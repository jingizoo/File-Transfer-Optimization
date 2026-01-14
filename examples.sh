#!/bin/bash
# Example usage scenarios for fast-xfer
#
# COMPATIBILITY NOTES:
# - Examples 1-248: Work with older versions (single files only)
# - Directory support (folders) is NEW - older versions will error on directories
# - All examples below are for SINGLE FILE transfers (compatible with older xfer)

# ============================================================================
# BASIC SINGLE FILE TRANSFERS (Compatible with older fast-xfer)
# ============================================================================

# Example 1: Basic auto transfer (remote)
echo "Example 1: Basic auto transfer (remote)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/

# Example 1b: Basic auto transfer (local - same server, different mount)
echo "Example 1b: Basic auto transfer (local)"
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/

# Example 2: Force compression with pigz (fastest, default)
echo "Example 2: Force compression with pigz (fastest)"
fast-xfer /data/bigfile.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --compressor pigz --compression-level 6

# Example 2b: Force compression with zstd (better ratio, slower)
echo "Example 2b: Force compression with zstd (better compression)"
fast-xfer /data/bigfile.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --compressor zstd --compression-level 3

# Example 3: Fast initial transfer
echo "Example 3: Fast initial transfer"
fast-xfer /data/file.dat user@10.0.0.15:/data/replica/ \
  --strategy direct --whole-file

# Example 4: Append-only log file
echo "Example 4: Append-only log file"
fast-xfer /var/log/app.log user@10.0.0.15:/backup/ \
  --strategy direct --append-only

# Example 5: Parallel chunked transfer for huge files (with pigz compression)
echo "Example 5: Parallel chunked transfer with pigz compression"
fast-xfer /data/hugefile.bin user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 20G \
  --parallel 6 \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6 \
  --cleanup-local-parts

# Example 6: With integrity verification
echo "Example 6: With SHA256 verification"
fast-xfer /data/critical.dat user@10.0.0.15:/data/replica/ \
  --verify-sha256

# Example 7: Custom work directory
echo "Example 7: Custom work directory"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --workdir /tmp/xfer_work --cleanup-workdir

# Example 8: High compression for constrained bandwidth (pigz)
echo "Example 8: High compression with pigz (fast)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --compressor pigz --compression-level 9

# Example 8b: Maximum compression with zstd (slower but better ratio)
echo "Example 8b: Maximum compression with zstd"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --compressor zstd --compression-level 19

# Example 9: Target as directory (keeps filename)
echo "Example 9: Target as directory"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/

# Example 10: Target as specific file path
echo "Example 10: Target as specific file"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/renamed.txt

# Example 11: Pigz with custom thread count
echo "Example 11: Pigz with custom thread count"
fast-xfer /data/largefile.txt user@10.0.0.15:/data/replica/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6 \
  --compression-threads 8

# Example 12: Local transfer with pigz compression
echo "Example 12: Local transfer with pigz compression"
fast-xfer /mnt/disk1/largefile.txt /mnt/disk2/replica/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6

# Example 13: Auto mode with pigz (default compressor)
echo "Example 13: Auto mode (uses pigz by default)"
fast-xfer /data/bigfile.txt user@10.0.0.15:/data/replica/ \
  --strategy auto \
  --compressor pigz

# Example 14: Fast compression with pigz (level 1)
echo "Example 14: Fast compression with pigz (level 1)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 1

# Example 15: Skip estimation to avoid hanging (fast start)
echo "Example 15: Skip compression estimation (fast start, no hanging)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy auto \
  --skip-estimate

# Example 16: Split + compress (for very large files)
echo "Example 16: Split + compress (chunked with compression)"
fast-xfer /data/hugefile.txt user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6 \
  --chunk-size 10G \
  --parallel 4 \
  --cleanup-local-parts

# Example 17: Split + compress with zstd (better compression)
echo "Example 17: Split + compress with zstd"
fast-xfer /data/hugefile.txt user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --compress-chunks \
  --compressor zstd \
  --compression-level 3 \
  --chunk-size 20G \
  --parallel 6 \
  --cleanup-local-parts

# Example 18: Local transfer with skip-estimate (fast)
echo "Example 18: Local transfer skipping estimation"
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/ \
  --skip-estimate

# Example 19: Reduce estimation timeout (faster fallback)
echo "Example 19: Auto mode with short estimation timeout"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy auto \
  --estimate-timeout 10

# Example 20: Direct transfer (bypasses all auto-detection)
echo "Example 20: Direct transfer (no compression, no estimation)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy direct

# Example 21: Custom temp directory (instead of /tmp)
echo "Example 21: Using custom temp directory"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --temp-dir /var/tmp

# Example 22: Using TMPDIR environment variable
echo "Example 22: Temp dir via TMPDIR env var (set before running)"
# export TMPDIR=/custom/temp
# fast-xfer /data/file.txt user@10.0.0.15:/data/replica/

# ============================================================================
# EXCELLENT COMPRESSION SCENARIOS (20GB -> 679MB = 3.4% ratio)
# ============================================================================

