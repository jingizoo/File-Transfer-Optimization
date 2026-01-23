# How to Specify Chunk Size

## Quick Answer

Use the `--chunk-size` flag with the `chunked` or `turbo` strategy:

```bash
./fast_xfer.py /source/file.bin /destination/ --strategy chunked --chunk-size 10G
```

## Chunk Size Format

The chunk size accepts human-readable size formats:

### Supported Units

- **Bytes**: `1073741824` (no unit = bytes)
- **K or KB**: Kilobytes (1024 bytes)
- **M or MB**: Megabytes (1024² bytes)
- **G or GB**: Gigabytes (1024³ bytes)
- **T or TB**: Terabytes (1024⁴ bytes)

### Examples

```bash
# 500 Megabytes
--chunk-size 500M
--chunk-size 500MB

# 10 Gigabytes (default)
--chunk-size 10G
--chunk-size 10GB

# 20 Gigabytes
--chunk-size 20G
--chunk-size 20GB

# 1 Terabyte
--chunk-size 1T
--chunk-size 1TB

# 4 Gigabytes
--chunk-size 4G
```

## Complete Examples

### Example 1: Small Chunks (500MB)
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 500M \
  --parallel 1
```
**Use case**: Slow network, want faster progress updates

### Example 2: Medium Chunks (10GB) - Default
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G
```
**Use case**: 10Gbps network, balanced performance

### Example 3: Large Chunks (50GB)
```bash
./fast_xfer.py /mnt/source/hugefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 50G \
  --parallel 4
```
**Use case**: 25Gbps+ network, maximum throughput

### Example 4: Very Small Chunks (100MB)
```bash
./fast_xfer.py /mnt/source/file.bin /backup/ \
  --strategy chunked \
  --chunk-size 100M
```
**Use case**: Very slow/unreliable network, frequent progress

### Example 5: With Compression
```bash
./fast_xfer.py /mnt/source/file.bin /backup/ \
  --strategy chunked \
  --chunk-size 5G \
  --compress-chunks
```
**Use case**: Compress each chunk before transfer

## Recommended Chunk Sizes by Network Speed

| Network Speed | Recommended Chunk Size | Example |
|--------------|------------------------|---------|
| < 1 Gbps | 500M - 2G | `--chunk-size 1G` |
| 1-10 Gbps | 5G - 20G | `--chunk-size 10G` (default) |
| 10-25 Gbps | 10G - 50G | `--chunk-size 20G` |
| 25+ Gbps | 20G - 100G | `--chunk-size 50G` |

## Recommended Chunk Sizes by Use Case

### For Domain/CIFS Mounts (Slow)
```bash
--chunk-size 1G
```
- Smaller chunks = faster progress updates
- Less likely to timeout
- Better for slow metadata operations

### For Fast Local Network
```bash
--chunk-size 20G
```
- Default size works well
- Good balance of overhead vs throughput

### For Very Large Files (100GB+)
```bash
--chunk-size 50G
```
- Fewer chunks = less overhead
- Better for parallel transfers

### For Unreliable Networks
```bash
--chunk-size 500M
```
- Smaller chunks = faster recovery on failure
- Less data to retransmit if chunk fails

## How Chunking Works

1. **Split**: File is split into chunks of specified size
2. **Transfer**: Each chunk is transferred (optionally in parallel)
3. **Reassemble**: Chunks are reassembled on destination

### Example Flow

```
Original file: 100GB
Chunk size: 10G

Result:
- part.0000 (10GB)
- part.0001 (10GB)
- part.0002 (10GB)
...
- part.0009 (10GB)

Total: 10 chunks
```

## Chunk Size Considerations

### Smaller Chunks (Pros)
- ✅ Faster progress updates
- ✅ Better for slow/unreliable networks
- ✅ Less data to retransmit on failure
- ✅ Lower memory usage

### Smaller Chunks (Cons)
- ❌ More overhead (more chunks to manage)
- ❌ More network round-trips
- ❌ Slower for fast networks

### Larger Chunks (Pros)
- ✅ Less overhead
- ✅ Better for fast networks
- ✅ Fewer files to manage
- ✅ Better parallelization

### Larger Chunks (Cons)
- ❌ Slower progress updates
- ❌ More data to retransmit on failure
- ❌ Higher memory usage
- ❌ Longer timeout risk

## When to Use Chunked Strategy

Use `--strategy chunked` when:
- ✅ Transferring very large files (50GB+)
- ✅ Want to parallelize transfer
- ✅ Network is fast enough to benefit
- ✅ Want resume capability per chunk

**Don't use chunked when:**
- ❌ Small files (< 10GB)
- ❌ Very slow network (< 100 Mbps)
- ❌ Domain mounts (use `direct` instead)

## Complete Command Examples

### Domain Mount with Small Chunks
```bash
./fast_xfer.py /mnt/cust-domain/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 1G \
  --parallel 1 \
  --rsync-no-inc-recursive
```

### Fast Network with Large Chunks
```bash
./fast_xfer.py /mnt/source/hugefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 50G \
  --parallel 4
```

### Compressed Chunks
```bash
./fast_xfer.py /mnt/source/file.bin /backup/ \
  --strategy chunked \
  --chunk-size 5G \
  --compress-chunks \
  --parallel 2
```

## Default Behavior

If you don't specify `--chunk-size`:
- **Default**: `20G` (20 Gigabytes)
- Works well for most 10Gbps networks
- Good balance of performance and overhead

## Troubleshooting

### Error: "Invalid chunk_size"
- Check format: use `M`, `G`, `T` suffixes
- Examples: `500M`, `10G`, `1T`
- Don't use spaces: `10 G` ❌, `10G` ✅

### Chunks Too Small
- Symptoms: Very slow, too many chunks
- Fix: Increase chunk size: `--chunk-size 10G`

### Chunks Too Large
- Symptoms: Timeouts, hangs
- Fix: Decrease chunk size: `--chunk-size 1G`

### Out of Memory
- Symptoms: Process killed, OOM errors
- Fix: Decrease chunk size: `--chunk-size 5G`

## Summary

**Basic usage:**
```bash
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --chunk-size 10G
```

**Common sizes:**
- Small: `--chunk-size 1G`
- Medium: `--chunk-size 10G` (default)
- Large: `--chunk-size 50G`

**Format:** Use `M`, `G`, or `T` suffix (e.g., `500M`, `10G`, `1T`)
