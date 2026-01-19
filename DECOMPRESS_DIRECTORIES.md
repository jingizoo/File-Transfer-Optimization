# How to Decompress Directories

This guide shows how to decompress directories that were compressed per-file (each file compressed individually with zstd).

## Method 1: CLI zstd (Fastest, if available)

### Basic Decompression (Sequential)
```bash
# Navigate to the compressed directory
cd /path/to/compressed/directory

# Decompress all .zst files (sequential, removes .zst after decompression)
find . -type f -name "*.zst" -exec zstd -d --rm {} \;
```

### Parallel Decompression (Recommended for large directories)
```bash
# Navigate to the compressed directory
cd /path/to/compressed/directory

# Decompress all .zst files in parallel (8 workers, removes .zst after decompression)
find . -type f -name "*.zst" -print0 | xargs -0 -P 8 -I{} zstd -T0 -d --rm "{}"
```

### Parallel with Progress (shows which files are being decompressed)
```bash
cd /path/to/compressed/directory

# Decompress with progress output
find . -type f -name "*.zst" -print0 | xargs -0 -P 8 -I{} sh -c 'echo "Decompressing: {}" && zstd -T0 -d --rm "{}"'
```

### Keep .zst files (don't remove after decompression)
```bash
cd /path/to/compressed/directory

# Decompress but keep .zst files
find . -type f -name "*.zst" -print0 | xargs -0 -P 8 -I{} zstd -T0 -d "{}"
```

## Method 2: Python zstandard (No sudo required)

If you don't have CLI `zstd` installed, you can use Python-based decompression.

### Install Python zstandard (if not already installed)
```bash
pip3 install --user zstandard
```

### Python Script for Directory Decompression

Create a script `decompress_dir.py`:

```python
#!/usr/bin/env python3
"""
Decompress all .zst files in a directory tree using Python zstandard library.
Usage: python3 decompress_dir.py /path/to/directory [--keep-zst] [--parallel N]
"""
import sys
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import zstandard as zstd
except ImportError:
    print("ERROR: zstandard library not installed. Install with: pip3 install --user zstandard")
    sys.exit(1)

def decompress_file(zst_path: Path, keep_zst: bool = False) -> tuple[Path, bool, str]:
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
```

### Usage of Python Script

```bash
# Make script executable
chmod +x decompress_dir.py

# Decompress directory (removes .zst files)
python3 decompress_dir.py /path/to/compressed/directory

# Decompress with 16 parallel workers
python3 decompress_dir.py /path/to/compressed/directory --parallel 16

# Decompress but keep .zst files
python3 decompress_dir.py /path/to/compressed/directory --keep-zst
```

## Method 3: One-liner Python (Quick)

If you just need a quick one-liner without creating a script:

```bash
# Navigate to directory
cd /path/to/compressed/directory

# One-liner: decompress all .zst files (8 parallel workers)
python3 -c "
import zstandard as zstd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys

def decompress(f):
    try:
        dctx = zstd.ZstdDecompressor()
        out = f.with_suffix('')
        with open(f, 'rb') as i, open(out, 'wb') as o:
            dctx.copy_stream(i, o)
        f.unlink()
        return True
    except: return False

files = list(Path('.').rglob('*.zst'))
with ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(decompress, files))
print(f'Decompressed {len(files)} files')
"
```

## Method 4: Remote Decompression (via SSH)

If the compressed directory is on a remote server:

### Using CLI zstd (if available on remote)
```bash
# SSH to remote and decompress
ssh user@remote-host "cd /path/to/compressed/directory && find . -type f -name '*.zst' -print0 | xargs -0 -P 8 -I{} zstd -T0 -d --rm '{}'"
```

### Using Python zstandard (if CLI zstd not available)
```bash
# Copy the decompress_dir.py script to remote, then run it
scp decompress_dir.py user@remote-host:/tmp/
ssh user@remote-host "python3 /tmp/decompress_dir.py /path/to/compressed/directory --parallel 8"
```

## Verification After Decompression

### Check that all .zst files are gone (if you removed them)
```bash
cd /path/to/directory
find . -name "*.zst" | wc -l
# Should output: 0
```

### Verify decompressed files are valid
```bash
# For text files, check a few samples
head -n 5 /path/to/directory/some_file.txt

# For binary files, check file sizes match expected
ls -lh /path/to/directory/
```

## Examples

### Example 1: Local directory decompression (CLI)
```bash
# Directory structure:
# /data/backup/
#   ├── file1.txt.zst
#   ├── file2.txt.zst
#   └── subdir/
#       └── file3.txt.zst

cd /data/backup
find . -type f -name "*.zst" -print0 | xargs -0 -P 8 -I{} zstd -T0 -d --rm "{}"

# Result:
# /data/backup/
#   ├── file1.txt
#   ├── file2.txt
#   └── subdir/
#       └── file3.txt
```

### Example 2: Remote directory decompression (Python)
```bash
# On remote server (via SSH)
ssh user@10.0.0.15 "cd /data/backup_zstd && python3 -c \"
import zstandard as zstd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

def decompress(f):
    dctx = zstd.ZstdDecompressor()
    out = f.with_suffix('')
    with open(f, 'rb') as i, open(out, 'wb') as o:
        dctx.copy_stream(i, o)
    f.unlink()

files = list(Path('.').rglob('*.zst'))
with ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(decompress, files))
print(f'Decompressed {len(files)} files')
\""
```

## Performance Tips

1. **Use parallel decompression** for directories with many files (8-16 workers is usually optimal)
2. **For very large directories**, consider decompressing in batches:
   ```bash
   # Decompress first 1000 files
   find . -name "*.zst" | head -1000 | xargs -P 8 -I{} zstd -T0 -d --rm "{}"
   ```
3. **Monitor disk space** - decompressed files will be larger than compressed
4. **Use `--rm` flag** (or remove .zst files) to save disk space after verification

## Troubleshooting

### Error: "zstd: command not found"
- Use Python-based decompression (Method 2 or 3)
- Or install zstd: `sudo apt-get install zstd` (if you have sudo)

### Error: "No module named 'zstandard'"
- Install Python zstandard: `pip3 install --user zstandard`

### Error: "Permission denied"
- Check file permissions: `ls -l file.zst`
- May need to run with appropriate permissions or use `sudo` (if available)

### Files are corrupted after decompression
- Verify compressed files are valid: `zstd -t file.zst` (if CLI available)
- Check disk space: `df -h`
- Try decompressing a single file manually to isolate the issue
