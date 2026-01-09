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


def parse_target(target: str, default_user: Optional[str]) -> Tuple[str, str, str]:
    """
    Parse target like:
      user@10.0.0.15:/data/path
      10.0.0.15:/data/path
    Returns (user, host, path).
    """
    m = TARGET_RE.match(target.strip())
    if not m:
        raise ValueError("Target must look like user@host:/abs/path or host:/abs/path")
    user = m.group("user") or (default_user or os.getenv("USER") or "")
    host = m.group("host")
    path = m.group("path")
    if not user:
        raise ValueError("Could not determine ssh user; pass target as user@host:/path or set --user")
    if not path.startswith("/"):
        raise ValueError("Target path must be an absolute path (start with /)")
    return user, host, path


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


def estimate_zstd_ratio(src: Path, level: int, sample_bytes: int) -> Optional[Tuple[float, int, int]]:
    """
    Return (ratio, in_bytes, out_bytes) for a sample.
    ratio = out/in (lower is better).
    Uses external `zstd` if present.
    """
    if which("zstd") is None:
        return None

    in_bytes = 0
    out_bytes = 0

    p = subprocess.Popen(
        ["zstd", f"-{level}", "-T0", "-c", "--no-progress"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert p.stdin is not None and p.stdout is not None

    try:
        with src.open("rb") as f:
            remaining = sample_bytes
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                p.stdin.write(chunk)
                in_bytes += len(chunk)
                remaining -= len(chunk)
        p.stdin.close()

        while True:
            chunk = p.stdout.read(1024 * 1024)
            if not chunk:
                break
            out_bytes += len(chunk)
        p.stdout.close()

        rc = p.wait()
        if rc != 0 or in_bytes == 0:
            return None
        ratio = out_bytes / in_bytes
        return ratio, in_bytes, out_bytes
    finally:
        try:
            if p.poll() is None:
                p.kill()
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
    ssh_e: str,
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
        "-e", ssh_e,
    ]
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
    Decide remote_dir and remote_file path.
    Heuristic:
      - if target_path ends with '/', treat as directory
      - else treat as file path
    Returns (remote_dir, remote_file)
    """
    if target_path.endswith("/"):
        remote_dir = target_path.rstrip("/")
        remote_file = f"{remote_dir}/{src_file.name}"
        return remote_dir, remote_file
    remote_file = target_path
    remote_dir = str(Path(target_path).parent)
    return remote_dir, remote_file


def strategy_direct(args: argparse.Namespace, user: str, host: str, remote_file: str, ssh_e: str) -> None:
    dest = f"{user}@{host}:{remote_file}"
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


def strategy_compress(args: argparse.Namespace, user: str, host: str, remote_file: str, ssh_e: str, control_path: Optional[str], cipher: str) -> None:
    if which("zstd") is None:
        raise RuntimeError("Strategy 'compress' requires zstd installed on SOURCE (command: zstd).")
    if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "zstd"):
        raise RuntimeError("Strategy 'compress' requires zstd installed on TARGET as well (command: zstd).")

    src = Path(args.source).resolve()
    workdir = Path(args.workdir).resolve() if args.workdir else src.parent
    workdir.mkdir(parents=True, exist_ok=True)

    zst_local = workdir / (src.name + ".zst")
    zst_remote = remote_file + ".zst"

    eprint(f"[compress] Compressing {src.name} with zstd level {args.zstd_level}...")
    run_stream(["zstd", f"-{args.zstd_level}", "-T0", "--no-progress", "-o", str(zst_local), str(src)])

    eprint(f"[compress] Transferring compressed file...")
    dest = f"{user}@{host}:{zst_remote}"
    cmd = build_rsync_cmd(
        str(zst_local),
        dest,
        ssh_e,
        append_only=False,
        whole_file=True,
        inplace=False,
        preallocate=args.preallocate,
        timeout=args.rsync_timeout,
    )
    run_stream(cmd)

    eprint(f"[compress] Decompressing on remote host...")
    remote_cmd = f"""
set -euo pipefail
if command -v unzstd >/dev/null 2>&1; then
  unzstd -T0 -f --rm {shlex.quote(zst_remote)}
else
  zstd -d -T0 -f {shlex.quote(zst_remote)}
  rm -f {shlex.quote(zst_remote)}
fi
"""
    run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", remote_cmd])

    if not args.keep_local_artifact:
        try:
            zst_local.unlink()
            eprint(f"[compress] Cleaned up local artifact: {zst_local}")
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


def compress_parts(parts: list[Path], level: int, parallel: int, keep_parts: bool) -> list[Path]:
    if which("zstd") is None:
        raise RuntimeError("Chunk compression requires zstd installed on SOURCE.")
    out: list[Path] = []

    eprint(f"[chunked] Compressing {len(parts)} parts with zstd level {level} (parallel={parallel})...")

    def do_one(p: Path) -> Path:
        zst = Path(str(p) + ".zst")
        run_checked(["zstd", f"-{level}", "-T1", "--no-progress", "-o", str(zst), str(p)])
        if not keep_parts:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        return zst

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = [ex.submit(do_one, p) for p in parts]
        for fut in as_completed(futs):
            out.append(fut.result())

    eprint(f"[chunked] Compressed all parts")
    return sorted(out)


def rsync_many_parallel(
    files: list[Path],
    user: str,
    host: str,
    remote_dir: str,
    ssh_e: str,
    parallel: int,
    rsync_timeout: int,
) -> None:
    dest_dir = f"{user}@{host}:{remote_dir.rstrip('/')}/"

    eprint(f"[chunked] Transferring {len(files)} files in parallel (workers={parallel})...")

    def send_one(p: Path) -> None:
        cmd = [
            "rsync",
            "-rtvh",
            "--partial",
            "--protect-args",
            f"--timeout={rsync_timeout}",
            "--whole-file",
            "-e", ssh_e,
            str(p),
            dest_dir,
        ]
        run_stream(cmd)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = [ex.submit(send_one, f) for f in files]
        for fut in as_completed(futs):
            fut.result()

    eprint(f"[chunked] All parts transferred")


def strategy_chunked(args: argparse.Namespace, user: str, host: str, remote_file: str, remote_dir: str, ssh_e: str, control_path: Optional[str], cipher: str) -> None:
    src = Path(args.source).resolve()
    if args.workdir:
        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        tmpdir = workdir / f".xfer_{src.name}_{int(time.time())}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        cleanup_tmpdir = args.cleanup_workdir
    else:
        tmpdir = Path(tempfile.mkdtemp(prefix=f"xfer_{src.name}_"))
        cleanup_tmpdir = True

    part_prefix = tmpdir / "part."
    parts = split_file(src, part_prefix, args.chunk_size)

    parts_to_send: list[Path] = parts
    if args.compress_chunks:
        if not remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "zstd"):
            raise RuntimeError("Chunk compression requires zstd installed on TARGET as well (command: zstd).")
        parts_to_send = compress_parts(parts, args.zstd_level, args.parallel, keep_parts=args.keep_local_parts)

    stage_dir = f"{remote_dir.rstrip('/')}/._xfer_{src.name}_{int(time.time())}"
    remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, stage_dir)

    rsync_many_parallel(parts_to_send, user, host, stage_dir, ssh_e, args.parallel, args.rsync_timeout)

    eprint(f"[chunked] Reassembling file on remote host...")
    stage_q = shlex.quote(stage_dir)
    dest_q = shlex.quote(remote_file)
    if args.compress_chunks:
        remote_assemble = f"""
set -euo pipefail
cd {stage_q}
dest={dest_q}
tmp="${{dest}}.incomplete.$$"
: > "$tmp"
for f in $(ls -1 part.*.zst | sort); do
  zstd -d -c "$f" >> "$tmp"
  rm -f "$f"
done
mv -f "$tmp" "$dest"
cd /
rmdir {stage_q} || true
"""
    else:
        remote_assemble = f"""
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
    run_checked(ssh_base_args(args.connect_timeout, cipher, control_path) + [f"{user}@{host}", remote_assemble])

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


def main() -> int:
    p = argparse.ArgumentParser(
        description="Highly-tuned Linux-to-Linux file transfer wrapper (rsync/ssh, optional zstd, optional chunk parallelism).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", type=Path, help="Source file path on this machine")
    p.add_argument("target", help="Target like user@10.0.0.15:/abs/path OR 10.0.0.15:/abs/path (absolute path required)")
    p.add_argument("--user", default=None, help="SSH user (if not provided in target)")
    p.add_argument("--strategy", choices=["auto", "direct", "compress", "chunked"], default="auto", help="Transfer strategy")
    p.add_argument("--append-only", action="store_true", help="Use rsync --append-verify (only if file only grows by appending)")
    p.add_argument("--whole-file", action="store_true", help="Use rsync --whole-file (fastest first transfer, weakest resume)")
    p.add_argument("--inplace", action="store_true", help="Use rsync --inplace (better resume semantics; can be riskier if interrupted)")
    p.add_argument("--preallocate", action="store_true", help="Use rsync --preallocate when possible")
    p.add_argument("--connect-timeout", type=int, default=10, help="SSH connect timeout (seconds)")
    p.add_argument("--rsync-timeout", type=int, default=0, help="rsync I/O timeout (0 = disabled)")
    p.add_argument("--workdir", default=None, help="Working directory for artifacts/parts (default: alongside source, or temp for chunked)")
    p.add_argument("--cleanup-workdir", action="store_true", help="If --workdir is used with chunked, remove temp subdir after success")
    p.add_argument("--keep-local-artifact", action="store_true", help="Keep local .zst artifact for compress strategy")
    p.add_argument("--chunk-size", default="20G", help="Chunk size for chunked strategy (e.g., 4G, 20G, 500M)")
    p.add_argument("--parallel", type=int, default=1, help="Parallel transfers for chunked strategy")
    p.add_argument("--compress-chunks", action="store_true", help="In chunked mode, zstd-compress each chunk before transfer")
    p.add_argument("--keep-local-parts", action="store_true", help="Keep uncompressed local parts after compressing chunks")
    p.add_argument("--cleanup-local-parts", action="store_true", help="Delete local parts after successful chunked transfer")
    p.add_argument("--zstd-level", type=int, default=3, help="zstd compression level (1=fast, 3=default)")
    p.add_argument("--auto-sample-mib", type=int, default=256, help="Auto mode: sample size (MiB) to estimate compressibility")
    p.add_argument("--auto-threshold", type=float, default=0.85, help="Auto mode: choose compress if zstd(out/in) <= threshold")
    p.add_argument("--verify-sha256", action="store_true", help="Compute sha256 on source+target after transfer (slow for huge files)")

    args = p.parse_args()

    src = args.source.resolve()
    if not src.exists() or not src.is_file():
        eprint(f"ERROR: source file not found: {src}")
        return 2

    if which("rsync") is None or which("ssh") is None:
        eprint("ERROR: requires rsync and ssh installed on SOURCE.")
        return 2

    user, host, target_path = parse_target(args.target, args.user)
    remote_dir, remote_file = normalize_dest_path(target_path, src)

    control_path = f"/tmp/sshcm-{os.getpid()}-%r@%h:%p"

    cipher = pick_ssh_cipher(user, host, args.connect_timeout, control_path)
    ssh_e = ssh_cmd_str(args.connect_timeout, cipher, control_path)

    remote_mkdir_p(user, host, args.connect_timeout, cipher, control_path, remote_dir)

    strategy = args.strategy
    if strategy == "auto":
        # Auto rule of thumb:
        #   1) If both ends have zstd and the file looks compressible -> compress (fastest over constrained links)
        #   2) Else -> direct rsync
        # Chunked/parallel is powerful but operationally heavier, so it's opt-in via --strategy chunked.
        if args.append_only:
            strategy = "direct"
        else:
            if which("zstd") and remote_has_cmd(user, host, args.connect_timeout, cipher, control_path, "zstd"):
                sample_bytes = args.auto_sample_mib * 1024**2
                est = estimate_zstd_ratio(src, args.zstd_level, sample_bytes)
                if est:
                    ratio, in_b, out_b = est
                    eprint(f"[auto] zstd sample: in={human_bytes(in_b)} out={human_bytes(out_b)} ratio={ratio:.3f}")
                    if ratio <= args.auto_threshold:
                        strategy = "compress"
                    else:
                        strategy = "direct"
                else:
                    strategy = "direct"
            else:
                strategy = "direct"

    start = time.time()
    eprint(f"=== Strategy: {strategy} | src={src} -> {user}@{host}:{remote_file} ===")

    try:
        if strategy == "direct":
            strategy_direct(args, user, host, remote_file, ssh_e)
        elif strategy == "compress":
            strategy_compress(args, user, host, remote_file, ssh_e, control_path, cipher)
        elif strategy == "chunked":
            strategy_chunked(args, user, host, remote_file, remote_dir, ssh_e, control_path, cipher)
        else:
            raise RuntimeError(f"Unknown strategy: {strategy}")

        if args.verify_sha256:
            eprint("=== Verifying sha256 (this will read the full file on both ends) ===")
            local_h = sha256sum_local(src)
            remote_h = sha256sum_remote(user, host, args.connect_timeout, cipher, control_path, remote_file)
            eprint(f"local sha256:  {local_h}")
            eprint(f"remote sha256: {remote_h}")
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

