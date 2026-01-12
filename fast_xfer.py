#!/usr/bin/env python3
"""
fast_xfer.py - Highly-tuned Linux-to-Linux file transfer wrapper for rsync/ssh, with optional zstd compression
and parallel chunking for very large files.

Typical uses:
  - auto: choose best strategy (compress if text compresses well; else direct rsync)
  - direct: rsync the file (optionally append-only or whole-file)
  - compress: zstd -> rsync -> remote unzstd (ends up with original filename on target)
  - chunked: split into parts, (optional zstd per part), parallel rsync, remote reassemble

Requires:
  - ssh + rsync on both ends
Optional:
  - zstd on both ends (for compression strategies)
  - split on source (for chunked strategy)
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional, Tuple

# Try to import select for non-blocking I/O (Unix only)
try:
    import select
    HAS_SELECT = True
except ImportError:
    HAS_SELECT = False
    select = None


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def fmt_cmd(cmd: Iterable[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def run_checked(cmd: list[str], *, capture: bool = False, env: Optional[dict[str, str]] = None) -> str:
    eprint("+", fmt_cmd(cmd))
    if capture:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        return (p.stdout or "") + (p.stderr or "")
    subprocess.run(cmd, check=True, env=env)
    return ""


def run_stream(cmd: list[str], *, env: Optional[dict[str, str]] = None) -> None:
    """Run a command and stream combined stdout/stderr to our stdout."""
    eprint("+", fmt_cmd(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"Command failed (exit={rc}): {fmt_cmd(cmd)}")


TARGET_RE = re.compile(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<path>.+)$")


def parse_target(target: str, default_user: Optional[str]) -> Tuple[bool, Optional[str], Optional[str], str]:
    """
    Parse target like:
      user@10.0.0.15:/data/path  (remote)
      10.0.0.15:/data/path        (remote)
      /data/path                  (local)
    Returns (is_local, user, host, path).
    """
    target = target.strip()
    
    # Check if it's a local path (absolute path without user@host: prefix)
    if target.startswith("/") and ":" not in target:
        # Local path - no user, no host
        return True, None, None, target
    
    # Try to match remote pattern
    m = TARGET_RE.match(target)
    if not m:
        # If it doesn't match remote pattern but starts with /, treat as local
        if target.startswith("/"):
            return True, None, None, target
        raise ValueError("Target must be an absolute path (/path) or remote (user@host:/path or host:/path)")
    
    # Remote path
    user = m.group("user") or (default_user or os.getenv("USER") or "")
    host = m.group("host")
    path = m.group("path")
    if not user:
        raise ValueError("Could not determine ssh user; pass target as user@host:/path or set --user")
    if not path.startswith("/"):
        raise ValueError("Target path must be an absolute path (start with /)")
    return False, user, host, path


def ssh_base_args(connect_timeout: int, cipher: str, control_path: Optional[str]) -> list[str]:
    args = [
        "ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "Compression=no",
        "-o", "IPQoS=throughput",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-c", cipher,
    ]
    if control_path:
        args += [
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=10m",
            "-o", f"ControlPath={control_path}",
        ]
    return args


def pick_ssh_cipher(user: str, host: str, connect_timeout: int, control_path: Optional[str]) -> str:
    """
    Pick a fast cipher that both ends accept.
    Tries aes128-gcm, then chacha20-poly1305.
    """
    candidates = ["aes128-gcm@openssh.com", "chacha20-poly1305@openssh.com"]
    for c in candidates:
        cmd = ssh_base_args(connect_timeout, c, control_path) + [f"{user}@{host}", "true"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            return c
        except subprocess.CalledProcessError:
            continue
    return "aes128-gcm@openssh.com"


def ssh_cmd_str(connect_timeout: int, cipher: str, control_path: Optional[str]) -> str:
    """String form for rsync -e."""
    args = ssh_base_args(connect_timeout, cipher, control_path)
    return fmt_cmd(args)


def remote_has_cmd(user: str, host: str, connect_timeout: int, cipher: str, control_path: Optional[str], cmdname: str) -> bool:
    cmd = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", f"command -v {shlex.quote(cmdname)} >/dev/null 2>&1"]
    return subprocess.run(cmd).returncode == 0


def remote_mkdir_p(user: str, host: str, connect_timeout: int, cipher: str, control_path: Optional[str], directory: str) -> None:
    directory_q = shlex.quote(directory)
    cmd = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", f"mkdir -p {directory_q}"]
    run_checked(cmd)


def get_compressor_cmd(compressor: str) -> Optional[tuple[str, str, str]]:
    """
    Returns (compress_cmd, decompress_cmd, extension) for the given compressor.
    Returns None if compressor is not available.
    """
    if compressor == "zstd":
        if which("zstd"):
            return ("zstd", "zstd", ".zst")
        return None
    elif compressor == "pigz":
        if which("pigz"):
            return ("pigz", "pigz", ".gz")
        # Fallback to gzip if pigz not available
        if which("gzip"):
            return ("gzip", "gunzip", ".gz")
        return None
    elif compressor == "gzip":
        if which("gzip"):
            return ("gzip", "gunzip", ".gz")
        return None
    return None


def estimate_compression_ratio(src: Path, compressor: str, level: int, sample_bytes: int, timeout: int = 30) -> Optional[Tuple[float, int, int]]:
    """
    Return (ratio, in_bytes, out_bytes) for a sample.
    ratio = out/in (lower is better).
    Supports zstd, pigz, gzip.
    timeout: seconds to wait before giving up (default: 30)
    """
    comp_info = get_compressor_cmd(compressor)
    if not comp_info:
        return None
    
    comp_cmd, _, _ = comp_info
    in_bytes = 0
    out_bytes = 0

    # Build compression command based on algorithm
    if compressor == "zstd":
        cmd = [comp_cmd, f"-{level}", "-T0", "-c", "--no-progress"]
    elif compressor == "pigz":
        # pigz: use default threads for sampling (omit -p for auto)
        cmd = [comp_cmd, f"-{level}", "-c"]
    elif compressor == "gzip":
        cmd = [comp_cmd, f"-{level}", "-c"]
    else:
        return None

    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert p.stdin is not None and p.stdout is not None

    start_time = time.time()
    
    try:
        # Write input with timeout check
        with src.open("rb") as f:
            remaining = sample_bytes
            while remaining > 0:
                if time.time() - start_time > timeout:
                    eprint(f"[estimate] Timeout after {timeout}s, skipping compression estimation")
                    break
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    p.stdin.write(chunk)
                    p.stdin.flush()  # Ensure data is sent
                    in_bytes += len(chunk)
                    remaining -= len(chunk)
                except BrokenPipeError:
                    # Process terminated early, check return code
                    break
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass

        # Read output with timeout
        # Use simpler approach: read in chunks with timeout checks
        while True:
            if time.time() - start_time > timeout:
                eprint(f"[estimate] Timeout reading output after {timeout}s")
                break
                
            # Check if process is done
            if p.poll() is not None:
                # Process finished, read remaining
                remaining = p.stdout.read(1024 * 1024)
                if remaining:
                    out_bytes += len(remaining)
                break
            
            # Try to read (may block briefly, but we check timeout)
            try:
                if HAS_SELECT and sys.platform != "win32":
                    # Unix: use select for non-blocking check
                    ready, _, _ = select.select([p.stdout], [], [], 0.5)
                    if ready:
                        chunk = p.stdout.read(1024 * 1024)
                        if not chunk:
                            if p.poll() is not None:
                                break
                            continue
                        out_bytes += len(chunk)
                    elif p.poll() is not None:
                        # Process finished
                        chunk = p.stdout.read(1024 * 1024)
                        if chunk:
                            out_bytes += len(chunk)
                        break
                else:
                    # Windows or no select: read with small timeout
                    chunk = p.stdout.read(1024 * 1024)
                    if not chunk:
                        if p.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    out_bytes += len(chunk)
            except (OSError, ValueError):
                # Pipe closed or error
                break
        
        try:
            p.stdout.close()
        except Exception:
            pass

        # Wait for process with timeout
        try:
            rc = p.wait(timeout=max(1, timeout - (time.time() - start_time)))
        except subprocess.TimeoutExpired:
            eprint(f"[estimate] Process timeout, killing")
            p.kill()
            p.wait()
            return None
            
        if rc != 0 or in_bytes == 0:
            return None
        ratio = out_bytes / in_bytes
        return ratio, in_bytes, out_bytes
    except BrokenPipeError:
        # Process terminated early, likely an error
        return None
    finally:
        try:
            if p.poll() is None:
                p.kill()
                p.wait()
            # Clean up stdin/stdout if still open
            try:
                if p.stdin and not p.stdin.closed:
                    p.stdin.close()
            except Exception:
                pass
            try:
                if p.stdout and not p.stdout.closed:
                    p.stdout.close()
            except Exception:
                pass
        except Exception:
            pass


def human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    x = float(n)
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f}{u}"
        x /= 1024.0
    return f"{n}B"


def build_rsync_cmd(
    src: str,
    dest: str,
    ssh_e: Optional[str],
    *,
    append_only: bool,
    whole_file: bool,
    inplace: bool,
    preallocate: bool,
    timeout: int,
) -> list[str]:
    cmd: list[str] = [
        "rsync",
        "-rtvh",
        "--info=progress2",
        "--partial",
        "--protect-args",
        f"--timeout={timeout}",
    ]
    if ssh_e:
        cmd.extend(["-e", ssh_e])
    if inplace:
        cmd.append("--inplace")
    if preallocate:
        cmd.append("--preallocate")
    if append_only:
        cmd.append("--append-verify")
    elif whole_file:
        cmd.append("--whole-file")
    cmd += [src, dest]
    return cmd


def normalize_dest_path(target_path: str, src_file: Path) -> Tuple[str, str]:
    """
    Decide dest_dir and dest_file path.
    Heuristic:
      - if target_path ends with '/', treat as directory
      - else treat as file path
    Returns (dest_dir, dest_file)
    """
    if target_path.endswith("/"):
        dest_dir = target_path.rstrip("/")
        dest_file = f"{dest_dir}/{src_file.name}"
        return dest_dir, dest_file
    dest_file = target_path
    dest_dir = str(Path(target_path).parent)
    return dest_dir, dest_file


def strategy_direct(args: argparse.Namespace, is_local: bool, user: Optional[str], host: Optional[str], dest_file: str, ssh_e: Optional[str]) -> None:
    if is_local:
        dest = dest_file
    else:
        dest = f"{user}@{host}:{dest_file}"
    cmd = build_rsync_cmd(
        str(args.source),
        dest,
        ssh_e,
        append_only=args.append_only,
        whole_file=args.whole_file,
        inplace=args.inplace,
        preallocate=args.preallocate,
        timeout=args.rsync_timeout,
    )
    run_stream(cmd)


def strategy_compress(args: argparse.Namespace, is_local: bool, user: Optional[str], host: Optional[str], dest_file: str, ssh_e: Optional[str], control_path: Optional[str], cipher: Optional[str]) -> None:
    compressor = args.compressor
    comp_info = get_compressor_cmd(compressor)
    if not comp_info:
        raise RuntimeError(f"Strategy 'compress' requires {compressor} installed (command: {compressor}).")
    
    comp_cmd, decomp_cmd, ext = comp_info
    
    if not is_local:
        assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
        # Check if remote has the decompressor
        if compressor == "zstd":
            remote_cmd_check = "zstd"
        elif compressor in ("pigz", "gzip"):
            remote_cmd_check = "gunzip" if which("gunzip") else "gzip"
        else:
            remote_cmd_check = decomp_cmd
        
        if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, remote_cmd_check):
            raise RuntimeError(f"Strategy 'compress' requires {compressor} decompressor ({remote_cmd_check}) installed on TARGET as well.")

    src = Path(args.source).resolve()
    workdir = Path(args.workdir).resolve() if args.workdir else src.parent
    workdir.mkdir(parents=True, exist_ok=True)

    comp_local = workdir / (src.name + ext)
    comp_dest = dest_file + ext

    # Build compression command
    comp_level = args.compression_level
    eprint(f"[compress] Compressing {src.name} with {compressor} level {comp_level}...")
    
    if compressor == "zstd":
        cmd = [comp_cmd, f"-{comp_level}", "-T0", "--no-progress", "-o", str(comp_local), str(src)]
        run_stream(cmd)
    elif compressor == "pigz":
        threads = args.compression_threads if hasattr(args, 'compression_threads') else 0
        # pigz: when using -c, it reads from stdin, so we need to redirect input
        # Build command: pigz -9 [-p N] -c
        if threads > 0:
            cmd = [comp_cmd, f"-{comp_level}", "-p", str(threads), "-c"]
        else:
            cmd = [comp_cmd, f"-{comp_level}", "-c"]
        # pigz -c reads from stdin and outputs to stdout
        with open(src, "rb") as infile, open(comp_local, "wb") as outfile:
            subprocess.run(cmd, stdin=infile, stdout=outfile, check=True, stderr=subprocess.PIPE)
    elif compressor == "gzip":
        cmd = [comp_cmd, f"-{comp_level}", "-c", str(src)]
        # gzip -c outputs to stdout
        with open(comp_local, "wb") as out:
            subprocess.run(cmd, stdout=out, check=True, stderr=subprocess.PIPE)
    else:
        raise RuntimeError(f"Unknown compressor: {compressor}")

    eprint(f"[compress] Transferring compressed file...")
    if is_local:
        dest = comp_dest
    else:
        dest = f"{user}@{host}:{comp_dest}"
    cmd = build_rsync_cmd(
        str(comp_local),
        dest,
        ssh_e,
        append_only=False,
        whole_file=True,
        inplace=False,
        preallocate=args.preallocate,
        timeout=args.rsync_timeout,
    )
    run_stream(cmd)

    eprint(f"[compress] Decompressing on destination...")
    if is_local:
        # Local decompression
        if compressor == "zstd":
            if which("unzstd"):
                run_checked(["unzstd", "-T0", "-f", "--rm", str(comp_dest)])
            else:
                run_checked([decomp_cmd, "-d", "-T0", "-f", str(comp_dest)])
                try:
                    Path(comp_dest).unlink()
                except FileNotFoundError:
                    pass
        elif compressor in ("pigz", "gzip"):
            run_checked([decomp_cmd, "-f", str(comp_dest)])
    else:
        # Remote decompression
        if compressor == "zstd":
            remote_cmd = f"""
