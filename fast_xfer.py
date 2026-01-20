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

# Note: We use typing.List, typing.Dict, typing.Tuple for Python 3.6 compatibility
# instead of from __future__ import annotations (which requires Python 3.7+)

import argparse
import sys
import os
import queue
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Try to import select for non-blocking I/O (Unix only)
try:
    import select
    HAS_SELECT = True
except ImportError:
    HAS_SELECT = False
    select = None

# Try to import Python zstandard library (optional, falls back to CLI)
try:
    import zstandard as zstd_lib
    HAS_ZSTD_LIB = True
except ImportError:
    HAS_ZSTD_LIB = False
    zstd_lib = None


def eprint(*args: object, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def fmt_cmd(cmd: Iterable[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def run_checked(cmd: List[str], *, capture: bool = False, env: Optional[Dict[str, str]] = None) -> str:
    eprint("+", fmt_cmd(cmd))
    if capture:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        return (p.stdout or "") + (p.stderr or "")
    subprocess.run(cmd, check=True, env=env)
    return ""


def run_stream(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> None:
    """Run a command and stream combined stdout/stderr to our stdout."""
    eprint("+", fmt_cmd(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = p.wait()
    if rc != 0:
        # Special-case rsync exit 23 to give a clearer explanation
        base_cmd = os.path.basename(cmd[0]) if cmd else ""
        if base_cmd == "rsync" and rc == 23:
            eprint(
                "[dir] rsync exit code 23: some files or attributes were NOT transferred.\n"
                "      Common causes:\n"
                "        - Permission denied reading some files on source\n"
                "        - Permission denied setting owner/group/ACL/xattrs on destination\n"
                "        - Files vanished during transfer (deleted/rotated while rsync was running)\n"
                "        - Destination filesystem does not support some attributes (ACLs/xattrs)\n"
                "      Scroll up to see the specific 'rsync:' ERROR/WARNING lines above."
            )
        raise RuntimeError(f"Command failed (exit={rc}): {fmt_cmd(cmd)}")


TARGET_RE = re.compile(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<path>.+)$")


def get_nfs_info(path: str) -> Optional[Tuple[str, str]]:
    """
    Detect if a path is on an NFS mount and return (server, export_path).
    Returns None if not NFS or detection fails.
    """
    try:
        # Use findmnt to get mount info (more reliable than /proc/mounts)
        # findmnt -n -o SOURCE,TARGET <path> returns: server:/export /mount/point
        result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE,TARGET", path],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout:
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                source = parts[0]
                # Check if it's NFS (starts with server: or server:/)
                if ":" in source and not source.startswith("/"):
                    # Extract server and export path
                    if "/" in source:
                        server, export_path = source.split("/", 1)
                        export_path = "/" + export_path
                    else:
                        server = source.rstrip(":")
                        export_path = "/"
                    return (server, export_path)
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def parse_target(target: str, default_user: Optional[str], nfs_server: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str], str]:
    """
    Parse target like:
      user@10.0.0.15:/data/path  (remote)
      10.0.0.15:/data/path        (remote)
      /data/path                  (local, unless nfs_server is set)
    Returns (is_local, user, host, path).
    
    If nfs_server is provided and target is a local path, treat it as remote via NFS server.
    """
    target = target.strip()
    
    # Check if it's a local path (absolute path without user@host: prefix)
    if target.startswith("/") and ":" not in target:
        # If nfs_server is specified, treat as remote via NFS
        if nfs_server:
            user = default_user or os.getenv("USER") or ""
            if not user:
                raise ValueError("Could not determine ssh user for NFS streaming; set --user or --nfs-user")
            return False, user, nfs_server, target
        
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


def ssh_base_args(connect_timeout: int, cipher: Optional[str], control_path: Optional[str]) -> List[str]:
    args = [
        "ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "Compression=no",
        "-o", "IPQoS=throughput",
        "-o", f"ConnectTimeout={connect_timeout}",
    ]
    # Only specify cipher if one was successfully negotiated
    if cipher:
        args.extend(["-c", cipher])
    if control_path:
        args += [
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=10m",
            "-o", f"ControlPath={control_path}",
        ]
    return args


def pick_ssh_cipher(user: str, host: str, connect_timeout: int, control_path: Optional[str]) -> Optional[str]:
    """
    Pick a fast cipher that both ends accept.
    Tries multiple ciphers in order of preference (fastest first).
    Returns None if no cipher works (will let SSH auto-negotiate).
    """
    # Comprehensive list of ciphers in order of preference (fastest/secure first)
    candidates = [
        "aes128-gcm@openssh.com",      # Fast, modern
        "aes256-gcm@openssh.com",      # Fast, modern (server supports this)
        "chacha20-poly1305@openssh.com", # Fast, modern
        "aes256-ctr",                  # Common, server supports this
        "aes192-ctr",                  # Common, server supports this
        "aes128-ctr",                  # Common fallback
        "aes256-cbc",                  # Legacy fallback
        "aes128-cbc",                  # Legacy fallback
    ]
    
    for c in candidates:
        cmd = ssh_base_args(connect_timeout, c, control_path) + [f"{user}@{host}", "true"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=connect_timeout)
            eprint(f"[ssh] Selected cipher: {c}")
            return c
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    
    # If no explicit cipher works, return None to let SSH auto-negotiate
    eprint(f"[ssh] WARNING: Could not negotiate cipher, letting SSH auto-negotiate")
    return None


def ssh_cmd_str(connect_timeout: int, cipher: Optional[str], control_path: Optional[str]) -> str:
    """String form for rsync -e."""
    args = ssh_base_args(connect_timeout, cipher, control_path)
    return fmt_cmd(args)


def remote_has_cmd(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str], cmdname: str) -> bool:
    cmd = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", f"command -v {shlex.quote(cmdname)} >/dev/null 2>&1"]
    return subprocess.run(cmd).returncode == 0


def remote_mkdir_p(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str], directory: str) -> None:
    directory_q = shlex.quote(directory)
    cmd = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", f"mkdir -p {directory_q}"]
    run_checked(cmd)


def compress_file_python_zstd(src: Path, dst: Path, level: int, threads: int = 0) -> None:
    """Compress file using Python zstandard library."""
    if not HAS_ZSTD_LIB:
        raise RuntimeError("Python zstandard library not available. Install with: pip install zstandard")
    
    cctx = zstd_lib.ZstdCompressor(level=level, threads=threads if threads > 0 else None)
    
    with open(src, "rb") as infile, open(dst, "wb") as outfile:
        cctx.copy_stream(infile, outfile)


def decompress_file_python_zstd(src: Path, dst: Path, threads: int = 0) -> None:
    """Decompress file using Python zstandard library."""
    if not HAS_ZSTD_LIB:
        raise RuntimeError("Python zstandard library not available. Install with: pip install zstandard")
    
    dctx = zstd_lib.ZstdDecompressor(threads=threads if threads > 0 else None)
    
    with open(src, "rb") as infile, open(dst, "wb") as outfile:
        dctx.copy_stream(infile, outfile)


def get_compressor_cmd(compressor: str, prefer_python: bool = True) -> Optional[Tuple[str, str, str]]:
    """
    Returns (compress_cmd, decompress_cmd, extension) for the given compressor.
    For zstd, we *prefer* the Python zstandard library when available, but we never
    return a fake binary name like "python_zstd". We always return the logical
    CLI name ("zstd") and let higher-level code decide whether to call the CLI
    or use the Python library (HAS_ZSTD_LIB).

    Returns None if the compressor is not available at all (no CLI and no Python lib).
    """
    if compressor == "zstd":
        # If we have either the Python library OR the CLI, report zstd as available.
        if HAS_ZSTD_LIB or which("zstd"):
            return ("zstd", "zstd", ".zst")
        # Neither Python zstandard nor CLI zstd is available.
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
        # Prefer Python zstandard library for estimation when available
        if HAS_ZSTD_LIB:
            try:
                import multiprocessing
                threads = multiprocessing.cpu_count()
            except Exception:
                threads = 4

            cctx = zstd_lib.ZstdCompressor(level=level, threads=threads)
            start_time = time.time()
            with src.open("rb") as f:
                remaining = sample_bytes
                while remaining > 0:
                    if time.time() - start_time > timeout:
                        eprint(f"[estimate] Timeout after {timeout}s, skipping compression estimation")
                        break
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    in_bytes += len(chunk)
                    compressed = cctx.compress(chunk)
                    out_bytes += len(compressed)
                    remaining -= len(chunk)
            if in_bytes == 0:
                return None
            ratio = out_bytes / in_bytes
            return ratio, in_bytes, out_bytes
        else:
            # Fallback to CLI zstd
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


def parse_size_to_bytes(size: str) -> int:
    """
    Parse human size strings similar to coreutils (split/dd).
    Supports: 123, 10K, 10M, 10G, 10T, 10P, 10E, and SI forms like 10kB/MB/GB, and IEC like 10KiB/MiB/GiB.
    Returns integer bytes.
    """
    s = size.strip()
    if not s:
        raise ValueError("size is empty")

    # Split number and suffix
    m = re.fullmatch(r"(?P<num>\d+)(?P<suf>[A-Za-z]{0,3})", s)
    if not m:
        raise ValueError(f"invalid size: {size!r} (examples: 500M, 20G, 4GiB)")

    num = int(m.group("num"))
    suf = m.group("suf") or ""

    multipliers = {
        "": 1,
        "c": 1,
        "w": 2,
        "b": 512,

        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
        "E": 1024**6,

        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "PB": 1000**5,
        "EB": 1000**6,

        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
        "PiB": 1024**5,
        "EiB": 1024**6,
    }
    if suf not in multipliers:
        raise ValueError(f"invalid size suffix: {suf!r} (examples: K, M, G, kB, MiB)")

    return num * multipliers[suf]


def choose_block_size(chunk_bytes: int, *, max_bs: int = 16 * 1024 * 1024) -> int:
    """
    Pick a dd-friendly block size (bytes) that divides chunk_bytes.
    Larger bs reduces dd overhead. Caps at max_bs.
    """
    if chunk_bytes <= 0:
        return 1024 * 1024

    # Candidate sizes (bytes), descending.
    cands = [
        128 * 1024 * 1024,
        64 * 1024 * 1024,
        32 * 1024 * 1024,
        16 * 1024 * 1024,
        8 * 1024 * 1024,
        4 * 1024 * 1024,
        2 * 1024 * 1024,
        1024 * 1024,
        512 * 1024,
        256 * 1024,
        128 * 1024,
        64 * 1024,
        32 * 1024,
        16 * 1024,
        8 * 1024,
        4 * 1024,
        1024,
        512,
    ]
    for bs in cands:
        if bs > max_bs:
            continue
        if chunk_bytes % bs == 0:
            return bs
    return 1024 * 1024  # fallback


def local_cpu_count() -> int:
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except Exception:
        return 4


def remote_capture(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str], cmd: str) -> str:
    full = ssh_base_args(connect_timeout, cipher, control_path) + [f"{user}@{host}", cmd]
    p = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"remote command failed: {cmd}\n{p.stderr.strip()}")
    return (p.stdout or "").strip()


def remote_fs_type(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str], path: str) -> str:
    # %T is filesystem type (e.g., ext4, xfs, nfs)
    cmd = f"stat -f -c %T {shlex.quote(path)} 2>/dev/null || echo unknown"
    return remote_capture(user, host, connect_timeout, cipher, control_path, cmd)


