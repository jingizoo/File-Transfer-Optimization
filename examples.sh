#!/bin/bash
# Example usage scenarios for fast-xfer

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