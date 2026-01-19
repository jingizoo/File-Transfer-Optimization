# fast-xfer Output Statistics and Information

This document describes all the statistics, progress information, and messages that `fast-xfer` prints during execution.

## Overview

`fast-xfer` prints detailed statistics throughout the transfer process, including:
- File sizes (original, compressed, transferred)
- Compression ratios
- Transfer speeds
- Progress percentages
- Time elapsed
- ETA (Estimated Time to Arrival)
- Thread/worker counts
- Success/failure counts

---

## Output by Strategy

### Strategy: `direct` (Simple File Transfer)

#### Local Transfer
```
[local] Detected local path - using direct file operations
[local] Copying filename.txt (1.23GiB)...
[local] Copy completed in 2.5s (500.00MiB/s)
=== Done in 2.5s ===
```

#### Remote Transfer
```
=== Strategy: direct | src=/path/file.txt -> user@host:/path/file.txt ===
[direct] Using rsync built-in compression (level 1) for on-the-fly compression
=== Done in 15.2s ===
```

**Statistics Shown:**
- Source file size
- Copy/transfer speed
- Total elapsed time

---

### Strategy: `compress` (Pre-compress, Transfer, Decompress)

#### Compression Phase
```
[compress] Compressing filename.txt (20.00GiB) with zstd level 3...
[compress] Using Python zstandard library with 8 threads...
[compress] Compressed: 20.00GiB -> 679.50MiB (3.3%) in 45.2s (453.10MiB/s)
```

**If compression ratio is poor:**
```
[compress] WARNING: Compression ratio is 95.2% - file may already be compressed or incompressible
[compress] Suggestion: Use --strategy direct for better performance on incompressible files
```

**If compressed file is larger:**
```
[compress] WARNING: Compressed file is LARGER than original (102.5%)!
[compress] This file does not compress well. Consider using --strategy direct instead
```

#### Transfer Phase
```
[compress] Transferring compressed file (679.50MiB)...
[compress] Transfer completed in 12.3s (55.24MiB/s)
```

#### Decompression Phase (if not --keep-compressed)
```
[compress] Decompressing on destination (optimized)...
[compress] Using 8 threads for decompression
```

#### Final Summary
```
[compress] Cleaned up local artifact: /tmp/file.txt.zst
=== Done in 62.5s ===
```

**Statistics Shown:**
- Original file size
- Compressed file size
- Compression ratio (percentage)
- Compression speed
- Compression time
- Transfer speed
- Transfer time
- Decompression thread count
- Total elapsed time

---

### Strategy: `stream` (Compress + Transfer + Decompress Simultaneously)

#### Initial Setup
```
[stream] Streaming compression and transfer: filename.txt (20.00GiB) with zstd level 3...
[stream] Compressing and transferring simultaneously (no pre-compression wait)...
[stream] Pipeline: COMPRESS → TRANSFER → DECOMPRESS (all simultaneously)
[stream] Using 8 threads for decompression on destination
```

#### Progress Updates (during transfer)
```
[stream] Transferring... 15.2s elapsed (~45% estimated, ~1.20GiB/s)
```

#### Final Summary
```
[stream] Transfer completed in 33.5s (610.45MiB/s)
[stream] File decompressed on destination: /path/file.txt
=== Done in 33.5s ===
```

**If --keep-compressed:**
```
[stream] Compressed file saved: /path/file.txt.zst
[stream] To decompress manually: zstd -d /path/file.txt.zst
```

**Statistics Shown:**
- Source file size
- Compression level and algorithm
- Decompression thread count
- Elapsed time (during transfer)
- Estimated progress percentage
- Estimated transfer speed
- Final transfer speed
- Total elapsed time

---

### Strategy: `chunked` (Split + Transfer + Reassemble)

#### Splitting Phase
```
[chunked] Splitting filename.txt into 5 chunks using parallel dd (workers=4)...
[chunked] Split progress: 3/5 chunks (2.1s)
[chunked] Created 5 parts in 3.2s (parallel dd)
```

**Or with sequential split:**
```
[chunked] Splitting filename.txt into 20G chunks (using split)...
[chunked] Created 5 parts (sequential split)
```

#### Compression Phase (if --compress-chunks)
```
[chunked] Compressing 5 parts with zstd level 3 (parallel=4, threads/job=2)...
[chunked] Compressed all parts
```

#### Transfer Phase - Local
```
[chunked] Copying 5 files in parallel (workers=4)...
[chunked] Starting parallel copy of 5 files (20.00GiB) with 4 workers...
[chunked] Progress: 3/5 files (12.00GiB/20.00GiB) - 1.50GiB/s - ETA: 5s
[chunked] ✓ All 5 parts copied successfully in 15.3s (1.31GiB/s)
```

#### Transfer Phase - Remote
```
[chunked] Transferring 5 files in parallel (workers=4)...
[chunked] Starting parallel transfer of 5 files (20.00GiB) with 4 workers...
[chunked] Progress:  60.00%  3/5 files  12.00GiB/20.00GiB  avg=1.50GiB/s
[chunked] ✓ All 5 parts transferred successfully
```

