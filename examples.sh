#!/bin/bash
# Example usage scenarios for fast-xfer

# Example 1: Basic auto transfer (remote)
echo "Example 1: Basic auto transfer (remote)"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/

# Example 1b: Basic auto transfer (local - same server, different mount)
echo "Example 1b: Basic auto transfer (local)"
fast-xfer /mnt/disk1/file.txt /mnt/disk2/replica/

# Example 2: Force compression for large text file
echo "Example 2: Force compression"
fast-xfer /data/bigfile.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --zstd-level 3

# Example 3: Fast initial transfer
echo "Example 3: Fast initial transfer"
fast-xfer /data/file.dat user@10.0.0.15:/data/replica/ \
  --strategy direct --whole-file

# Example 4: Append-only log file
echo "Example 4: Append-only log file"
fast-xfer /var/log/app.log user@10.0.0.15:/backup/ \
  --strategy direct --append-only

# Example 5: Parallel chunked transfer for huge files
echo "Example 5: Parallel chunked transfer"
fast-xfer /data/hugefile.bin user@10.0.0.15:/data/replica/ \
  --strategy chunked \
  --chunk-size 20G \
  --parallel 6 \
  --compress-chunks \
  --cleanup-local-parts

# Example 6: With integrity verification
echo "Example 6: With SHA256 verification"
fast-xfer /data/critical.dat user@10.0.0.15:/data/replica/ \
  --verify-sha256

# Example 7: Custom work directory
echo "Example 7: Custom work directory"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --workdir /tmp/xfer_work --cleanup-workdir

# Example 8: High compression for constrained bandwidth
echo "Example 8: High compression"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/ \
  --strategy compress --zstd-level 6

# Example 9: Target as directory (keeps filename)
echo "Example 9: Target as directory"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/

# Example 10: Target as specific file path
echo "Example 10: Target as specific file"
fast-xfer /data/file.txt user@10.0.0.15:/data/replica/renamed.txt