set -euo pipefail
if command -v unzstd >/dev/null 2>&1; then
  unzstd -T0 -f --rm {shlex.quote(comp_dest)}
else
  zstd -d -T0 -f {shlex.quote(comp_dest)}
  rm -f {shlex.quote(comp_dest)}
fi
"""
        else:  # pigz/gzip
            remote_cmd = f"""
set -euo pipefail
gunzip -f {shlex.quote(comp_dest)} || gzip -d -f {shlex.quote(comp_dest)}
"""
        run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", remote_cmd])

    if not args.keep_local_artifact:
        try:
            comp_local.unlink()
            eprint(f"[compress] Cleaned up local artifact: {comp_local}")
        except FileNotFoundError:
            pass


def split_file(src: Path, part_prefix: Path, chunk_size: str) -> list[Path]:
    if which("split") is None:
        raise RuntimeError("Strategy 'chunked' requires 'split' installed on SOURCE.")
    part_prefix.parent.mkdir(parents=True, exist_ok=True)

    eprint(f"[chunked] Splitting {src.name} into {chunk_size} chunks...")
    cmd = [
        "split",
        "-b", chunk_size,
        "--numeric-suffixes=0",
        "--suffix-length=4",
        str(src),
        str(part_prefix),
    ]
    run_checked(cmd)

    parts = sorted(part_prefix.parent.glob(part_prefix.name + "*"))
    if not parts:
        raise RuntimeError("split produced no parts (unexpected).")
    eprint(f"[chunked] Created {len(parts)} parts")
    return parts


def compress_parts(parts: list[Path], compressor: str, level: int, parallel: int, keep_parts: bool) -> list[Path]:
    comp_info = get_compressor_cmd(compressor)
    if not comp_info:
        raise RuntimeError(f"Chunk compression requires {compressor} installed on SOURCE.")
    
    comp_cmd, _, ext = comp_info
    out: list[Path] = []

    eprint(f"[chunked] Compressing {len(parts)} parts with {compressor} level {level} (parallel={parallel})...")

    def do_one(p: Path) -> Path:
        comp_file = Path(str(p) + ext)
        
        if compressor == "zstd":
            run_checked([comp_cmd, f"-{level}", "-T1", "--no-progress", "-o", str(comp_file), str(p)])
        elif compressor == "pigz":
            # pigz -c reads from stdin, so redirect input
            cmd = [comp_cmd, f"-{level}", "-p", "1", "-c"]
            with open(p, "rb") as infile, open(comp_file, "wb") as outfile:
                subprocess.run(cmd, stdin=infile, stdout=outfile, check=True, stderr=subprocess.PIPE)
        elif compressor == "gzip":
            cmd = [comp_cmd, f"-{level}", "-c", str(p)]
            with open(comp_file, "wb") as out:
                subprocess.run(cmd, stdout=out, check=True, stderr=subprocess.PIPE)
        
        if not keep_parts:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        return comp_file

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = [ex.submit(do_one, p) for p in parts]
        for fut in as_completed(futs):
            out.append(fut.result())

    eprint(f"[chunked] Compressed all parts")
    return sorted(out)


def rsync_many_parallel(
    files: list[Path],
    is_local: bool,
    user: Optional[str],
    host: Optional[str],
    dest_dir: str,
    ssh_e: Optional[str],
    parallel: int,
    rsync_timeout: int,
) -> None:
    if is_local:
        dest_dir_str = f"{dest_dir.rstrip('/')}/"
    else:
        dest_dir_str = f"{user}@{host}:{dest_dir.rstrip('/')}/"

    eprint(f"[chunked] Transferring {len(files)} files in parallel (workers={parallel})...")

    def send_one(p: Path) -> tuple[Path, bool, Optional[str]]:
        """Returns (file_path, success, error_message)"""
        cmd = [
            "rsync",
            "-rtv",  # Removed -h and --info=progress2 to reduce output
            "--partial",
            "--protect-args",
            f"--timeout={rsync_timeout}",
            "--whole-file",
            "--info=name0",  # Minimal output: only show file names, no progress
        ]
        if ssh_e:
            cmd.extend(["-e", ssh_e])
        cmd.extend([str(p), dest_dir_str])
        
        try:
            # Run without streaming to avoid blocking - capture output instead
            # This allows true parallel execution
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,  # Suppress output for parallel transfers
                stderr=subprocess.PIPE,
                check=True,
            )
            return (p, True, None)
        except subprocess.CalledProcessError as e:
            error_msg = f"{e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else e.stderr or 'unknown error'}"
            return (p, False, error_msg)

    # Run transfers in parallel
    completed = 0
    failed = []
    total = len(files)
    eprint(f"[chunked] Starting parallel transfer of {total} files with {parallel} workers...")
    
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = {ex.submit(send_one, f): f for f in files}
        for fut in as_completed(futs):
            file_path, success, error = fut.result()
            completed += 1
            if not success:
                failed.append((file_path, error))
            # Show progress every 10% or on completion
            if completed % max(1, total // 10) == 0 or completed == total:
                eprint(f"[chunked] Progress: {completed}/{total} files transferred")

    if failed:
        eprint(f"[chunked] ERROR: Failed to transfer {len(failed)}/{total} files:")
        for fpath, err in failed[:5]:  # Show first 5 errors
            eprint(f"  - {fpath.name}: {err}")
        if len(failed) > 5:
            eprint(f"  ... and {len(failed) - 5} more failures")
        raise RuntimeError(f"Failed to transfer {len(failed)} files")

    eprint(f"[chunked] ✓ All {total} parts transferred successfully")


def local_mkdir_p(directory: str) -> None:
    Path(directory).mkdir(parents=True, exist_ok=True)


def strategy_chunked(args: argparse.Namespace, is_local: bool, user: Optional[str], host: Optional[str], dest_file: str, dest_dir: str, ssh_e: Optional[str], control_path: Optional[str], cipher: Optional[str]) -> None:
    src = Path(args.source).resolve()
    if args.workdir:
        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        tmpdir = workdir / f".xfer_{src.name}_{int(time.time())}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        cleanup_tmpdir = args.cleanup_workdir
    else:
        # Use user-specified temp dir or system default (respects TMPDIR env var)
        temp_base = args.temp_dir if hasattr(args, 'temp_dir') and args.temp_dir else tempfile.gettempdir()
        tmpdir = Path(tempfile.mkdtemp(prefix=f"xfer_{src.name}_", dir=temp_base))
        cleanup_tmpdir = True

    part_prefix = tmpdir / "part."
    parts = split_file(src, part_prefix, args.chunk_size)

    parts_to_send: list[Path] = parts
    if args.compress_chunks:
        compressor = args.compressor
        comp_info = get_compressor_cmd(compressor)
        if not comp_info:
            raise RuntimeError(f"Chunk compression requires {compressor} installed on SOURCE.")
        
        _, decomp_cmd, ext = comp_info
        
        if not is_local:
            assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
            # Check for decompressor on remote
            if compressor == "zstd":
                remote_cmd_check = "zstd"
            elif compressor in ("pigz", "gzip"):
                remote_cmd_check = "gunzip" if which("gunzip") else "gzip"
            else:
                remote_cmd_check = decomp_cmd
            
            if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, remote_cmd_check):
                raise RuntimeError(f"Chunk compression requires {compressor} decompressor ({remote_cmd_check}) installed on TARGET as well.")
        
        parts_to_send = compress_parts(parts, compressor, args.compression_level, args.parallel, keep_parts=args.keep_local_parts)

    stage_dir = f"{dest_dir.rstrip('/')}/._xfer_{src.name}_{int(time.time())}"
    if is_local:
        local_mkdir_p(stage_dir)
    else:
        assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
        remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, stage_dir)

    rsync_many_parallel(parts_to_send, is_local, user, host, stage_dir, ssh_e, args.parallel, args.rsync_timeout)

    eprint(f"[chunked] Reassembling file on destination...")
    stage_q = shlex.quote(stage_dir)
    dest_q = shlex.quote(dest_file)
    if args.compress_chunks:
        compressor = args.compressor
        _, decomp_cmd, ext = get_compressor_cmd(compressor) or (None, None, None)
        
        if compressor == "zstd":
            decomp_cmd_str = "zstd -d -c"
            pattern = "part.*.zst"
        elif compressor in ("pigz", "gzip"):
            decomp_cmd_str = "gunzip -c || gzip -d -c"
            pattern = "part.*.gz"
        else:
            decomp_cmd_str = f"{decomp_cmd} -d -c"
            pattern = f"part.*{ext}"
        
        assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
: > "$tmp"
for f in $(ls -1 {pattern} | sort); do
  {decomp_cmd_str} "$f" >> "$tmp"
  rm -f "$f"
done
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
    else:
        assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
: > "$tmp"
for f in $(ls -1 part.* | sort); do
  cat "$f" >> "$tmp"
  rm -f "$f"
done
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
    if is_local:
        run_checked(["bash", "-c", assemble_cmd])
    else:
        run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", assemble_cmd])

    if args.cleanup_local_parts:
        for p in parts_to_send:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        try:
            for child in tmpdir.glob("*"):
                child.unlink()
            tmpdir.rmdir()
        except Exception:
            pass
    if cleanup_tmpdir:
        try:
            for child in tmpdir.glob("*"):
                child.unlink()
            tmpdir.rmdir()
            eprint(f"[chunked] Cleaned up temporary directory: {tmpdir}")
        except Exception:
            pass


def sha256sum_local(path: Path) -> str:
    h = subprocess.run(["sha256sum", str(path)], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split()[0]
    return h


def sha256sum_remote(user: str, host: str, connect_timeout: int, cipher: str, control_path: Optional[str], remote_path: str) -> str:
    cmd = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", f"sha256sum {shlex.quote(remote_path)} | awk '{{print $1}}'"]
    out = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    return out


def sha256sum_local_path(path: str) -> str:
    h = subprocess.run(["sha256sum", path], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split()[0]
    return h


def main() -> int:
    p = argparse.ArgumentParser(
        description="Highly-tuned Linux-to-Linux file transfer wrapper (rsync/ssh, optional zstd, optional chunk parallelism).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", type=Path, help="Source file path on this machine")
    p.add_argument("target", help="Target: /abs/path (local) OR user@10.0.0.15:/abs/path OR 10.0.0.15:/abs/path (remote, absolute path required)")
    p.add_argument("--user", default=None, help="SSH user (if not provided in target)")
    p.add_argument("--strategy", choices=["auto", "direct", "compress", "chunked"], default="auto", help="Transfer strategy (chunked=split+transfer, use --compress-chunks for split+compress)")
    p.add_argument("--append-only", action="store_true", help="Use rsync --append-verify (only if file only grows by appending)")
    p.add_argument("--whole-file", action="store_true", help="Use rsync --whole-file (fastest first transfer, weakest resume)")
    p.add_argument("--inplace", action="store_true", help="Use rsync --inplace (better resume semantics; can be riskier if interrupted)")
    p.add_argument("--preallocate", action="store_true", help="Use rsync --preallocate when possible")
    p.add_argument("--connect-timeout", type=int, default=10, help="SSH connect timeout (seconds)")
    p.add_argument("--rsync-timeout", type=int, default=0, help="rsync I/O timeout (0 = disabled)")
    p.add_argument("--workdir", default=None, help="Working directory for artifacts/parts (default: alongside source, or temp for chunked)")
    p.add_argument("--cleanup-workdir", action="store_true", help="If --workdir is used with chunked, remove temp subdir after success")
    p.add_argument("--compressor", choices=["zstd", "pigz", "gzip"], default="pigz", help="Compression algorithm (pigz=fast parallel gzip, zstd=better ratio, gzip=fallback)")
    p.add_argument("--compression-level", type=int, default=6, help="Compression level (1=fast, 6=default for pigz/gzip, 3=default for zstd)")
    p.add_argument("--compression-threads", type=int, default=0, help="Threads for compression (0=auto, pigz only)")
    p.add_argument("--keep-local-artifact", action="store_true", help="Keep local compressed artifact for compress strategy")
    p.add_argument("--chunk-size", default="20G", help="Chunk size for chunked strategy (e.g., 4G, 20G, 500M). Optimal: 5-20G for 10G links, 10-50G for 25G+, smaller for slower links")
    p.add_argument("--parallel", type=int, default=1, help="Parallel transfers for chunked strategy")
    p.add_argument("--compress-chunks", action="store_true", help="In chunked mode, compress each chunk before transfer")
    p.add_argument("--keep-local-parts", action="store_true", help="Keep uncompressed local parts after compressing chunks")
    p.add_argument("--cleanup-local-parts", action="store_true", help="Delete local parts after successful chunked transfer")
    p.add_argument("--zstd-level", type=int, default=3, help="[DEPRECATED] Use --compression-level instead. zstd compression level (1=fast, 3=default)")
    p.add_argument("--auto-sample-mib", type=int, default=256, help="Auto mode: sample size (MiB) to estimate compressibility")
    p.add_argument("--auto-threshold", type=float, default=0.85, help="Auto mode: choose compress if compression(out/in) <= threshold")
    p.add_argument("--skip-estimate", action="store_true", help="Skip compression estimation in auto mode (use direct transfer)")
    p.add_argument("--estimate-timeout", type=int, default=30, help="Timeout in seconds for compression estimation (default: 30)")
    p.add_argument("--temp-dir", default=None, help="Temporary directory for SSH control sockets (default: system temp, respects TMPDIR env var)")
    p.add_argument("--verify-sha256", action="store_true", help="Compute sha256 on source+target after transfer (slow for huge files)")

    args = p.parse_args()

    # Handle deprecated --zstd-level, map to compression-level if set
    # If user explicitly set --zstd-level and didn't set --compression-level, use zstd-level
    if hasattr(args, 'zstd_level'):
        # Check if compression_level is still at default (6) and zstd_level was explicitly set
        # We can't detect if it was explicitly set, so we'll use it if compressor is zstd
        if args.compressor == "zstd" and args.compression_level == 6:
            args.compression_level = args.zstd_level

    src = args.source.resolve()
    if not src.exists() or not src.is_file():
        eprint(f"ERROR: source file not found: {src}")
        return 2

    if which("rsync") is None:
        eprint("ERROR: requires rsync installed.")
        return 2

    is_local, user, host, target_path = parse_target(args.target, args.user)
    dest_dir, dest_file = normalize_dest_path(target_path, src)

    # For local transfers, we don't need SSH
    if is_local:
        eprint("[local] Detected local path - using direct file operations")
        local_mkdir_p(dest_dir)
        ssh_e = None
        control_path = None
        cipher = None
    else:
        if which("ssh") is None:
            eprint("ERROR: requires ssh installed for remote transfers.")
            return 2
        # Use user-specified temp dir or system default (respects TMPDIR env var)
        temp_base = args.temp_dir if hasattr(args, 'temp_dir') and args.temp_dir else tempfile.gettempdir()
        control_path = os.path.join(temp_base, f"sshcm-{os.getpid()}-%r@%h:%p")
        cipher = pick_ssh_cipher(user, host, args.connect_timeout, control_path)
        ssh_e = ssh_cmd_str(args.connect_timeout, cipher, control_path)
        remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, dest_dir)

    strategy = args.strategy
    if strategy == "auto":
        # Auto rule of thumb:
        #   1) If both ends have zstd and the file looks compressible -> compress (fastest over constrained links)
        #   2) Else -> direct rsync
        # Chunked/parallel is powerful but operationally heavier, so it's opt-in via --strategy chunked.
        if args.append_only:
            strategy = "direct"
        else:
            # Check if compressor is available
            compressor = args.compressor
            comp_info = get_compressor_cmd(compressor)
            
            if args.skip_estimate:
                # Skip estimation, use direct
                eprint("[auto] Skipping compression estimation (--skip-estimate)")
                strategy = "direct"
            elif is_local:
                # For local, check if compressor is available
                if comp_info:
                    eprint(f"[auto] Estimating compression ratio with {compressor}...")
                    sample_bytes = args.auto_sample_mib * 1024**2
                    est = estimate_compression_ratio(src, compressor, args.compression_level, sample_bytes, args.estimate_timeout)
                    if est:
                        ratio, in_b, out_b = est
                        eprint(f"[auto] {compressor} sample: in={human_bytes(in_b)} out={human_bytes(out_b)} ratio={ratio:.3f}")
                        if ratio <= args.auto_threshold:
                            strategy = "compress"
                        else:
                            strategy = "direct"
                    else:
                        eprint("[auto] Compression estimation failed or timed out, using direct transfer")
                        strategy = "direct"
                else:
                    strategy = "direct"
            else:
                assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
                if comp_info:
                    # Check if remote has decompressor
                    _, decomp_cmd, _ = comp_info
                    if compressor == "zstd":
                        remote_cmd_check = "zstd"
                    elif compressor in ("pigz", "gzip"):
                        remote_cmd_check = "gunzip" if which("gunzip") else "gzip"
                    else:
                        remote_cmd_check = decomp_cmd
                    
                    if remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, remote_cmd_check):
                        eprint(f"[auto] Estimating compression ratio with {compressor}...")
                        sample_bytes = args.auto_sample_mib * 1024**2
                        est = estimate_compression_ratio(src, compressor, args.compression_level, sample_bytes, args.estimate_timeout)
                        if est:
                            ratio, in_b, out_b = est
                            eprint(f"[auto] {compressor} sample: in={human_bytes(in_b)} out={human_bytes(out_b)} ratio={ratio:.3f}")
                            if ratio <= args.auto_threshold:
                                strategy = "compress"
                            else:
                                strategy = "direct"
                        else:
                            eprint("[auto] Compression estimation failed or timed out, using direct transfer")
                            strategy = "direct"
                    else:
                        strategy = "direct"
                else:
                    strategy = "direct"

    start = time.time()
    if is_local:
        eprint(f"=== Strategy: {strategy} | src={src} -> {dest_file} (local) ===")
    else:
        eprint(f"=== Strategy: {strategy} | src={src} -> {user}@{host}:{dest_file} ===")

    try:
        if strategy == "direct":
            strategy_direct(args, is_local, user, host, dest_file, ssh_e)
        elif strategy == "compress":
            strategy_compress(args, is_local, user, host, dest_file, ssh_e, control_path, cipher)
        elif strategy == "chunked":
            strategy_chunked(args, is_local, user, host, dest_file, dest_dir, ssh_e, control_path, cipher)
        else:
            raise RuntimeError(f"Unknown strategy: {strategy}")

        if args.verify_sha256:
            eprint("=== Verifying sha256 (this will read the full file on both ends) ===")
            local_h = sha256sum_local(src)
            if is_local:
                remote_h = sha256sum_local_path(dest_file)
            else:
                remote_h = sha256sum_remote(user, host, args.connect_timeout, cipher, control_path, dest_file)
            eprint(f"source sha256:  {local_h}")
            eprint(f"dest sha256:    {remote_h}")
            if local_h != remote_h:
                raise RuntimeError("sha256 mismatch: transfer may be corrupted")

        elapsed = time.time() - start
        eprint(f"=== Done in {elapsed:.1f}s ===")
        return 0
    except Exception as ex:
        eprint(f"ERROR: {ex}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

