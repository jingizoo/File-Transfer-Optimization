# Best Commands for Your 20GB File (Compresses to 679MB)

## Your Current Performance
- **File**: 20GB → 679MB (3.4% ratio - excellent!)
- **Link**: 80 Mbps (~10 MB/s)
- **Current time**: 80 seconds

## Two Best Strategies to Compare

### Option 1: Pre-Compress with Auto-Threading (RECOMMENDED)
**Best for: Maximum compression ratio, best for slow links**

```bash
fast-xfer /path/to/20gb_file.txt user@host:/dest/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6 \
  --compression-threads 0 \
  --keep-compressed
```

**Why this is best:**
- Pre-compresses to 679MB (saves 97% bandwidth)
- Auto-detects all CPU cores for fastest compression
- `--keep-compressed` skips decompression (saves time)
- Transfer only 679MB instead of 20GB
- **Expected time**: ~70-90 seconds total
  - Compression: ~30-50s (with all CPU cores)
  - Transfer 679MB: ~68s at 10 MB/s
  - No decompression: 0s

### Option 2: rsync Built-in Compression (ALTERNATIVE)
**Best for: Simpler workflow, no pre-compression wait**

```bash
fast-xfer /path/to/20gb_file.txt user@host:/dest/ \
  --strategy direct \
  --rsync-compress \
  --rsync-compress-level 6
```

**Why this might be better:**
- No pre-compression wait (starts transferring immediately)
- Compresses on-the-fly during transfer
- Simpler (one step instead of compress+transfer+decompress)
- **Expected time**: ~60-80 seconds total
  - Compression happens during transfer (no separate step)
  - May be slightly faster overall

## Comparison Table

| Strategy | Compression Time | Transfer Time | Decompression | Total Time | Disk Space Saved |
|----------|-----------------|---------------|---------------|------------|------------------|
| **Option 1** (Pre-compress) | 30-50s | 68s | 0s (kept compressed) | **~70-90s** | 97% (20GB → 679MB) |
| **Option 2** (rsync-compress) | 0s (on-the-fly) | 60-80s | 0s | **~60-80s** | ~60-70% (rsync compression) |

## Recommendation

**Start with Option 2** (rsync-compress) because:
1. Simpler - one command, no waiting for compression
2. Potentially faster overall (no separate compression step)
3. Good enough compression for your use case

**If you need maximum compression** (to save bandwidth/storage), use **Option 1** (pre-compress with `--keep-compressed`).

## Quick Test Commands

Test both and compare:

```bash
# Test Option 1 (Pre-compress)
time fast-xfer /path/to/20gb_file.txt user@host:/dest/ \
  --strategy compress \
  --compressor pigz \
  --compression-level 6 \
  --compression-threads 0 \
  --keep-compressed

# Test Option 2 (rsync-compress)
time fast-xfer /path/to/20gb_file.txt user@host:/dest/ \
  --strategy direct \
  --rsync-compress \
  --rsync-compress-level 6
```

## Expected Results

- **Option 1**: Should be ~70-90s (similar to your current 80s, but keeps file compressed)
- **Option 2**: Should be ~60-80s (potentially faster, simpler workflow)

Choose based on:
- **Speed priority**: Option 2
- **Compression ratio priority**: Option 1
