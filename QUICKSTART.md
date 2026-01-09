# Quick Start Guide

## Installation (Choose One Method)

### Method 1: Using the install script (Easiest)

```bash
bash install.sh
```

### Method 2: Using pip

```bash
pip3 install --user .
```

### Method 3: Using Make

```bash
make install-user
```

### Method 4: Direct usage (no installation)

```bash
chmod +x fast_xfer.py
./fast_xfer.py <source> <target>
```

## Basic Usage

```bash
# Remote transfer (auto-detects best strategy)
fast-xfer /path/to/file.txt user@10.0.0.15:/data/replica/

# Local transfer (same server, different mount point)
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/

# With explicit user (remote only)
fast-xfer /path/to/file.txt 10.0.0.15:/data/replica/ --user myuser
```

## Common Scenarios

### Large text file (600GB+)
```bash
fast-xfer /data/bigfile.txt user@host:/data/ --strategy compress
```

### Very large binary file on fast link
```bash
fast-xfer /data/hugefile.bin user@host:/data/ \
  --strategy chunked --parallel 8 --chunk-size 20G
```

### Log file (append-only)
```bash
fast-xfer /var/log/app.log user@host:/backup/ --append-only
```

### First-time transfer (max speed)
```bash
fast-xfer /data/file.dat user@host:/data/ --whole-file
```

## Verify Installation

```bash
# Check if command is available
which fast-xfer

# Or test with help
fast-xfer --help
```

## Troubleshooting

### Command not found after installation

Add to your `~/.bashrc` or `~/.zshrc`:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

### SSH key not set up

```bash
# Generate key
ssh-keygen -t ed25519

# Copy to remote
ssh-copy-id user@host

# Test
ssh user@host true
```

