# fast-xfer

**Highly-tuned Linux-to-Linux file transfer wrapper** for `rsync` over `ssh`, with optional `zstd` compression and parallel chunking for very large files.

## Features

- **Auto strategy**: Intelligently chooses compression when beneficial
- **Direct transfer**: Standard rsync with optimized SSH settings
- **Compression**: Multiple algorithms supported (`pigz`/`gzip`/`zstd`) → rsync → remote uncompress (best for huge text files)
- **Chunked parallel**: Split into parts, transfer in parallel, reassemble remotely (saturate 10G/25G/40G links)
- **Optimized SSH**: Fast ciphers, connection multiplexing, throughput tuning
- **Progress tracking**: Real-time transfer progress
- **Integrity verification**: Optional SHA256 checksum verification

## Quick Start

### Installation

#### Option 1: Install via pip (Recommended)

```bash
# Install from current directory
pip3 install .

# Or install in user mode (no sudo needed)
pip3 install --user .
```

After installation, use `fast-xfer` command:

```bash
# Remote transfer
fast-xfer /path/to/file.txt user@10.0.0.15:/data/replica/

# Local transfer (same server, different mount point)
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/
```

#### Option 2: Direct script usage

```bash
# Make executable
chmod +x fast_xfer.py

# Use directly
./fast_xfer.py /path/to/file.txt user@10.0.0.15:/data/replica/
```

#### Option 3: Quick install script

```bash
# Run the install script
bash install.sh
```

### Prerequisites

**Required:**
- `rsync` (always required)

**For remote transfers:**
- `ssh` (OpenSSH) on source machine
- Key-based authentication must be configured (non-interactive)
- Test with: `ssh user@host true` (should work without password)

**Optional (for compression strategies):**
- `pigz` (parallel gzip, recommended - fastest) OR `gzip` OR `zstd` (on source, and on target for remote transfers)

**Optional (for chunked strategy):**
- `split` command on source

**Note:** For local transfers (same server, different mount points), only `rsync` is required. No SSH needed.

## Usage Examples

### 1. Auto mode (recommended for most cases)

Automatically chooses the best strategy based on file compressibility:

```bash
# Remote transfer
fast-xfer /data/bigfile.txt 10.0.0.15:/data/replica/

# Local transfer (same server, different mount)
fast-xfer /mnt/disk1/bigfile.txt /mnt/disk2/replica/
```

### 2. Force compression (best for huge text files)

```bash
# Using pigz (fastest, default)
fast-xfer /data/bigfile.txt 10.0.0.15:/data/replica/ \
  --strategy compress --compressor pigz --compression-level 6

# Using zstd (better compression ratio)
fast-xfer /data/bigfile.txt 10.0.0.15:/data/replica/ \
  --strategy compress --compressor zstd --compression-level 3
```

### 3. Fast initial transfer (throughput-first, weak resume)

```bash
fast-xfer /data/bigfile.txt 10.0.0.15:/data/replica/ \
  --strategy direct --whole-file
```

### 4. Append-only files (logs, append extracts)

```bash
fast-xfer /data/logfile.txt 10.0.0.15:/data/replica/ \
  --strategy direct --append-only
```

### 5. Parallel chunked transfer (saturate fast links)

For 10G/25G/40G links, split and transfer in parallel:

```bash
fast-xfer /data/hugefile.bin 10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 20G \
  --parallel 6 \
  --compress-chunks \
  --cleanup-local-parts
```

### 6. With integrity verification

```bash
fast-xfer /data/critical.dat 10.0.0.15:/data/replica/ \
  --verify-sha256
```

## Command-Line Options

### Basic Options

- `source`: Source file path (required)
- `target`: Target like `user@10.0.0.15:/abs/path` or `10.0.0.15:/abs/path` (required)
- `--user USER`: SSH user (if not provided in target)
- `--strategy {auto,direct,compress,chunked}`: Transfer strategy (default: `auto`)

### Transfer Options

- `--append-only`: Use rsync `--append-verify` (for files that only grow by appending)
- `--whole-file`: Use rsync `--whole-file` (fastest first transfer, weakest resume)
- `--inplace`: Use rsync `--inplace` (better resume semantics)
- `--preallocate`: Use rsync `--preallocate` when possible

### Compression Options

- `--compressor {pigz,zstd,gzip}`: Compression algorithm (default: `pigz` - fastest parallel gzip)
- `--compression-level LEVEL`: Compression level (1=fast, 6=default for pigz/gzip, 3=default for zstd)
- `--compression-threads N`: Threads for compression (0=auto, pigz only)
- `--zstd-level LEVEL`: [DEPRECATED] Use `--compression-level` instead
- `--auto-sample-mib SIZE`: Auto mode sample size in MiB (default: 256)
- `--auto-threshold RATIO`: Auto mode compression threshold (default: 0.85)

