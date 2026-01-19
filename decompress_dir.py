#!/usr/bin/env python3
"""
Decompress all .zst files in a directory tree using Python zstandard library.
Usage: python3 decompress_dir.py /path/to/directory [--keep-zst] [--parallel N]
"""
import sys
import os
from pathlib import Path
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import zstandard as zstd
except ImportError:
    print("ERROR: zstandard library not installed. Install with: pip3 install --user zstandard")
    sys.exit(1)

def decompress_file(zst_path: Path, keep_zst: bool = False) -> Tuple[Path, bool, str]:
    """Decompress a single .zst file. Returns (path, success, error_msg)."""
    try:
        # Output path (remove .zst extension)
        out_path = zst_path.with_suffix('')
        
        # Decompress
        dctx = zstd.ZstdDecompressor()
        with open(zst_path, 'rb') as f_in, open(out_path, 'wb') as f_out:
            dctx.copy_stream(f_in, f_out)
        
        # Remove .zst file unless --keep-zst
        if not keep_zst:
            zst_path.unlink()
        
        return (zst_path, True, "")
    except Exception as e:
        return (zst_path, False, str(e))

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Decompress all .zst files in a directory tree")
    parser.add_argument("directory", type=Path, help="Directory containing .zst files")
    parser.add_argument("--keep-zst", action="store_true", help="Keep .zst files after decompression")
    parser.add_argument("--parallel", type=int, default=8, help="Number of parallel workers (default: 8)")
    args = parser.parse_args()
    
    dir_path = args.directory.resolve()
    if not dir_path.is_dir():
        print(f"ERROR: {dir_path} is not a directory")
        sys.exit(1)
    
    # Find all .zst files
    zst_files = list(dir_path.rglob("*.zst"))
    if not zst_files:
        print(f"No .zst files found in {dir_path}")
        return
    
    print(f"Found {len(zst_files)} .zst files")
    print(f"Decompressing with {args.parallel} parallel workers...")
    if args.keep_zst:
        print("(Keeping .zst files after decompression)")
    else:
        print("(Removing .zst files after decompression)")
    
    # Decompress in parallel
    completed = 0
    failed = []
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(decompress_file, f, args.keep_zst): f for f in zst_files}
        for fut in as_completed(futures):
            zst_path, success, error = fut.result()
            completed += 1
            if success:
                if completed % max(1, len(zst_files) // 10) == 0 or completed == len(zst_files):
                    print(f"Progress: {completed}/{len(zst_files)} files decompressed")
            else:
                failed.append((zst_path, error))
                print(f"ERROR: Failed to decompress {zst_path}: {error}")
    
    print(f"\n✓ Decompressed {completed - len(failed)}/{len(zst_files)} files")
    if failed:
        print(f"✗ Failed: {len(failed)} files")
        for path, err in failed[:5]:
            print(f"  - {path}: {err}")
        if len(failed) > 5:
            print(f"  ... and {len(failed) - 5} more failures")
        sys.exit(1)

if __name__ == "__main__":
    main()
