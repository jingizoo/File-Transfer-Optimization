# Chunked + Compress Strategy Benefits

## How It Works

1. **Split** file into chunks (e.g., 4 chunks of 5GB each)
2. **Compress** each chunk in parallel (4 workers compressing simultaneously)
3. **Transfer** compressed chunks in parallel (4 simultaneous transfers)
4. **Reassemble** on destination (decompress and concatenate)

## Benefits for Your 20GB File

### Current Performance (Sequential Compress)
- Compress 20GB → 679MB: ~30-50s (sequential, uses 1 core)
- Transfer 679MB: ~68s at 10 MB/s
- **Total: ~80-90s**

### Chunked + Compress Performance
- Split 20GB into 4 chunks: ~2s
- Compress 4×5GB chunks in parallel: ~10-15s (4 cores working simultaneously)
- Transfer 4×170MB chunks in parallel: ~17s (4 parallel transfers at 10 MB/s each = 40 MB/s effective)
- Reassemble: ~5s
- **Total: ~35-40s** (2x faster!)

## Command

```bash
fast-xfer /path/to/20gb_file.txt user@host:/dest/ \
  --strategy chunked \
  --chunk-size 5G \
  --parallel 4 \
  --compress-chunks \
  --compressor pigz \
  --compression-level 6 \
  --keep-compressed
```

## Why It's Faster

1. **Parallel Compression**: 4 chunks compressed simultaneously = 4x faster compression
2. **Parallel Transfer**: 4 transfers happening at once = better link utilization
3. **Smaller Chunks**: Each chunk is 5GB → 170MB, transfers faster than one 679MB file

## Comparison

| Strategy | Compression | Transfer | Total | Speedup |
|----------|-------------|----------|-------|---------|
| **Sequential Compress** | 30-50s | 68s | ~80-90s | 1x |
| **Chunked + Compress** | 10-15s | 17s | ~35-40s | **2x faster** |

## When to Use

✅ **Use chunked + compress when:**
- File is large (10GB+)
- You have multiple CPU cores (4+)
- Network link can handle parallel transfers
- You want maximum speed

❌ **Don't use when:**
- File is small (< 1GB)
- Single CPU core
- Very slow network (< 10 Mbps)

./fast_xfer.py \
  /opt/oracle/backup/cp84s03c/cptub05p/rman/pbck_*.dbf \
  ora9dba@10.197.126.30:/opt/app/oracle/backup/rman_202601291025133/ \
  --strategy chunked \
  --parallel 20 \
  --chunk-size 4G \
  --workdir /opt/grid/tmp \
  --cleanup-workdir \
  --skip-existing \
  --verify-sha256