def remote_cpu(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str]) -> int:
    cmd = "nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4"
    out = remote_capture(user, host, connect_timeout, cipher, control_path, cmd)
    try:
        return max(1, int(out.strip()))
    except Exception:
        return 4


def get_decompression_threads(requested: Optional[int]) -> int:
    """
    Get optimal number of threads for decompression.
    If requested is None or 0, auto-detect CPU count.
    """
    if requested is not None and requested > 0:
        return requested
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except:
        return 4  # fallback


def build_fast_decompression_cmd(compressor: str, decomp_cmd: str, threads: int, streaming: bool = False) -> str:
    """
    Build optimized decompression command for maximum speed.
    Returns command string optimized for the given compressor.
    """
    if compressor == "zstd":
        # zstd: use all threads, fast mode, streaming if needed
        if streaming:
            # For streaming: -d -c -T{N} --fast
            return f"zstd -d -c -T{threads} --fast"
        else:
            # For file decompression: prefer unzstd if available, use --fast for speed
            # unzstd is sometimes faster than zstd -d
            return f"unzstd -T{threads} --fast -f --rm 2>/dev/null || zstd -d -T{threads} --fast -f"
    elif compressor in ("pigz", "gzip"):
        # pigz: use parallel decompression with all threads
        if streaming:
            # For streaming: pigz -d -c -p {N}
            return f"pigz -d -c -p {threads} 2>/dev/null || gunzip -c || gzip -d -c"
        else:
            # For file decompression: prefer unpigz if available, use all threads
            return f"unpigz -p {threads} -f 2>/dev/null || pigz -d -p {threads} -f 2>/dev/null || gunzip -f || gzip -d -f"
    else:
        # Fallback for other compressors
        if streaming:
            return f"{decomp_cmd} -d -c"
        else:
            return f"{decomp_cmd} -d -f"


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
    rsync_compress: bool = False,
    rsync_compress_level: int = 1,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    cmd: List[str] = [
        "rsync",
        "-rtvh",
        "--info=progress2",
        "--partial",
        "--protect-args",
        f"--timeout={timeout}",
    ]
    if ssh_e:
        cmd.extend(["-e", ssh_e])
    if rsync_compress:
        # Use rsync's built-in compression (compresses on-the-fly during transfer)
        # This is more efficient than pre-compression for network transfers
        cmd.append("--compress")
        if rsync_compress_level > 0:
            cmd.append(f"--compress-level={rsync_compress_level}")
    if inplace:
        cmd.append("--inplace")
    if preallocate:
        cmd.append("--preallocate")
    if append_only:
        cmd.append("--append-verify")
    elif whole_file:
        cmd.append("--whole-file")
    if extra_args:
        cmd.extend(extra_args)
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
        # For local transfers, ALWAYS use direct copy (faster than rsync)
        src = Path(args.source).resolve()
        dest = Path(dest_file)
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        src_size = src.stat().st_size
        eprint(f"[local] Copying {src.name} ({human_bytes(src_size)})...")
        copy_start = time.time()
        import shutil
        shutil.copy2(str(src), str(dest))  # copy2 preserves metadata (like cp -p)
        copy_elapsed = time.time() - copy_start
        copy_speed = src_size / copy_elapsed if copy_elapsed > 0 else 0
        eprint(f"[local] Copy completed in {copy_elapsed:.1f}s ({human_bytes(copy_speed)}/s)")
    else:
        dest = f"{user}@{host}:{dest_file}"
        # Use rsync compression for remote transfers if enabled
        use_rsync_compress = args.rsync_compress if hasattr(args, 'rsync_compress') else False
        rsync_comp_level = args.rsync_compress_level if hasattr(args, 'rsync_compress_level') else 1
        cmd = build_rsync_cmd(
            str(args.source),
            dest,
            ssh_e,
            append_only=args.append_only,
            whole_file=args.whole_file,
            inplace=args.inplace,
            preallocate=args.preallocate,
            timeout=args.rsync_timeout,
            rsync_compress=use_rsync_compress,
            rsync_compress_level=rsync_comp_level,
        )
        if use_rsync_compress:
            eprint(f"[direct] Using rsync built-in compression (level {rsync_comp_level}) for on-the-fly compression")
        run_stream(cmd)


def strategy_dir_rsync(
    args: argparse.Namespace,
    is_local: bool,
    user: Optional[str],
    host: Optional[str],
    target_path: str,
    ssh_e: Optional[str],
) -> None:
    """
    Directory transfer strategy: use rsync to copy an entire directory tree (including nested folders).

    Semantics:
      - Copies *contents* of the source directory into the target path (like: rsync src_dir/ dest_dir/)
      - Works for both local and remote targets
      - Re-uses rsync compression flags if enabled via --rsync-compress
    """
    src = Path(args.source).resolve()
    if not src.is_dir():
        raise RuntimeError("strategy_dir_rsync called but source is not a directory")

    # rsync-style: src/ means "contents of src"
    src_arg = str(src)
    if not src_arg.endswith("/"):
        src_arg = src_arg + "/"

    dest_root = target_path
    # Ensure dest_root is treated as a directory
    if dest_root.endswith("/"):
        dest_root = dest_root.rstrip("/")
    dest_dir_arg = dest_root + "/"

    if is_local:
        # Local rsync (no ssh)
        dest_arg = dest_dir_arg
    else:
        assert user is not None and host is not None, "user and host must be set for remote directory transfers"
        dest_arg = f"{user}@{host}:{dest_dir_arg}"

    use_rsync_compress = args.rsync_compress if hasattr(args, "rsync_compress") else False
    rsync_comp_level = args.rsync_compress_level if hasattr(args, "rsync_compress_level") else 1

    # Optional: only transfer files older/newer than a given cutoff date (by mtime).
    # We implement this in Python by building a filtered file list and passing it
    # to rsync via --files-from, so it works even on older rsync versions.
    extra_rsync_args: List[str] = []
    before_date_str = getattr(args, "before_date", None)
    after_date_str = getattr(args, "after_date", None)
    if before_date_str and after_date_str:
        raise RuntimeError("Use only ONE of --before-date or --after-date (they are mutually exclusive).")

    files_from_path: Optional[str] = None
    if before_date_str or after_date_str:
        try:
            cutoff = datetime.datetime.strptime(
                before_date_str or after_date_str, "%Y-%m-%d"
            )
        except Exception as e:
            flag = "--before-date" if before_date_str else "--after-date"
            val = before_date_str or after_date_str
            raise RuntimeError(f"Invalid {flag} {val!r}: {e}")

        # Walk directory and select files based on mtime
        selected: List[Path] = []
        for root, _dirs, files in os.walk(src):
            root_path = Path(root)
            for name in files:
                p = root_path / name
                try:
                    mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime)
                except OSError:
                    continue
                if before_date_str and mtime < cutoff:
                    selected.append(p)
                elif after_date_str and mtime > cutoff:
                    selected.append(p)

        if not selected:
            if before_date_str:
                eprint(f"[dir] Filtering: no files found with mtime BEFORE {before_date_str}")
            else:
                eprint(f"[dir] Filtering: no files found with mtime AFTER {after_date_str}")
            return

        # Build a temporary --files-from list with paths relative to src root
        fd, files_from_path = tempfile.mkstemp(prefix="xfer_files_", suffix=".list")
        with os.fdopen(fd, "w") as f:
            for p in selected:
                rel = p.relative_to(src)
                f.write(str(rel).replace("\\", "/") + "\n")

        extra_rsync_args.append(f"--files-from={files_from_path}")
        if before_date_str:
            eprint(f"[dir] Filtering: transferring {len(selected)} files with mtime BEFORE {before_date_str}")
        else:
            eprint(f"[dir] Filtering: transferring {len(selected)} files with mtime AFTER {after_date_str}")

    # For directories we don't use append_only/whole_file/inplace/preallocate; rsync handles trees efficiently.
    cmd = build_rsync_cmd(
        src_arg,
        dest_arg,
        ssh_e,
        append_only=False,
        whole_file=False,
        inplace=False,
        preallocate=False,
        timeout=args.rsync_timeout,
        rsync_compress=use_rsync_compress,
        rsync_compress_level=rsync_comp_level,
        extra_args=extra_rsync_args or None,
    )

    if is_local:
        eprint(f"[dir] Using rsync for local directory copy: {src_arg} -> {dest_root}/")
    else:
        if use_rsync_compress:
            eprint(f"[dir] Using rsync with built-in compression (level {rsync_comp_level}) for directory transfer")
        else:
            eprint(f"[dir] Using rsync for remote directory transfer: {src_arg} -> {dest_root}/ on {user}@{host}")

    try:
        run_stream(cmd)
    finally:
        # Cleanup temporary files-from list, if any
        if files_from_path:
            try:
                os.remove(files_from_path)
            except OSError:
                pass


