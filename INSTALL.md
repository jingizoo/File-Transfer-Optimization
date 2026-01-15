# Installation Guide for fast-xfer

## Quick Install

### Step 1: Install System Dependencies

Choose your operating system:

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install -y rsync openssh-client zstd pigz
```

#### CentOS/RHEL 7
```bash
sudo yum install -y rsync openssh-clients zstd pigz
```

#### CentOS/RHEL 8+ / Fedora
```bash
sudo dnf install -y rsync openssh-clients zstd pigz
```

#### macOS (via Homebrew)
```bash
brew install rsync zstd pigz
# SSH is pre-installed on macOS
```

#### Arch Linux
```bash
sudo pacman -S rsync openssh zstd pigz
```

### Step 2: Install Python Dependencies (Optional)

**Option A: Use Python zstandard library (recommended - no CLI zstd needed)**
```bash
pip3 install zstandard
# OR for user install (no sudo):
pip3 install --user zstandard
```

**Option B: Use system zstd CLI (if you prefer)**
- Already installed in Step 1 above
- No Python packages needed

### Step 3: Install fast-xfer

**Option 1: Direct usage (no installation)**
```bash
chmod +x fast_xfer.py
./fast_xfer.py --help
```

**Option 2: Install via pip**
```bash
pip3 install .
# OR for user install:
pip3 install --user .
```

**Option 3: Add to PATH manually**
```bash
# Copy to a directory in your PATH
cp fast_xfer.py ~/bin/fast-xfer
chmod +x ~/bin/fast-xfer
# Make sure ~/bin is in your PATH
export PATH="$HOME/bin:$PATH"
```

## Verify Installation

```bash
# Check Python version (needs 3.6+)
python3 --version

# Check system tools
rsync --version
ssh -V

# Check optional compression tools
zstd --version  # Optional
pigz --version  # Optional

# Check Python zstandard (if installed)
python3 -c "import zstandard; print('zstandard OK')"  # Optional

# Test fast-xfer
python3 fast_xfer.py --help
```

## Minimum Requirements

**For basic transfers (no compression):**
- Python 3.6+
- `rsync` (required)
- `ssh` (required for remote transfers only)

**For compression:**
- `zstandard` Python package OR `zstd` CLI tool
- OR `pigz` OR `gzip` (for gzip compression)

**For chunked transfers:**
- `split` or `dd` (usually pre-installed)
- `xargs` (usually pre-installed)

## Troubleshooting

### "rsync: command not found"
```bash
# Ubuntu/Debian
sudo apt-get install rsync

# CentOS/RHEL
sudo yum install rsync
```

### "ssh: command not found"
```bash
# Ubuntu/Debian
sudo apt-get install openssh-client

# CentOS/RHEL
sudo yum install openssh-clients
```

### "zstd: command not found" (if using CLI zstd)
```bash
# Ubuntu/Debian
sudo apt-get install zstd

# CentOS/RHEL
sudo yum install zstd
```

### Python zstandard not found (if using Python zstd)
```bash
pip3 install zstandard
# OR
pip3 install --user zstandard
```

### Permission denied when using fast-xfer
```bash
chmod +x fast_xfer.py
# OR if installed via pip, check PATH
which fast-xfer
```