### Chunked Strategy Options

- `--chunk-size SIZE`: Chunk size (e.g., `4G`, `20G`, `500M`) (default: `20G`)
- `--parallel N`: Number of parallel transfers (default: 1)
- `--compress-chunks`: Compress each chunk before transfer
- `--keep-local-parts`: Keep uncompressed local parts after compressing
- `--cleanup-local-parts`: Delete local parts after successful transfer

### Advanced Options

- `--connect-timeout SECONDS`: SSH connect timeout (default: 10)
- `--rsync-timeout SECONDS`: rsync I/O timeout (0 = disabled, default: 0)
- `--workdir DIR`: Working directory for artifacts/parts
- `--cleanup-workdir`: Remove temp subdir after success (chunked strategy)
- `--keep-local-artifact`: Keep local `.zst` artifact (compress strategy)
- `--verify-sha256`: Compute SHA256 checksums after transfer

## Strategy Details

### Auto Strategy (Default)

1. Checks if both ends have `zstd`
2. Samples the file to estimate compressibility
3. Chooses `compress` if compression ratio ≤ threshold (default 0.85)
4. Otherwise uses `direct` rsync

### Direct Strategy

Standard rsync with optimized SSH settings:
- Fast cipher selection (aes128-gcm or chacha20-poly1305)
- Connection multiplexing
- Throughput-optimized IPQoS

### Compress Strategy

1. Compress file locally with `zstd`
2. Transfer compressed file via rsync
3. Decompress on remote host
4. Clean up compressed artifacts

Best for:
- Large text files
- Files that compress well
- Constrained bandwidth

### Chunked Strategy

1. Split file into chunks
2. Optionally compress each chunk
3. Transfer chunks in parallel
4. Reassemble on remote host
5. Clean up temporary files

Best for:
- Very large files (hundreds of GB+)
- High-speed links (10G/25G/40G)
- When you need to saturate bandwidth

## Performance Tuning

### For Constrained Bandwidth

```bash
# Using pigz (faster compression)
fast-xfer file.txt user@host:/path/ --strategy compress --compressor pigz --compression-level 6

# Using zstd (better compression ratio, slower)
fast-xfer file.txt user@host:/path/ --strategy compress --compressor zstd --compression-level 3
```

### For High-Speed Links

```bash
fast-xfer hugefile.bin user@host:/path/ \
  --strategy chunked \
  --chunk-size 20G \
  --parallel 8 \
  --compress-chunks
```

### For Append-Only Files (Logs)

```bash
fast-xfer logfile.txt user@host:/path/ --strategy direct --append-only
```

## Important Notes

### Active File Writes

⚠️ **Warning**: If the source file is actively being written during transfer:
- rsync may chase a moving target
- The replica may be inconsistent
- **Best practice**: Transfer from a snapshot or stable copy

### SSH Key Setup

Ensure key-based authentication is configured:

```bash
# Generate key if needed
ssh-keygen -t ed25519

# Copy to remote host
ssh-copy-id user@host

# Test
ssh user@host true
```

### File Paths

- Source: Can be relative or absolute
- Target: **Must be absolute** (start with `/`)
  - **Local path**: `/path/to/dest` (for same-server transfers, different mount points)
  - **Remote path**: `user@host:/path/to/dest` or `host:/path/to/dest`
- If target ends with `/`, it's treated as a directory (keeps same filename)

### Local vs Remote Transfers

**Local transfers** (same server, different mount points):
```bash
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/
```
- No SSH required
- Faster (no network overhead)
- Uses direct rsync without SSH wrapper

**Remote transfers** (different servers):
```bash
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/
```
- Requires SSH key-based authentication
- Uses optimized SSH + rsync

## Troubleshooting

### "Could not determine ssh user"

Provide user explicitly:
```bash
fast-xfer file.txt 10.0.0.15:/path/ --user myuser
```

### "Target path must be an absolute path"

Use absolute paths:
```bash
# Wrong
fast-xfer file.txt user@host:relative/path
fast-xfer file.txt relative/path

# Correct (remote)
fast-xfer file.txt user@host:/absolute/path

# Correct (local)
fast-xfer file.txt /absolute/path
```

### "requires [compressor] installed"

Install compression tools:
```bash
# Install pigz (recommended - fastest)
# Debian/Ubuntu
sudo apt-get install pigz

# RHEL/CentOS
sudo yum install pigz

# macOS
brew install pigz

# Or install zstd (better compression)
# Debian/Ubuntu
sudo apt-get install zstd

# RHEL/CentOS
sudo yum install zstd

# macOS
brew install zstd

# gzip is usually pre-installed on most systems
```

### Connection Timeout

Increase timeout:
```bash
fast-xfer file.txt user@host:/path/ --connect-timeout 30
```

## License

MIT License

## Contributing

Contributions welcome! Please open issues or pull requests.