def strategy_stream_compress(args: argparse.Namespace, is_local: bool, user: Optional[str], host: Optional[str], dest_file: str, ssh_e: Optional[str], control_path: Optional[str], cipher: Optional[str]) -> None:
    """Stream compression: compress and transfer simultaneously (no pre-compression wait)"""
    compressor = args.compressor
    comp_info = get_compressor_cmd(compressor)
    if not comp_info:
        raise RuntimeError(f"Strategy 'stream' requires {compressor} installed (command: {compressor}).")
    
    comp_cmd, decomp_cmd, ext = comp_info
    
    if is_local:
        # Check if this is an NFS mount that we should stream via SSH
        nfs_info = get_nfs_info(dest_file)
        nfs_server = getattr(args, 'nfs_server', None)
        
        if nfs_info or nfs_server:
            # NFS mount detected or explicitly specified - use SSH streaming to NFS server
            if nfs_server:
                nfs_host = nfs_server
                eprint(f"[stream] NFS streaming mode: using specified NFS server {nfs_host}")
            elif nfs_info:
                nfs_host, _ = nfs_info
                eprint(f"[stream] NFS mount detected: streaming via NFS server {nfs_host}")
            else:
                # Fall back to regular compress
                eprint("[stream] Local transfer detected - using regular compress strategy instead")
                strategy_compress(args, is_local, user, host, dest_file, ssh_e, control_path, cipher)
                return
            
            # Override is_local and set up SSH for NFS streaming
            is_local = False
            if not user:
                user = args.user or os.getenv("USER") or ""
                if not user:
                    raise ValueError("Could not determine ssh user for NFS streaming; set --user or --nfs-user")
            
            # Set up SSH if not already done
            if not ssh_e or not control_path or not cipher:
                if which("ssh") is None:
                    raise RuntimeError("SSH required for NFS streaming")
                temp_base = args.temp_dir if hasattr(args, 'temp_dir') and args.temp_dir else tempfile.gettempdir()
                control_path = os.path.join(temp_base, f"sshcm-{os.getpid()}-%r@%h:%p")
                cipher = pick_ssh_cipher(user, nfs_host, args.connect_timeout, control_path)
                ssh_e = ssh_cmd_str(args.connect_timeout, cipher, control_path)
            
            host = nfs_host
            
            # Ensure remote directory exists
            dest_dir = str(Path(dest_file).parent)
            remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, dest_dir)
        else:
            # Regular local transfer - use compress strategy
            eprint("[stream] Local transfer detected - using regular compress strategy instead")
            strategy_compress(args, is_local, user, host, dest_file, ssh_e, control_path, cipher)
            return
    
    assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
    
    # Check if remote has the decompressor
    if compressor == "zstd":
        remote_cmd_check = "zstd"
    elif compressor in ("pigz", "gzip"):
        remote_cmd_check = "gunzip" if which("gunzip") else "gzip"
    else:
        remote_cmd_check = decomp_cmd
    
    if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, remote_cmd_check):
        raise RuntimeError(f"Strategy 'stream' requires {compressor} decompressor ({remote_cmd_check}) installed on TARGET as well.")
    
    src = Path(args.source).resolve()
    src_size = src.stat().st_size
    comp_level = args.compression_level
    
    eprint(f"[stream] Streaming compression and transfer: {src.name} ({human_bytes(src_size)}) with {compressor} level {comp_level}...")
    eprint(f"[stream] Compressing and transferring simultaneously (no pre-compression wait)...")
    
    transfer_start = time.time()
    
    # Build compression command (output to stdout, read from file)
    if compressor == "zstd":
        # zstd with parallel threads and stdout output
        threads = args.compression_threads if hasattr(args, 'compression_threads') and args.compression_threads > 0 else 0
        if threads == 0:
            try:
                import multiprocessing
                threads = multiprocessing.cpu_count()
            except:
                threads = 4
        comp_cmd_list = [comp_cmd, f"-{comp_level}", "-c", f"-T{threads}", str(src)]
    elif compressor == "pigz":
        threads = args.compression_threads if hasattr(args, 'compression_threads') and args.compression_threads > 0 else 0
        if threads == 0:
            try:
                import multiprocessing
                threads = multiprocessing.cpu_count()
            except:
                threads = 4
        # pigz can read from file and output to stdout
        comp_cmd_list = [comp_cmd, f"-{comp_level}", "-c", "-p", str(threads), str(src)]
    else:  # gzip
        comp_cmd_list = [comp_cmd, f"-{comp_level}", "-c", str(src)]
    
    # Build remote decompression command (optimized for speed)
    decomp_threads = get_decompression_threads(getattr(args, 'decompression_threads', None))
    remote_decomp_cmd = build_fast_decompression_cmd(compressor, decomp_cmd, decomp_threads, streaming=True)
    
    # Build SSH command for remote execution
    ssh_cmd = ssh_base_args(args.connect_timeout, cipher, control_path)
    dest_q = shlex.quote(dest_file)
    
    if args.keep_compressed:
        # Keep compressed on destination
        remote_cmd = f"cat > {dest_q}{ext}"
        eprint(f"[stream] Streaming compressed data to {dest_q}{ext}...")
    else:
        # Decompress on-the-fly on remote (COMPRESS + TRANSFER + DECOMPRESS all at once!)
        remote_cmd = f"{remote_decomp_cmd} > {dest_q}"
        eprint(f"[stream] Pipeline: COMPRESS → TRANSFER → DECOMPRESS (all simultaneously)")
        eprint(f"[stream] Using {decomp_threads} threads for decompression on destination")
    
    # Start compression process (reads from file, outputs to stdout)
    # Note: comp_cmd_list already includes the source file, so we don't add it again
    comp_proc = subprocess.Popen(
        comp_cmd_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Start SSH process (reads from compression stdout, writes to remote)
    ssh_proc = subprocess.Popen(
        ssh_cmd + [f"{user}@{host}", remote_cmd],
        stdin=comp_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Close compression stdout in parent (SSH process owns it now)
    comp_proc.stdout.close()
    
    # Monitor progress by reading from compression stderr (if available) and tracking time
    # For progress display, we'll show periodic updates based on elapsed time
    last_progress_time = transfer_start
    progress_interval = 2.0  # Show progress every 2 seconds
    
    # Read compression stderr in background (for error reporting)
    comp_stderr_chunks = []
    def read_comp_stderr():
        if comp_proc.stderr:
            try:
                while True:
                    chunk = comp_proc.stderr.read(1024)
                    if not chunk:
                        break
                    comp_stderr_chunks.append(chunk)
            except Exception:
                pass
    
    import threading
    stderr_thread = threading.Thread(target=read_comp_stderr, daemon=True)
    stderr_thread.start()
    
    # Monitor SSH process and show progress
    while ssh_proc.poll() is None:
        elapsed = time.time() - transfer_start
        if elapsed - (last_progress_time - transfer_start) >= progress_interval:
            # Estimate progress based on time (rough estimate)
            # We can't know exact bytes transferred through pipe, so estimate based on elapsed time
            estimated_speed = src_size / elapsed if elapsed > 0 else 0
            estimated_progress = min(100, (elapsed / (src_size / estimated_speed * 0.1)) * 100) if estimated_speed > 0 else 0
            eprint(f"[stream] Transferring... {elapsed:.1f}s elapsed (~{estimated_progress:.0f}% estimated, ~{human_bytes(estimated_speed)}/s)", end='\r')
            last_progress_time = time.time()
        time.sleep(0.5)
    
    # Wait for both processes
    ssh_stdout, ssh_stderr = ssh_proc.communicate()
    comp_retcode = comp_proc.wait()
    ssh_retcode = ssh_proc.returncode
    
    # Join stderr thread
    stderr_thread.join(timeout=1.0)
    comp_stderr = b''.join(comp_stderr_chunks)
    
    if comp_retcode != 0:
        error_msg = comp_stderr.decode('utf-8', errors='ignore') if comp_stderr else "unknown error"
        raise RuntimeError(f"Compression failed (exit={comp_retcode}): {error_msg}")
    
    if ssh_retcode != 0:
        error_msg = ssh_stderr.decode('utf-8', errors='ignore') if ssh_stderr else "unknown error"
        raise RuntimeError(f"Transfer failed (exit={ssh_retcode}): {error_msg}")
    
    transfer_elapsed = time.time() - transfer_start
    transfer_speed = src_size / transfer_elapsed if transfer_elapsed > 0 else 0
    eprint()  # New line after progress
    eprint(f"[stream] Transfer completed in {transfer_elapsed:.1f}s ({human_bytes(transfer_speed)}/s)")
    
    if args.keep_compressed:
        eprint(f"[stream] Compressed file saved: {dest_file}{ext}")
        eprint(f"[stream] To decompress manually: {decomp_cmd} -d {dest_file}{ext}")
    else:
        eprint(f"[stream] File decompressed on destination: {dest_file}")


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
    src_size = src.stat().st_size
    eprint(f"[compress] Compressing {src.name} ({human_bytes(src_size)}) with {compressor} level {comp_level}...")
    comp_start = time.time()
    
    if compressor == "zstd":
        if HAS_ZSTD_LIB:
            # Use Python zstandard library for local compression (no external zstd needed)
            threads = getattr(args, "compression_threads", 0) or 0
            if threads <= 0:
                try:
                    import multiprocessing
                    threads = multiprocessing.cpu_count()
                except Exception:
                    threads = 4
            eprint(f"[compress] Using Python zstandard library with {threads} threads...")
            compress_file_python_zstd(src, comp_local, comp_level, threads)
        else:
            # Fallback to CLI zstd
            cmd = [comp_cmd, f"-{comp_level}", "-T0", "--no-progress", "-o", str(comp_local), str(src)]
            run_stream(cmd)
    elif compressor == "pigz":
        threads = args.compression_threads if hasattr(args, 'compression_threads') and args.compression_threads > 0 else 0
        # Auto-detect threads if not specified (use CPU count)
        if threads == 0:
            try:
                import multiprocessing
                threads = multiprocessing.cpu_count()
            except:
                threads = 4  # fallback
        
        # pigz: when using -c, it reads from stdin, so we need to redirect input
        # Build command: pigz -9 [-p N] -c
        cmd = [comp_cmd, f"-{comp_level}", "-p", str(threads), "-c"]
        eprint(f"[compress] Using {threads} threads for pigz compression...")
        
        # pigz -c reads from stdin and outputs to stdout
        with open(src, "rb") as infile, open(comp_local, "wb") as outfile:
            result = subprocess.run(cmd, stdin=infile, stdout=outfile, stderr=subprocess.PIPE, check=False)
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else "unknown error"
                raise RuntimeError(f"pigz compression failed (exit={result.returncode}): {error_msg}")
            # Verify compression actually happened
            if comp_local.exists() and comp_local.stat().st_size == 0:
                raise RuntimeError("pigz produced empty output - compression may have failed")
    elif compressor == "gzip":
        cmd = [comp_cmd, f"-{comp_level}", "-c", str(src)]
        # gzip -c outputs to stdout
        with open(comp_local, "wb") as out:
            subprocess.run(cmd, stdout=out, check=True, stderr=subprocess.PIPE)
    
    comp_elapsed = time.time() - comp_start
    comp_size = comp_local.stat().st_size
    comp_ratio = comp_size / src_size if src_size > 0 else 0
    comp_speed = src_size / comp_elapsed if comp_elapsed > 0 else 0
    eprint(f"[compress] Compressed: {human_bytes(src_size)} -> {human_bytes(comp_size)} ({comp_ratio:.1%}) in {comp_elapsed:.1f}s ({human_bytes(comp_speed)}/s)")
    
    # Warn if compression didn't help much
    if comp_ratio >= 0.95:
        eprint(f"[compress] WARNING: Compression ratio is {comp_ratio:.1%} - file may already be compressed or incompressible")
        eprint(f"[compress] Suggestion: Use --strategy direct for better performance on incompressible files")
    elif comp_ratio > 1.0:
        eprint(f"[compress] WARNING: Compressed file is LARGER than original ({comp_ratio:.1%})!")
        eprint(f"[compress] This file does not compress well. Consider using --strategy direct instead")

    comp_size = comp_local.stat().st_size
    eprint(f"[compress] Transferring compressed file ({human_bytes(comp_size)})...")
    transfer_start = time.time()
    if is_local:
        # For local, use fast copy (faster than rsync)
        dest_path = Path(comp_dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(comp_local), str(dest_path))
        transfer_elapsed = time.time() - transfer_start
        transfer_speed = comp_size / transfer_elapsed if transfer_elapsed > 0 else 0
        eprint(f"[compress] Transfer completed in {transfer_elapsed:.1f}s ({human_bytes(transfer_speed)}/s)")
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
        transfer_elapsed = time.time() - transfer_start
        transfer_speed = comp_size / transfer_elapsed if transfer_elapsed > 0 else 0
        eprint(f"[compress] Transfer completed in {transfer_elapsed:.1f}s ({human_bytes(transfer_speed)}/s)")

    # Decompress on destination unless --keep-compressed is set
    if args.keep_compressed:
        eprint(f"[compress] Keeping compressed file on destination: {comp_dest}")
        eprint(f"[compress] To decompress manually: gunzip {comp_dest} (or zstd -d {comp_dest})")
    else:
        eprint(f"[compress] Decompressing on destination (optimized)...")
        decomp_threads = get_decompression_threads(getattr(args, 'decompression_threads', None))
        eprint(f"[compress] Using {decomp_threads} threads for decompression")
        
        if is_local:
            # Local decompression (optimized)
            if compressor == "zstd":
                # Try unzstd first (often faster), then zstd -d
                if which("unzstd"):
                    cmd = ["unzstd", f"-T{decomp_threads}", "--fast", "-f", "--rm", str(comp_dest)]
                else:
                    cmd = [decomp_cmd, "-d", f"-T{decomp_threads}", "--fast", "-f", str(comp_dest)]
                run_checked(cmd)
                if not which("unzstd"):
                    try:
                        Path(comp_dest).unlink()
                    except FileNotFoundError:
                        pass
            elif compressor in ("pigz", "gzip"):
                # Try unpigz first (parallel), then pigz -d, then gunzip
                if which("unpigz"):
                    run_checked(["unpigz", f"-p{decomp_threads}", "-f", str(comp_dest)])
                elif which("pigz"):
                    run_checked(["pigz", "-d", f"-p{decomp_threads}", "-f", str(comp_dest)])
                else:
                    run_checked([decomp_cmd, "-f", str(comp_dest)])
        else:
            # Remote decompression (optimized)
            decomp_cmd_str = build_fast_decompression_cmd(compressor, decomp_cmd, decomp_threads, streaming=False)
            remote_cmd = f"""
set -euo pipefail
{decomp_cmd_str} {shlex.quote(comp_dest)}
"""
            run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", remote_cmd])

    if not args.keep_local_artifact:
        try:
            comp_local.unlink()
            eprint(f"[compress] Cleaned up local artifact: {comp_local}")
        except FileNotFoundError:
            pass


def split_file(src: Path, part_prefix: Path, chunk_size: str, parallel: int = 1) -> List[Path]:
    """
    Split file into chunks using parallel dd (much faster than sequential split).
    If dd is available and parallel > 1, uses parallel dd. Otherwise falls back to split.
    """
    src_size = src.stat().st_size
    if src_size == 0:
        raise RuntimeError("Source file is empty; nothing to split.")
    
    try:
        chunk_bytes = parse_size_to_bytes(chunk_size)
    except Exception as e:
        raise RuntimeError(f"Invalid chunk_size {chunk_size!r}: {e}")
    
    n_chunks = (src_size + chunk_bytes - 1) // chunk_bytes
    suffix_len = max(4, len(str(n_chunks - 1)))
    part_prefix.parent.mkdir(parents=True, exist_ok=True)
    
    # Use parallel dd if available and parallel > 1, otherwise use split
    use_parallel_dd = (which("dd") is not None and parallel > 1 and n_chunks > 1)
    
    if use_parallel_dd:
        eprint(f"[chunked] Splitting {src.name} into {n_chunks} chunks using parallel dd (workers={parallel})...")
        
        # Choose block size for dd
        bs_bytes = choose_block_size(chunk_bytes, max_bs=16 * 1024 * 1024)
        
        def split_one_chunk(idx: int) -> Path:
            offset_bytes = idx * chunk_bytes
            if offset_bytes >= src_size:
                return None
            remaining = src_size - offset_bytes
            this_size = min(chunk_bytes, remaining)
            
            out_name = f"{part_prefix.name}{idx:0{suffix_len}d}"
            out_path = part_prefix.parent / out_name
            
            # Calculate dd parameters
            skip_blocks = offset_bytes // bs_bytes
            count_blocks = (this_size + bs_bytes - 1) // bs_bytes
            
            # Use dd to read chunk directly from source file
            dd_cmd = [
                "dd",
                f"if={str(src)}",
                f"of={str(out_path)}",
                f"bs={bs_bytes}",
                f"skip={skip_blocks}",
                f"count={count_blocks}",
                "iflag=fullblock",
                "status=none",
            ]
            
            try:
                subprocess.run(dd_cmd, check=True, stderr=subprocess.PIPE)
                return out_path
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else "unknown error"
                raise RuntimeError(f"dd failed for chunk {idx}: {error_msg}")
        
        # Split chunks in parallel
        parts = []
        start = time.time()
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
            futs = {ex.submit(split_one_chunk, i): i for i in range(n_chunks)}
            for fut in as_completed(futs):
                idx = futs[fut]
                part = fut.result()
                if part is not None:
                    parts.append(part)
                if len(parts) % max(1, n_chunks // 10) == 0 or len(parts) == n_chunks:
                    elapsed = time.time() - start
                    eprint(f"[chunked] Split progress: {len(parts)}/{n_chunks} chunks ({elapsed:.1f}s)", end='\r')
        
        eprint()  # New line after progress
        parts = sorted(parts)
        eprint(f"[chunked] Created {len(parts)} parts in {time.time() - start:.1f}s (parallel dd)")
    else:
        # Fallback to sequential split
        if which("split") is None:
            raise RuntimeError("Strategy 'chunked' requires 'split' or 'dd' installed on SOURCE.")
        
        eprint(f"[chunked] Splitting {src.name} into {chunk_size} chunks (using split)...")
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
        eprint(f"[chunked] Created {len(parts)} parts (sequential split)")
    
    if not parts:
        raise RuntimeError("Split produced no parts (unexpected).")
    return parts


def compress_parts(parts: List[Path], compressor: str, level: int, parallel: int, keep_parts: bool, compression_threads: Optional[int] = None) -> List[Path]:
    comp_info = get_compressor_cmd(compressor)
    if not comp_info:
        raise RuntimeError(f"Chunk compression requires {compressor} installed on SOURCE.")
    
    comp_cmd, _, ext = comp_info
    out: list[Path] = []

    # Determine compression threads per job
    local_cpus = local_cpu_count()
    if compression_threads and compression_threads > 0:
        comp_threads = compression_threads
    else:
        # Auto-detect: use more threads per job when parallel is low, fewer when parallel is high
        # Leave headroom for I/O and other processes
        if parallel > 0:
            comp_threads = max(1, int((local_cpus * 0.80) // parallel))
        else:
            comp_threads = max(1, int(local_cpus * 0.80))
    
    eprint(f"[chunked] Compressing {len(parts)} parts with {compressor} level {level} (parallel={parallel}, threads/job={comp_threads})...")

    def do_one(p: Path) -> Path:
        comp_file = Path(str(p) + ext)
        
        if compressor == "zstd":
            if HAS_ZSTD_LIB:
                # Use Python zstandard library for per-chunk compression
                compress_file_python_zstd(p, comp_file, level, comp_threads)
            else:
                # Use CLI zstd
                run_checked([comp_cmd, f"-{level}", f"-T{comp_threads}", "--no-progress", "-o", str(comp_file), str(p)])
        elif compressor == "pigz":
            # pigz -c reads from stdin, so redirect input
            cmd = [comp_cmd, f"-{level}", "-p", str(comp_threads), "-c"]
            with open(p, "rb") as infile, open(comp_file, "wb") as outfile:
                subprocess.run(cmd, stdin=infile, stdout=outfile, check=True, stderr=subprocess.PIPE)
        elif compressor == "gzip":
            # gzip doesn't support multi-threading, so use single thread
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
    files: List[Path],
    is_local: bool,
    user: Optional[str],
    host: Optional[str],
    dest_dir: str,
    ssh_e: Optional[str],
    parallel: int,
    rsync_timeout: int,
    rsync_compress: bool = False,
    rsync_compress_level: int = 1,
) -> None:
    if is_local:
        # For local transfers, use fast parallel copy (faster than rsync)
        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)
        
        eprint(f"[chunked] Copying {len(files)} files in parallel (workers={parallel})...")
        
        def copy_one(p: Path) -> Tuple[Path, bool, Optional[str]]:
            """Returns (file_path, success, error_message)"""
            try:
                dest_file = dest_path / p.name
                import shutil
                shutil.copy2(str(p), str(dest_file))
                return (p, True, None)
            except Exception as e:
                return (p, False, str(e))
        
        # Run copies in parallel
        completed = 0
        failed = []
        total = len(files)
        total_size = sum(f.stat().st_size for f in files)
        transfer_start = time.time()
        eprint(f"[chunked] Starting parallel copy of {total} files ({human_bytes(total_size)}) with {parallel} workers...")
        
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
            futs = {ex.submit(copy_one, f): f for f in files}
            for fut in as_completed(futs):
                file_path, success, error = fut.result()
                completed += 1
                if not success:
                    failed.append((file_path, error))
                
                # Show progress with speed
                elapsed = time.time() - transfer_start
                if elapsed > 0:
                    transferred_so_far = sum(f.stat().st_size for f in files[:completed])
                    current_speed = transferred_so_far / elapsed
                    remaining = total - completed
                    if remaining > 0:
                        avg_file_size = total_size / total
                        eta = (remaining * avg_file_size) / current_speed if current_speed > 0 else 0
                        eprint(f"[chunked] Progress: {completed}/{total} files ({human_bytes(transferred_so_far)}/{human_bytes(total_size)}) - {human_bytes(current_speed)}/s - ETA: {eta:.0f}s")
                    else:
                        eprint(f"[chunked] Progress: {completed}/{total} files ({human_bytes(transferred_so_far)}/{human_bytes(total_size)}) - {human_bytes(current_speed)}/s")
                else:
                    if completed % max(1, total // 10) == 0 or completed == total:
                        eprint(f"[chunked] Progress: {completed}/{total} files transferred")
        
        transfer_elapsed = time.time() - transfer_start
        transfer_speed = total_size / transfer_elapsed if transfer_elapsed > 0 else 0
        
        if failed:
            eprint(f"[chunked] ERROR: Failed to copy {len(failed)}/{total} files:")
            for fpath, err in failed[:5]:
                eprint(f"  - {fpath.name}: {err}")
            if len(failed) > 5:
                eprint(f"  ... and {len(failed) - 5} more failures")
            raise RuntimeError(f"Failed to copy {len(failed)} files")
        
        eprint(f"[chunked] ✓ All {total} parts copied successfully in {transfer_elapsed:.1f}s ({human_bytes(transfer_speed)}/s)")
        return
        
    # Remote transfer path (original rsync code)
    dest_dir_str = f"{user}@{host}:{dest_dir.rstrip('/')}/"

    eprint(f"[chunked] Transferring {len(files)} files in parallel (workers={parallel})...")

    def send_one(p: Path) -> Tuple[Path, bool, Optional[str]]:
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
        # Add rsync compression if enabled (for uncompressed files only)
        if rsync_compress and not str(p).endswith(('.gz', '.zst', '.bz2', '.xz', '.zip')):
            # Only compress if file doesn't appear to be already compressed
            cmd.append("--compress")
            cmd.append(f"--compress-level={rsync_compress_level}")
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

    # Run transfers in parallel with better progress reporting
    completed = 0
    failed = []
    total = len(files)
    total_size = sum(f.stat().st_size for f in files)
    transfer_start = time.time()
    eprint(f"[chunked] Starting parallel transfer of {total} files ({human_bytes(total_size)}) with {parallel} workers...")
    
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = {ex.submit(send_one, f): f for f in files}
        for fut in as_completed(futs):
            file_path, success, error = fut.result()
            completed += 1
            if not success:
                failed.append((file_path, error))
            
            # Show progress with percentage and speed (similar to zstd_xfer_turbo.py)
            elapsed = time.time() - transfer_start
            if elapsed > 0:
                # Estimate transferred bytes (rough, based on completed files)
                transferred_so_far = sum(f.stat().st_size for f in files[:completed]) if completed <= len(files) else total_size
                current_speed = transferred_so_far / elapsed
                pct = min(100.0, (completed / total) * 100.0)
                eprint(f"[chunked] Progress: {pct:6.2f}%  {completed}/{total} files  {human_bytes(transferred_so_far)}/{human_bytes(total_size)}  avg={human_bytes(current_speed)}/s", end='\r')
            else:
                if completed % max(1, total // 10) == 0 or completed == total:
                    eprint(f"[chunked] Progress: {completed}/{total} files transferred")
    
    eprint()  # New line after progress

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
    parts = split_file(src, part_prefix, args.chunk_size, parallel=args.parallel)

    parts_to_send: List[Path] = parts
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
            
            # For zstd turbo mode (dd-based assembly), also check for dd and xargs
            if compressor == "zstd" and not args.keep_compressed:
                if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "dd"):
                    eprint(f"[chunked] WARNING: 'dd' not found on remote - turbo mode (dd-based assembly) will be disabled")
                if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "xargs"):
                    eprint(f"[chunked] WARNING: 'xargs' not found on remote - turbo mode (dd-based assembly) will be disabled")
        
        parts_to_send = compress_parts(parts, compressor, args.compression_level, args.parallel, keep_parts=args.keep_local_parts, compression_threads=getattr(args, 'compression_threads', None))

    # Determine staging directory: for NFS destinations, stage on local disk for faster assembly
    stage_base = (getattr(args, "remote_stage_base", "") or "").strip()
    if not stage_base:
        if is_local:
            # Check if destination is on NFS mount
            nfs_info = get_nfs_info(dest_dir)
            if nfs_info:
                # NFS mount detected - stage on local disk for faster concatenation
                stage_base = "/var/tmp"
                eprint(f"[chunked] NFS mount detected at destination - staging on {stage_base} for faster assembly")
            else:
                stage_base = dest_dir
        else:
            # Remote: detect filesystem type
            assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
            dest_fs = remote_fs_type(user, host, args.connect_timeout, cipher, control_path, dest_dir)
            if "nfs" in dest_fs.lower():
                stage_base = "/var/tmp"
                eprint(f"[chunked] Remote NFS detected - staging on {stage_base} for faster assembly")
            else:
                stage_base = dest_dir

    stage_dir = f"{stage_base.rstrip('/')}/._xfer_{src.name}_{int(time.time())}"
    if is_local:
        local_mkdir_p(stage_dir)
    else:
        assert user is not None and host is not None and cipher is not None, "user, host, and cipher must be set for remote transfers"
        remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, stage_dir)

    # Use rsync compression for chunked transfers if enabled (only for uncompressed files)
    use_rsync_compress = args.rsync_compress if hasattr(args, 'rsync_compress') and not args.compress_chunks else False
    rsync_comp_level = args.rsync_compress_level if hasattr(args, 'rsync_compress_level') else 1
    rsync_many_parallel(parts_to_send, is_local, user, host, stage_dir, ssh_e, args.parallel, args.rsync_timeout, use_rsync_compress, rsync_comp_level)

    # Reassemble file on destination
    stage_q = shlex.quote(stage_dir)
    dest_q = shlex.quote(dest_file)
    if args.compress_chunks:
        compressor = args.compressor
        _, decomp_cmd, ext = get_compressor_cmd(compressor) or (None, None, None)
        
        if args.keep_compressed:
            # Keep compressed chunks and concatenate them - USE SEQUENTIAL CAT (safer for compressed files)
            # Note: Parallel dd can corrupt compressed files due to race conditions
            eprint(f"[chunked] Keeping compressed chunks and concatenating to {dest_q}{ext}...")
            if compressor == "zstd":
                pattern = "part.*.zst"
            elif compressor in ("pigz", "gzip"):
                pattern = "part.*.gz"
            else:
                pattern = f"part.*{ext}"
            
            # Check if staging and destination are different (e.g., staged on /var/tmp, dest on NFS)
            final_dest = f"{dest_q}{ext}"
            final_dest_q = shlex.quote(final_dest)
            
            # Use sequential cat for compressed chunks (safer and fast enough)
            # Add verification command based on compressor type
            verify_cmd = ""
            if compressor == "zstd":
                verify_cmd = 'zstd -t "$first_chunk" >/dev/null 2>&1 || { echo "ERROR: First chunk is corrupted" >&2; exit 1; }'
            elif compressor in ("pigz", "gzip"):
                verify_cmd = 'gunzip -t "$first_chunk" >/dev/null 2>&1 || { echo "ERROR: First chunk is corrupted" >&2; exit 1; }'
            
            if stage_dir != dest_dir:
                assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
tmp="tmp_$$.zst"
files=($(ls -1 {pattern} | sort))
# Concatenate all compressed chunks sequentially (cat is safe and fast for compressed files)
cat "${{files[@]}}" > "$tmp"
# Verify the concatenated file is valid (test first frame)
if [ "${{#files[@]}}" -gt 0 ]; then
  first_chunk="${{files[0]}}"
  {verify_cmd if verify_cmd else "# No verification available"}
fi
rm -f "${{files[@]}}"
# Move final file to NFS destination
mkdir -p "$(dirname {final_dest_q})"
mv -f "$tmp" {final_dest_q}
cd /
rmdir {stage_q} || true
"""
            else:
                assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={final_dest_q}
tmp="${{dest}}.incomplete.$$"
files=($(ls -1 {pattern} | sort))
# Concatenate all compressed chunks sequentially (cat is safe and fast for compressed files)
cat "${{files[@]}}" > "$tmp"
# Verify the concatenated file is valid (test first frame)
if [ "${{#files[@]}}" -gt 0 ]; then
  first_chunk="${{files[0]}}"
  {verify_cmd if verify_cmd else "# No verification available"}
fi
rm -f "${{files[@]}}"
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
        else:
            # Decompress and reassemble - OPTIMIZED: use dd-based assembly for zstd (writes directly to final file offsets)
            eprint(f"[chunked] Reassembling and decompressing file on destination (optimized)...")
            decomp_threads = get_decompression_threads(getattr(args, 'decompression_threads', None))
            eprint(f"[chunked] Using {decomp_threads} threads per chunk for parallel decompression")
            
            if compressor == "zstd" and not is_local:
                # Check if remote has dd and xargs for turbo mode
                has_dd = remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "dd")
                has_xargs = remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "xargs")
                
                if has_dd and has_xargs:
                    # TURBO MODE: Use dd-based assembly for zstd (writes directly to final file offsets, no temp files)
                    # This is MUCH faster for huge files - avoids creating temp decompressed chunks
                    eprint(f"[chunked] Using TURBO mode: dd-based assembly (writes directly to final file, no temp decompressed chunks)")
                    
                    # Parse chunk size to bytes for dd block size calculation
                    chunk_size_bytes = parse_size_to_bytes(args.chunk_size) if hasattr(args, 'chunk_size') else 20 * 1024**3
                    src_size = src.stat().st_size
                    
                    # Choose dd block size that divides chunk size (prefer 4MiB, fallback to 1MiB)
                    bs = 4 * 1024 * 1024  # 4MiB
                    if chunk_size_bytes % bs != 0:
                        bs = 1 * 1024 * 1024  # 1MiB
                    if chunk_size_bytes % bs != 0:
                        bs = 1024 * 1024  # Ensure it works
                    
                    chunk_blocks = chunk_size_bytes // bs
                    remote_jobs = max(1, min(args.parallel, 8))  # Cap at 8 parallel jobs
                    
                    assemble_cmd = f"""
set -euo pipefail
stage={stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
size={src_size}
bs={bs}
chunk_blocks={chunk_blocks}
jobs={remote_jobs}
threads={decomp_threads}

mkdir -p "$(dirname "$dest")"

# Preallocate final file for better write performance
(fallocate -l "$size" "$tmp" 2>/dev/null) || (truncate -s "$size" "$tmp")

cd "$stage"

# Ensure there are parts
ls -1 part.*.zst >/dev/null 2>&1

export bs chunk_blocks tmp threads

# Decompress each part and write into correct offset using dd seek
# File names are: part.0000.zst, part.0001.zst, ...
ls -1 part.*.zst | sort | \\
  xargs -n 1 -P "$jobs" -I{{}} bash -lc '
    f="{{}}"
    idx=${{f#part.}}
    idx=${{idx%.zst}}
    # Interpret leading zeros as base-10
    off_blocks=$((10#$idx * chunk_blocks))
    zstd -d -c -T"$threads" --fast --no-progress "$f" | dd of="$tmp" bs="$bs" seek="$off_blocks" conv=notrunc status=none
  '

# Verify size
actual=$(stat -c %s "$tmp")
if [ "$actual" -ne "$size" ]; then
  echo "Size mismatch after assembly: expected=$size actual=$actual" >&2
  exit 24
fi

# Move into place
mv -f "$tmp" "$dest"

# Cleanup compressed parts and stage dir
rm -f part.*.zst
cd /
rmdir "$stage" 2>/dev/null || true
"""
                else:
                    # Fall back to standard mode if dd/xargs not available
                    eprint(f"[chunked] Turbo mode unavailable (missing dd/xargs) - using standard assembly")
                    decomp_cmd_str = f"zstd -d -c -T{decomp_threads} --fast"
                    pattern = "part.*.zst"
                    
                    assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
files=($(ls -1 {pattern} | sort))
# Decompress all chunks in parallel to temp files
for f in "${{files[@]}}"; do
  {decomp_cmd_str} "$f" > "$f.decomp" &
done
wait  # Wait for all decompressions to finish
# Concatenate all decompressed chunks at once (much faster than sequential append)
decomp_files=()
for f in "${{files[@]}}"; do
  decomp_files+=("$f.decomp")
done
cat "${{decomp_files[@]}}" > "$tmp"
# Cleanup
rm -f "${{files[@]}}" "${{decomp_files[@]}}"
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
            else:
                # Standard mode: decompress in parallel, then concatenate
                if compressor == "zstd":
                    decomp_cmd_str = f"zstd -d -c -T{decomp_threads} --fast"
                    pattern = "part.*.zst"
                elif compressor in ("pigz", "gzip"):
                    decomp_cmd_str = f"pigz -d -c -p {decomp_threads} 2>/dev/null || gunzip -c || gzip -d -c"
                    pattern = "part.*.gz"
                else:
                    decomp_cmd_str = f"{decomp_cmd} -d -c"
                    pattern = f"part.*{ext}"
                
                assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
files=($(ls -1 {pattern} | sort))
# Decompress all chunks in parallel to temp files
for f in "${{files[@]}}"; do
  {decomp_cmd_str} "$f" > "$f.decomp" &
done
wait  # Wait for all decompressions to finish
# Concatenate all decompressed chunks at once (much faster than sequential append)
decomp_files=()
for f in "${{files[@]}}"; do
  decomp_files+=("$f.decomp")
done
cat "${{decomp_files[@]}}" > "$tmp"
# Cleanup
rm -f "${{files[@]}}" "${{decomp_files[@]}}"
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
    else:
        # Uncompressed chunks: use parallel dd-based concatenation if possible
        can_parallel = False
        if not is_local:
            has_dd = remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "dd")
            has_xargs = remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "xargs")
            can_parallel = has_dd and has_xargs
        else:
            can_parallel = which("dd") is not None and which("xargs") is not None
        
        assemble_parallel = max(1, min(args.parallel, 8))  # Cap at 8 parallel jobs
        
        if can_parallel:
            # PARALLEL MODE: Use dd seek to write chunks in parallel (with job limit)
            eprint(f"[chunked] Using parallel dd-based concatenation for uncompressed chunks ({assemble_parallel} workers)")
            bs = 4 * 1024 * 1024  # 4MiB block size
            
            assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
files=($(ls -1 part.* | sort))
# Calculate total size and preallocate
total_size=0
for f in "${{files[@]}}"; do
  total_size=$((total_size + $(stat -c %s "$f")))
done
# Preallocate output file
(fallocate -l "$total_size" "$tmp" 2>/dev/null) || (truncate -s "$total_size" "$tmp")
# Write chunks in parallel using dd seek (limit parallel jobs)
offset=0
pids=()
for f in "${{files[@]}}"; do
  size=$(stat -c %s "$f")
  seek_blocks=$((offset / {bs}))
  count_blocks=$((size / {bs} + 1))
  dd if="$f" of="$tmp" bs={bs} seek=$seek_blocks count=$count_blocks conv=notrunc status=none &
  pids+=($!)
  offset=$((offset + size))
  # Limit parallel jobs
  if [ "${{#pids[@]}}" -ge {assemble_parallel} ]; then
    wait "${{pids[0]}}"
    pids=("${{pids[@]:1}}")
  fi
done
# Wait for remaining jobs
for pid in "${{pids[@]}}"; do
  wait "$pid"
done
mv -f "$tmp" "$dest"
rm -f "${{files[@]}}"
cd /
rmdir {stage_q} || true
"""
        else:
            # FALLBACK: Sequential cat (if dd/xargs not available)
            eprint(f"[chunked] Parallel concatenation unavailable (missing dd/xargs) - using sequential cat")
            assemble_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
files=($(ls -1 part.* | sort))
# Concatenate all chunks at once (much faster than sequential append)
cat "${{files[@]}}" > "$tmp"
rm -f "${{files[@]}}"
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


def strategy_turbo(args: argparse.Namespace, is_local: bool, user: Optional[str], host: Optional[str],
                  dest_file: str, dest_dir: str, ssh_e: Optional[str],
                  control_path: Optional[str], cipher: Optional[str]) -> None:
    """
    TURBO (zstd): chunked + parallel compress+transfer + parallel remote assemble.

    Key design goals:
      - No uncompressed split files on disk (reads source by offset via dd)
      - Multiple independent SSH TCP connections (disable ControlMaster mux for parallel data)
      - Parallel remote reassembly WITHOUT writing decompressed temp chunks (scatter write into preallocated file)
    """
    if args.compressor != "zstd":
        raise RuntimeError("Strategy 'turbo' is zstd-only. Use --compressor zstd.")
    if which("zstd") is None:
        raise RuntimeError("Strategy 'turbo' requires zstd installed on SOURCE.")
    if which("dd") is None:
        raise RuntimeError("Strategy 'turbo' requires dd on SOURCE.")
    if which("rsync") is None:
        raise RuntimeError("Strategy 'turbo' requires rsync on SOURCE.")

    if is_local:
        raise RuntimeError("Strategy 'turbo' is intended for remote targets (user@host:/path).")

    assert user is not None and host is not None and cipher is not None and ssh_e is not None, "remote fields not set"

    # Check remote dependencies
    if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "zstd"):
        raise RuntimeError("Strategy 'turbo' requires zstd installed on TARGET as well.")
    if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "dd"):
        raise RuntimeError("Strategy 'turbo' requires dd installed on TARGET as well.")

    src = Path(args.source).resolve()
    src_size = src.stat().st_size
    if src_size == 0:
        raise RuntimeError("Source file is empty; nothing to transfer.")

    # Chunk sizing
    try:
        chunk_bytes = parse_size_to_bytes(args.chunk_size)
    except Exception as e:
        raise RuntimeError(f"Invalid --chunk-size {args.chunk_size!r}: {e}")
    if chunk_bytes <= 0:
        raise RuntimeError("chunk size must be > 0")

    # Pick a dd block size that divides chunk_bytes (important for seek math)
    bs_bytes = choose_block_size(chunk_bytes, max_bs=16 * 1024 * 1024)

    if chunk_bytes % bs_bytes != 0:
        # This should not happen with choose_block_size, but keep it defensive
        raise RuntimeError(f"Internal error: bs_bytes={bs_bytes} does not divide chunk_bytes={chunk_bytes}")

    n_chunks = (src_size + chunk_bytes - 1) // chunk_bytes
    suffix_len = max(4, len(str(n_chunks - 1)))

    parallel = max(1, int(args.parallel))

    # Disable SSH multiplexing for data channels (multiple rsync in parallel should be multiple TCP conns)
    ssh_e_xfer = ssh_e + " -o ControlMaster=no -o ControlPersist=no -o ControlPath=none"

    # Threads per zstd job (source side)
    local_cpus = local_cpu_count()
    if getattr(args, "compression_threads", 0) and args.compression_threads > 0:
        comp_threads = int(args.compression_threads)
    else:
        # Leave headroom for SSH encryption + kernel IO
        comp_threads = max(1, int((local_cpus * 0.80) // parallel))

    # Threads per zstd job (remote side)
    remote_cpus = remote_cpu(user, host, args.connect_timeout, cipher, control_path)
    assemble_parallel = int(getattr(args, "assemble_parallel", 0) or 0)
    if assemble_parallel <= 0:
        assemble_parallel = parallel
    assemble_parallel = max(1, min(assemble_parallel, remote_cpus))

    if getattr(args, "decompression_threads", 0) and args.decompression_threads > 0:
        decomp_threads = int(args.decompression_threads)
    else:
        decomp_threads = max(1, int((remote_cpus * 0.80) // assemble_parallel))

    level = int(args.compression_level)

    # Remote staging directory: if destination filesystem is NFS, stage on /var/tmp (local disk) by default.
    dest_fs = remote_fs_type(user, host, args.connect_timeout, cipher, control_path, dest_dir)
    stage_base = (getattr(args, "remote_stage_base", "") or "").strip()
    if not stage_base:
        if "nfs" in dest_fs.lower():
            stage_base = "/var/tmp"
        else:
            stage_base = dest_dir

    stage_dir = f"{stage_base.rstrip('/')}/._xfer_{src.name}_{int(time.time())}"
    eprint(f"[turbo] src={src.name} size={human_bytes(src_size)} chunks={n_chunks} chunk={human_bytes(chunk_bytes)} bs={human_bytes(bs_bytes)}")
    eprint(f"[turbo] parallel={parallel} comp_threads/job={comp_threads} assemble_parallel={assemble_parallel} decomp_threads/job={decomp_threads}")
    eprint(f"[turbo] remote dest_fs={dest_fs} stage_dir={stage_dir}")

    remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, stage_dir)

    # Local workdir for transient compressed chunks
    if args.workdir:
        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        tmpdir = workdir / f".xfer_turbo_{src.name}_{int(time.time())}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        cleanup_tmpdir = getattr(args, "cleanup_workdir", False)
    else:
        temp_base = getattr(args, "temp_dir", None) or tempfile.gettempdir()
        tmpdir = Path(tempfile.mkdtemp(prefix=f"xfer_turbo_{src.name}_", dir=temp_base))
        cleanup_tmpdir = True

    dest_stage = f"{user}@{host}:{stage_dir.rstrip('/')}/"

    # Worker: compress a chunk by offset (dd) -> zstd file, then rsync it, then delete local chunk.
    def process_chunk(idx: int) -> None:
        offset_bytes = idx * chunk_bytes
        if offset_bytes >= src_size:
            return
        remaining = src_size - offset_bytes
        this_size = min(chunk_bytes, remaining)

        out_name = f"part.{idx:0{suffix_len}d}.zst"
        out_path = tmpdir / out_name

        # dd math in blocks
        skip_blocks = offset_bytes // bs_bytes
        # Count blocks: exact for all but last; ceil for last
        count_blocks = (this_size + bs_bytes - 1) // bs_bytes

        # dd -> zstd (stdin)
        dd_cmd = [
            "dd",
            f"if={str(src)}",
            f"bs={bs_bytes}",
            f"skip={skip_blocks}",
            f"count={count_blocks}",
            "iflag=fullblock",
            "status=none",
        ]
        z_cmd = [
            "zstd",
            f"-{level}",
            f"-T{comp_threads}",
            "--no-progress",
            "-o", str(out_path),
            "-",  # stdin
        ]

        dd_p = subprocess.Popen(dd_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert dd_p.stdout is not None
        z_p = subprocess.Popen(z_cmd, stdin=dd_p.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        dd_p.stdout.close()

        dd_err = dd_p.stderr.read() if dd_p.stderr else b""
        z_err = z_p.stderr.read() if z_p.stderr else b""

        dd_rc = dd_p.wait()
        z_rc = z_p.wait()

        if dd_rc != 0:
            raise RuntimeError(f"[turbo] dd failed for chunk {idx}: {dd_err.decode('utf-8', errors='ignore')}")
        if z_rc != 0:
            raise RuntimeError(f"[turbo] zstd failed for chunk {idx}: {z_err.decode('utf-8', errors='ignore')}")

        # Transfer compressed chunk
        rsync_cmd = [
            "rsync",
            "-t",
            "--whole-file",
            "--partial",
            "--inplace",
            "--protect-args",
            f"--timeout={args.rsync_timeout}",
            "-e", ssh_e_xfer,
            str(out_path),
            dest_stage,
        ]
        try:
            subprocess.run(rsync_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as e:
            msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else "unknown error"
            raise RuntimeError(f"[turbo] rsync failed for chunk {idx}: {msg}")

        # Cleanup local chunk artifact unless asked to keep
        if not getattr(args, "keep_local_artifact", False):
            try:
                out_path.unlink()
            except FileNotFoundError:
                pass

    eprint(f"[turbo] Compress+transfer pipeline starting...")
    start = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(process_chunk, i): i for i in range(n_chunks)}
        for fut in as_completed(futs):
            idx = futs[fut]
            fut.result()  # raise if any
            completed += 1
            if completed % max(1, n_chunks // 20) == 0 or completed == n_chunks:
                elapsed = time.time() - start
                eprint(f"[turbo] progress: {completed}/{n_chunks} chunks done ({elapsed:.1f}s)")

    pipe_elapsed = time.time() - start
    eprint(f"[turbo] ✓ All chunks transferred in {pipe_elapsed:.1f}s")

    # Assemble on destination.
    # If destination FS is NFS, prefer sequential append (large sequential writes) over random scatter.
    assemble_mode = "seek"
    if "nfs" in dest_fs.lower():
        assemble_mode = "append"

    stage_q = shlex.quote(stage_dir)
    dest_q = shlex.quote(dest_file)

    if args.keep_compressed:
        # Keep compressed: just concatenate all .zst chunks (sequential cat is safe)
        eprint(f"[turbo] Keeping compressed file (concatenating chunks to {dest_q}.zst)")
        remote_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}.zst
tmp="${{dest}}.incomplete.$$"
files=( $(ls -1 part.*.zst | sort) )
# Concatenate compressed chunks sequentially (cat is safe for compressed files)
cat "${{files[@]}}" > "$tmp"
# Verify first chunk is valid
if [ "${{#files[@]}}" -gt 0 ]; then
  first_chunk="${{files[0]}}"
  zstd -t "$first_chunk" >/dev/null 2>&1 || {{ echo "ERROR: First chunk is corrupted" >&2; exit 1; }}
fi
mv -f "$tmp" "$dest"
rm -f "${{files[@]}}"
cd /
rmdir {stage_q} 2>/dev/null || true
"""
    elif assemble_mode == "append":
        eprint(f"[turbo] Remote assemble mode=append (dest on NFS detected)")
        remote_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
: > "$tmp"
files=( $(ls -1 part.*.zst | sort) )
for f in "${{files[@]}}"; do
  zstd -d -c -T{decomp_threads} --fast "$f" >> "$tmp"
done
mv -f "$tmp" "$dest"
rm -f "${{files[@]}}"
cd /
rmdir {stage_q} 2>/dev/null || true
"""
    else:
        eprint(f"[turbo] Remote assemble mode=seek (parallel scatter write)")
        remote_cmd = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
chunk_bytes={chunk_bytes}
bs={bs_bytes}
parallel={assemble_parallel}
threads={decomp_threads}
total_size={src_size}

# Create/size output file
(fallocate -l "$total_size" "$tmp" 2>/dev/null) || (truncate -s "$total_size" "$tmp")

files=( $(ls -1 part.*.zst | sort) )
pids=()
fail=0

run_one() {{
  local f="$1"
  local base="${{f##*/}}"
  local num="${{base#part.}}"
  num="${{num%.zst}}"
  local idx=$((10#$num))
  local offset=$((idx * chunk_bytes))
  local seek=$((offset / bs))
  (
    set -euo pipefail
    zstd -d -c -T"$threads" --fast "$f" | dd of="$tmp" bs="$bs" seek="$seek" conv=notrunc status=none
  ) &
  echo $!
}}

for f in "${{files[@]}}"; do
  pid=$(run_one "$f")
  pids+=("$pid")
  if [ "${{#pids[@]}}" -ge "$parallel" ]; then
    first="${{pids[0]}}"
    if ! wait "$first"; then
      fail=1
      break
    fi
    pids=("${{pids[@]:1}}")
  fi
done

if [ "$fail" -eq 1 ]; then
  for pid in "${{pids[@]}}"; do
    kill "$pid" 2>/dev/null || true
  done
  exit 1
fi

for pid in "${{pids[@]}}"; do
  wait "$pid"
done

mv -f "$tmp" "$dest"
rm -f "${{files[@]}}"
cd /
rmdir {stage_q} 2>/dev/null || true
"""
    run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", remote_cmd])

    # Cleanup local tempdir
    if cleanup_tmpdir and not getattr(args, "keep_local_artifact", False):
        try:
            for child in tmpdir.glob("*"):
                child.unlink()
            tmpdir.rmdir()
        except Exception:
            pass


def sha256sum_local(path: Path) -> str:
    h = subprocess.run(["sha256sum", str(path)], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split()[0]
    return h


def sha256sum_remote(user: str, host: str, connect_timeout: int, cipher: Optional[str], control_path: Optional[str], remote_path: str) -> str:
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
    p.add_argument("--nfs-server", default=None, help="NFS server hostname/IP for NFS-to-NFS streaming (enables SSH streaming to NFS server even for local-looking paths)")
    p.add_argument("--strategy", choices=["auto", "direct", "compress", "chunked", "stream", "turbo"], default="auto", help="Transfer strategy (chunked=split+transfer, stream=compress+transfer simultaneously, turbo=zstd-only optimized chunked with dd-based assembly, use --compress-chunks for split+compress)")
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
    p.add_argument("--decompression-threads", type=int, default=0, help="Threads for decompression (0=auto, uses all CPU cores by default)")
    p.add_argument("--keep-local-artifact", action="store_true", help="Keep local compressed artifact for compress strategy")
    p.add_argument("--keep-compressed", action="store_true", help="Keep compressed file on destination (skip decompression)")
    p.add_argument("--chunk-size", default="20G", help="Chunk size for chunked strategy (e.g., 4G, 20G, 500M). Optimal: 5-20G for 10G links, 10-50G for 25G+, smaller for slower links")
    p.add_argument("--parallel", type=int, default=1, help="Parallel transfers for chunked/turbo strategy")
    p.add_argument("--assemble-parallel", type=int, default=0, help="TURBO/chunked: parallel jobs for destination-side reassembly (0=auto; default: same as --parallel)")
    p.add_argument("--remote-stage-base", default="", help="TURBO: remote base dir for staging chunk files (default: auto; uses /var/tmp when destination is NFS)")
    p.add_argument("--compress-chunks", action="store_true", help="In chunked mode, compress each chunk before transfer")
    p.add_argument("--keep-local-parts", action="store_true", help="Keep uncompressed local parts after compressing chunks")
    p.add_argument("--cleanup-local-parts", action="store_true", help="Delete local parts after successful chunked transfer")
    p.add_argument("--zstd-level", type=int, default=3, help="[DEPRECATED] Use --compression-level instead. zstd compression level (1=fast, 3=default)")
    p.add_argument("--auto-sample-mib", type=int, default=256, help="Auto mode: sample size (MiB) to estimate compressibility")
    p.add_argument("--auto-threshold", type=float, default=0.85, help="Auto mode: choose compress if compression(out/in) <= threshold")
    p.add_argument("--skip-estimate", action="store_true", help="Skip compression estimation in auto mode (use direct transfer)")
    p.add_argument("--estimate-timeout", type=int, default=30, help="Timeout in seconds for compression estimation (default: 30)")
    p.add_argument("--temp-dir", default=None, help="Temporary directory for SSH control sockets (default: system temp, respects TMPDIR env var)")
    p.add_argument("--rsync-compress", action="store_true", help="Use rsync's built-in compression (compresses on-the-fly during transfer, more efficient than pre-compression)")
    p.add_argument("--rsync-compress-level", type=int, default=1, help="rsync compression level (1=fast, 6=better ratio, default: 1)")
    p.add_argument(
        "--before-date",
        default=None,
        help="Directory mode ONLY: only transfer files whose modification time is BEFORE this date (YYYY-MM-DD).",
    )
    p.add_argument(
        "--after-date",
        default=None,
        help="Directory mode ONLY: only transfer files whose modification time is AFTER this date (YYYY-MM-DD).",
    )
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
    if not src.exists() or (not src.is_file() and not src.is_dir()):
        eprint(f"ERROR: source path not found or unsupported type (must be file or directory): {src}")
        return 2

    if which("rsync") is None:
        eprint("ERROR: requires rsync installed.")
        return 2

    is_local, user, host, target_path = parse_target(args.target, args.user, nfs_server=getattr(args, 'nfs_server', None))
    dest_dir, dest_file = normalize_dest_path(target_path, src if src.is_file() else Path(src.name))

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
    if src.is_dir():
        # Directory mode: always use rsync-based directory transfer, ignore other strategies.
        if strategy not in ("direct", "auto"):
            eprint(f"[dir] WARNING: Source is a directory; ignoring --strategy={strategy!r} and using rsync directory transfer")
        if is_local:
            eprint(f"=== Directory transfer (rsync) | src={src}/ -> {target_path} (local) ===")
        else:
            eprint(f"=== Directory transfer (rsync) | src={src}/ -> {user}@{host}:{target_path} ===")
    else:
        if is_local:
            eprint(f"=== Strategy: {strategy} | src={src} -> {dest_file} (local) ===")
        else:
            eprint(f"=== Strategy: {strategy} | src={src} -> {user}@{host}:{dest_file} ===")

    try:
        if src.is_dir():
            # Directory tree transfer
            strategy_dir_rsync(args, is_local, user, host, target_path, ssh_e)
            if args.verify_sha256:
                eprint("[dir] NOTE: --verify-sha256 is not implemented for directory transfers; skipping integrity check")
        else:
            # Single-file transfer strategies
            if strategy == "direct":
                strategy_direct(args, is_local, user, host, dest_file, ssh_e)
            elif strategy == "compress":
                strategy_compress(args, is_local, user, host, dest_file, ssh_e, control_path, cipher)
            elif strategy == "stream":
                strategy_stream_compress(args, is_local, user, host, dest_file, ssh_e, control_path, cipher)
            elif strategy == "chunked":
                strategy_chunked(args, is_local, user, host, dest_file, dest_dir, ssh_e, control_path, cipher)
            elif strategy == "turbo":
                strategy_turbo(args, is_local, user, host, dest_file, dest_dir, ssh_e, control_path, cipher)
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