**If errors occur:**
```
[chunked] ERROR: Failed to transfer 2/5 files:
  - part.0002.zst: Connection timeout
  - part.0004.zst: Permission denied
  ... and 0 more failures
```

#### Reassembly Phase
```
[chunked] Reassembling and decompressing file on destination (optimized)...
[chunked] Using 8 threads per chunk for parallel decompression
[chunked] Using TURBO mode: dd-based assembly (writes directly to final file, no temp decompressed chunks)
```

**Or if keeping compressed:**
```
[chunked] Keeping compressed chunks and concatenating to /path/file.txt.zst...
```

**Or for uncompressed chunks:**
```
[chunked] Using parallel dd-based concatenation for uncompressed chunks (4 workers)
```

#### Cleanup
```
[chunked] Cleaned up temporary directory: /tmp/xfer_filename_1234567890
=== Done in 28.5s ===
```

**Statistics Shown:**
- Number of chunks created
- Chunk size
- Split method (parallel dd vs sequential split)
- Split time
- Compression settings (if enabled)
- Number of files to transfer
- Total size to transfer
- Parallel workers count
- Progress: files completed/total
- Progress: bytes transferred/total
- Current/average transfer speed
- ETA (for local transfers)
- Transfer completion time and speed
- Reassembly mode
- Decompression thread count
- Total elapsed time

---

### Strategy: `turbo` (Zstd-optimized Chunked)

#### Initial Configuration
```
[turbo] src=filename.txt size=20.00GiB chunks=5 chunk=4.00GiB bs=4.00MiB
[turbo] parallel=4 comp_threads/job=2 assemble_parallel=4 decomp_threads/job=2
[turbo] remote dest_fs=nfs4 stage_dir=/var/tmp/._xfer_filename_1234567890
```

#### Compression + Transfer Phase
```
[turbo] Compress+transfer pipeline starting...
[turbo] progress: 2/5 chunks done (12.3s)
[turbo] progress: 4/5 chunks done (18.7s)
[turbo] ✓ All chunks transferred in 25.1s
```

#### Assembly Phase
```
[turbo] Remote assemble mode=seek (parallel scatter write)
```

**Or if NFS detected:**
```
[turbo] Remote assemble mode=append (dest on NFS detected)
```

**If keeping compressed:**
```
[turbo] Keeping compressed file (concatenating chunks to /path/file.txt.zst)
```

#### Final Summary
```
=== Done in 28.5s ===
```

**Statistics Shown:**
- Source file name and size
- Number of chunks
- Chunk size
- Block size (bs) for dd operations
- Parallel workers for compression
- Compression threads per job
- Assembly parallel workers
- Decompression threads per job
- Remote filesystem type
- Staging directory
- Progress: chunks completed/total
- Time elapsed per progress update
- Total transfer time
- Assembly mode
- Total elapsed time

---

### Strategy: `auto` (Automatic Strategy Selection)

#### Compression Estimation
```
[auto] Estimating compression ratio with zstd...
[auto] zstd sample: in=256.00MiB out=8.50MiB ratio=0.033
```

**If estimation fails:**
```
[auto] Compression estimation failed or timed out, using direct transfer
```

**If skipping estimation:**
```
[auto] Skipping compression estimation (--skip-estimate)
```

**Then proceeds with selected strategy** (direct, compress, etc.) and shows that strategy's output.

**Statistics Shown:**
- Compression algorithm used for estimation
- Sample input size
- Sample output size
- Compression ratio
- Selected strategy (implicitly, by what follows)

---

### Directory Transfer (rsync-based)

#### Local Directory
```
[local] Detected local path - using direct file operations
[dir] Using rsync for local directory copy: /src/folder/ -> /dest/folder/
=== Directory transfer (rsync) | src=/src/folder/ -> /dest/folder/ (local) ===
=== Done in 45.2s ===
```

#### Remote Directory
```
[dir] Using rsync for remote directory transfer: /src/folder/ -> /dest/folder/ on user@host
=== Directory transfer (rsync) | src=/src/folder/ -> user@host:/dest/folder/ ===
=== Done in 120.5s ===
```

**If rsync compression enabled:**
```
[dir] Using rsync with built-in compression (level 1) for directory transfer
```

**Statistics Shown:**
- Source and destination paths
- Transfer type (local/remote)
- Total elapsed time
- (rsync itself may show additional progress)

---

## SHA256 Verification (--verify-sha256)

```
=== Verifying sha256 (this will read the full file on both ends) ===
source sha256:  a1b2c3d4e5f6...
dest sha256:    a1b2c3d4e5f6...
```

**If mismatch:**
```
ERROR: sha256 mismatch: transfer may be corrupted
```

**For directories:**
```
[dir] NOTE: --verify-sha256 is not implemented for directory transfers; skipping integrity check
```

---

## Warnings and Errors

### Compression Warnings
```
[compress] WARNING: Compression ratio is 95.2% - file may already be compressed or incompressible
[compress] Suggestion: Use --strategy direct for better performance on incompressible files
```

