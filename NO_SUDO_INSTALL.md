# Installation Without Sudo Access

## Good News! 🎉

**Compression is already Python-based!** You don't need to install `zstd`, `pigz`, or `gzip` system packages.

## What You Need

### 1. Python Package (No Sudo Required)

```bash
# Install Python zstandard library (this is all you need for compression!)
pip3 install --user zstandard

# OR if you have a virtual environment:
pip3 install zstandard
```

**That's it for compression!** The code will automatically use Python's `zstandard` library instead of CLI tools.

### 2. System Tools (Usually Pre-Installed)

**Check if you already have these:**
```bash
# Check rsync (required for transfers)
which rsync
rsync --version

# Check ssh (required for remote transfers only)
which ssh
ssh -V
```

**If you already have `rsync` and `ssh`, you're all set!** These are usually pre-installed on Linux systems.

### 3. If rsync/ssh Are Missing

**Option A: Ask your admin to install them**
```bash
# Show this to your system administrator:
# "Please install: rsync openssh-client"
# They can run: sudo apt-get install rsync openssh-client
```

**Option B: Use local transfers only** (if `rsync` is missing)
- The code uses Python's `shutil.copy2` for local transfers
- No `rsync` needed for same-server transfers!

**Option C: Check if they're in a non-standard location**
```bash
# Sometimes tools are in /usr/local/bin or user directories
find ~ -name rsync 2>/dev/null
find ~ -name ssh 2>/dev/null
```

## Installation Steps (No Sudo)

### Step 1: Install Python zstandard
```bash
pip3 install --user zstandard
```

### Step 2: Verify system tools
```bash
# Check if rsync exists
command -v rsync || echo "rsync not found - ask admin to install"

# Check if ssh exists (only needed for remote transfers)
command -v ssh || echo "ssh not found - ask admin to install"
```

### Step 3: Use fast-xfer!

```bash
# Make executable
chmod +x fast_xfer.py

# Use with Python zstd compression (no CLI tools needed!)
python3 fast_xfer.py /data/file.txt user@host:/data/ \
  --strategy compress \
  --compressor zstd \
  --compression-level 3
```

## What Works Without Sudo

✅ **Compression**: Fully Python-based using `zstandard` library  
✅ **Local transfers**: Uses Python's `shutil.copy2` (no rsync needed)  
✅ **Directory transfers**: Uses Python's `shutil.copytree` for local, rsync for remote  
✅ **File operations**: All Python standard library  

## What Still Needs System Tools

⚠️ **Remote transfers**: Still need `rsync` and `ssh` (usually pre-installed)  
⚠️ **Chunked strategy**: Needs `split` or `dd` (usually pre-installed)  

## Example: Full Python-Based Usage

### Local Transfer (No rsync/ssh needed!)
```bash
python3 fast_xfer.py /mnt/disk1/file.txt /mnt/disk2/file.txt \
  --strategy compress \
  --compressor zstd
```

### Remote Transfer (needs rsync/ssh, but compression is Python-based)
```bash
python3 fast_xfer.py /data/file.txt user@host:/data/file.txt \
  --strategy compress \
  --compressor zstd \
  --compression-level 3
```

## Verify Python zstandard is Working

```bash
# Test Python zstandard import
python3 -c "import zstandard; print('✓ Python zstandard OK')"

# If that works, compression will use Python library automatically!
```

## Troubleshooting

### "zstandard module not found"
```bash
pip3 install --user zstandard
# OR
pip3 install zstandard
```

### "rsync: command not found"
- For **local transfers**: Not needed! The code uses `shutil.copy2`
- For **remote transfers**: Ask admin to install `rsync`
- Or check if it's in a non-standard location: `find /usr -name rsync 2>/dev/null`

### "ssh: command not found"
- Only needed for **remote transfers**
- For **local transfers**: Not needed!
- Ask admin to install `openssh-client` or check: `find /usr -name ssh 2>/dev/null`

## Summary

**Minimum for compression (no sudo):**
```bash
pip3 install --user zstandard
```

**For local transfers (no sudo, no system tools):**
- Just use the script! It uses Python's built-in file operations.

**For remote transfers:**
- Need `rsync` and `ssh` (usually pre-installed)
- But compression is still Python-based!

The code automatically prefers Python `zstandard` over CLI `zstd` when available, so you get full Python-based compression without needing any system compression tools! 🎉