# Example 31: EXCELLENT compression - Pre-compress then transfer (BEST for 80 Mbps)
echo "Example 31: Excellent compression (20GB -> 679MB) - Pre-compress strategy"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6 \
  --compression-threads 0  # Auto-detect CPU cores

# Example 32: Excellent compression with chunked + compress (for very large files)
echo "Example 32: Excellent compression with chunked strategy"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 5G \
  --parallel 4 \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6

# Example 33: Keep compressed file on destination (skip decompression)
echo "Example 33: Keep compressed file on destination (no decompression)"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6 \
  --keep-compressed

# Example 34: Keep compressed chunks (for chunked strategy)
echo "Example 34: Keep compressed chunks on destination"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 5G \
  --parallel 4 \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6 \
  --keep-compressed

# Example 35: BEST - Chunked + Compress (FASTEST for large files with good compression)
echo "Example 35: Chunked + Compress - Parallel compression and transfer (FASTEST)"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 5G \
  --parallel 4 \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6 \
  --keep-compressed \
  --cleanup-local-parts

# Example 36: Stream transfer - COMPRESS + TRANSFER + DECOMPRESS all at once (BEST for real-time pipeline)
echo "Example 36: Stream transfer - Compress, transfer, and decompress ALL AT ONCE (no waiting)"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy stream \
  --compressor pigz \
  --compression-level 6 \
  --compression-threads 0 \
  --decompression-threads 0
# Note: By default, decompresses on destination automatically (use --keep-compressed to skip)

# Example 37: Stream transfer with zstd (compress + transfer + decompress simultaneously)
echo "Example 37: Stream transfer with zstd - All operations happen simultaneously"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy stream \
  --compressor zstd \
  --compression-level 3 \
  --compression-threads 0 \
  --decompression-threads 0

# Example 38: Stream transfer with pigz (keep compressed on destination)
echo "Example 38: Stream transfer with pigz, keep compressed (skip decompression)"
fast-xfer /data/20gb_file.txt user@10.0.0.15:/data/replica/ \
  --strategy stream \
  --compressor pigz \
  --compression-level 6 \
  --keep-compressed

# Example 39: NFS-to-NFS streaming (stream via SSH to NFS server)
echo "Example 39: NFS-to-NFS streaming - Stream compress+transfer+decompress via SSH to NFS server"
fast-xfer /mnt/nfs1/500gb_file.txt /mnt/nfs2/replica/ \
  --strategy stream \
  --compressor pigz \
  --compression-level 6 \
  --nfs-server nfs-server.example.com \
  --user myuser

# Example 40: NFS-to-NFS streaming with auto-detection (if NFS mount detected)
echo "Example 40: NFS-to-NFS streaming with auto-detection (if destination is NFS mount)"
fast-xfer /mnt/nfs1/500gb_file.txt /mnt/nfs2/replica/ \
  --strategy stream \
  --compressor zstd \
  --compression-level 3 \
  --nfs-server nfs-server.example.com

# ============================================================================
# OLDER XFER COMPATIBILITY - SINGLE FILE ONLY (No directory support)
# ============================================================================
# These examples work with older versions of fast-xfer that only handle single files.
# For directory transfers, use rsync directly or upgrade to newer fast-xfer.

# Example 41: OLDER XFER - Basic single file transfer (works with older versions)
echo "Example 41: OLDER XFER - Basic single file (compatible with older fast-xfer)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/file.txt

# Example 42: OLDER XFER - Single file with compression (older behavior)
echo "Example 42: OLDER XFER - Single file with zstd compression"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/file.txt \
  --strategy compress \
  --compressor zstd \
  --compression-level 3

# Example 43: OLDER XFER - Single file chunked transfer (older behavior)
echo "Example 43: OLDER XFER - Single file chunked with zstd compression"
fast-xfer /data/hugefile.txt user@10.0.0.15:/data/replica/hugefile.txt \
  --strategy chunked \
  --compress-chunks \
  --compressor zstd \
  --compression-level 3 \
  --chunk-size 20G \
  --parallel 8 \
  --keep-compressed

# Example 44: OLDER XFER - Single file stream transfer (older behavior)
echo "Example 44: OLDER XFER - Single file stream with zstd"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/file.txt \
  --strategy stream \
  --compressor zstd \
  --compression-level 3 \
  --keep-compressed

# Example 45: OLDER XFER - Single file turbo strategy (zstd only, older behavior)
echo "Example 45: OLDER XFER - Single file turbo strategy with zstd"
fast-xfer /data/hugefile.txt user@10.0.0.15:/data/replica/hugefile.txt \
  --strategy turbo \
  --compressor zstd \
  --compression-level 3 \
  --chunk-size 20G \
  --parallel 8 \
  --keep-compressed

# Example 46: OLDER XFER - Single file without compression (max parallel, older behavior)
echo "Example 46: OLDER XFER - Single file without compression, max parallel"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/file.txt \
  --strategy chunked \
  --parallel 16 \
  --chunk-size 20G \
  --assemble-parallel 8

# ============================================================================
# NOTE: Directory transfers are NEW and require newer fast-xfer version
# For older versions, use rsync directly for directories:
#   rsync -rtvh --info=progress2 /src_dir/ user@host:/dest_dir/
# ============================================================================