### Missing Tools Warnings
```
[chunked] WARNING: 'dd' not found on remote - turbo mode (dd-based assembly) will be disabled
[chunked] WARNING: 'xargs' not found on remote - turbo mode (dd-based assembly) will be disabled
```

### NFS Detection
```
[chunked] NFS mount detected at destination - staging on /var/tmp for faster assembly
[chunked] Remote NFS detected - staging on /var/tmp for faster assembly
```

### Strategy Override (for directories)
```
[dir] WARNING: Source is a directory; ignoring --strategy=turbo and using rsync directory transfer
```

---

## Human-Readable Size Format

All file sizes are displayed in human-readable format:
- `B` = Bytes
- `KiB` = Kibibytes (1024 bytes)
- `MiB` = Mebibytes (1024² bytes)
- `GiB` = Gibibytes (1024³ bytes)
- `TiB` = Tebibytes (1024⁴ bytes)

Examples:
- `1.23GiB` = 1.23 × 1024³ bytes
- `500.00MiB` = 500 × 1024² bytes
- `679.50MiB` = 679.5 × 1024² bytes

---

## Progress Indicators

### Real-time Progress (chunked strategy)
- Updates on the same line (using `\r`)
- Shows: `Progress: XX.XX%  completed/total  bytes_transferred/total_bytes  avg=speed/s`

### Periodic Updates (stream strategy)
- Updates every few seconds
- Shows: `Transferring... X.Xs elapsed (~XX% estimated, ~speed/s)`

### Completion Messages
- All successful transfers end with: `=== Done in X.Xs ===`
- Chunked transfers show: `✓ All N parts transferred successfully`

---

## Example Complete Output

### Example: Compress Strategy (Remote)
```
=== Strategy: compress | src=/data/bigfile.txt -> user@10.0.0.15:/backup/bigfile.txt ===
[compress] Compressing bigfile.txt (20.00GiB) with zstd level 3...
[compress] Using Python zstandard library with 8 threads...
[compress] Compressed: 20.00GiB -> 679.50MiB (3.3%) in 45.2s (453.10MiB/s)
[compress] Transferring compressed file (679.50MiB)...
[compress] Transfer completed in 12.3s (55.24MiB/s)
[compress] Decompressing on destination (optimized)...
[compress] Using 8 threads for decompression
[compress] Cleaned up local artifact: /tmp/bigfile.txt.zst
=== Done in 62.5s ===
```

### Example: Chunked Strategy (Local)
```
=== Strategy: chunked | src=/data/hugefile.bin -> /backup/hugefile.bin (local) ===
[chunked] Splitting hugefile.bin into 5 chunks using parallel dd (workers=4)...
[chunked] Created 5 parts in 3.2s (parallel dd)
[chunked] Compressing 5 parts with zstd level 3 (parallel=4, threads/job=2)...
[chunked] Compressed all parts
[chunked] Copying 5 files in parallel (workers=4)...
[chunked] Starting parallel copy of 5 files (20.00GiB) with 4 workers...
[chunked] Progress: 5/5 files (20.00GiB/20.00GiB) - 1.50GiB/s
[chunked] ✓ All 5 parts copied successfully in 15.3s (1.31GiB/s)
[chunked] Reassembling and decompressing file on destination (optimized)...
[chunked] Using 8 threads per chunk for parallel decompression
[chunked] Using TURBO mode: dd-based assembly (writes directly to final file, no temp decompressed chunks)
[chunked] Cleaned up temporary directory: /tmp/xfer_hugefile_1234567890
=== Done in 28.5s ===
```

---

## Summary Table

| Statistic | Where Shown | Format |
|-----------|-------------|--------|
| **File Size** | All strategies | `20.00GiB`, `679.50MiB` |
| **Compression Ratio** | compress, auto | `3.3%`, `95.2%` |
| **Compression Speed** | compress | `453.10MiB/s` |
| **Transfer Speed** | All strategies | `1.50GiB/s`, `55.24MiB/s` |
| **Progress %** | chunked (remote), stream | `60.00%`, `~45%` |
| **Files/Chunks Progress** | chunked | `3/5 files`, `2/5 chunks` |
| **Bytes Progress** | chunked | `12.00GiB/20.00GiB` |
| **ETA** | chunked (local) | `ETA: 5s` |
| **Elapsed Time** | All strategies | `15.3s`, `62.5s` |
| **Thread Count** | compress, stream, chunked | `8 threads`, `4 workers` |
| **SHA256 Hash** | verify-sha256 | `a1b2c3d4e5f6...` |

---

## Notes

1. **Progress updates** may overwrite the same line (using `\r`) for real-time updates
2. **Time precision**: Usually shown to 1 decimal place (e.g., `15.3s`)
3. **Speed calculations**: Based on original file size (for compressed transfers, shows effective speed)
4. **Error messages**: Always shown on separate lines and include context
5. **Warnings**: Prefixed with `WARNING:` and include suggestions when applicable
