# Transfer Without Compression (Serial Mode)

## Quick Answer

To transfer **without compression** and **serially** (one file at a time):

```bash
./fast_xfer.py /source/ /destination/ --strategy direct
```

This uses:
- **No compression** (direct rsync transfer)
- **Serial mode** (default `--parallel 1`)

## Detailed Options

### 1. No Compression

**Option A: Use `--strategy direct` (Recommended)**
```bash
./fast_xfer.py /source/ /destination/ --strategy direct
```
- Uses plain rsync, no compression
- Fastest for uncompressed transfers
- Works for both files and directories

**Option B: Disable rsync built-in compression**
```bash
# Don't use --rsync-compress flag
./fast_xfer.py /source/ /destination/ --strategy direct
```
- By default, rsync compression is **disabled**
- Only add compression if you explicitly use `--rsync-compress`

**Option C: For chunked mode, don't compress chunks**
```bash
./fast_xfer.py /source/ /destination/ --strategy chunked --parallel 1
# Don't use --compress-chunks flag
```
- Chunks are transferred uncompressed
- Still uses chunked strategy (split + transfer + reassemble)

### 2. Serial Mode (Not Parallel)

**Default is already serial:**
```bash
./fast_xfer.py /source/ /destination/ --strategy direct
# --parallel defaults to 1, so it's already serial
```

**Explicitly set to serial:**
```bash
./fast_xfer.py /source/ /destination/ --strategy direct --parallel 1
```

**For chunked/turbo strategies:**
```bash
./fast_xfer.py /source/ /destination/ --strategy chunked --parallel 1
# Transfers chunks one at a time (serial)
```

## Complete Examples

### Example 1: Simple File Transfer (No Compression, Serial)
```bash
./fast_xfer.py /mnt/source/file.txt /backup/ --strategy direct
```

### Example 2: Directory Transfer (No Compression, Serial)
```bash
./fast_xfer.py /mnt/source/data/ /backup/ --strategy direct
```

### Example 3: With Domain Mount (No Compression, Serial)
```bash
./fast_xfer.py /mnt/cust-domain/data/ /backup/ \
  --strategy direct \
  --rsync-no-inc-recursive
```

### Example 4: Large File with Extended Timeouts (No Compression, Serial)
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy direct \
  --rsync-timeout 120 \
  --rsync-operation-timeout 600
```

### Example 5: Chunked but Uncompressed and Serial
```bash
./fast_xfer.py /mnt/source/hugefile.bin /backup/ \
  --strategy chunked \
  --parallel 1 \
  --chunk-size 10G
# Chunks are NOT compressed (no --compress-chunks)
# Chunks transfer one at a time (--parallel 1)
```

## Strategy Comparison

| Strategy | Compression | Parallel | Use Case |
|----------|------------|----------|----------|
| `direct` | ❌ No | Serial (1) | **Recommended for no compression, serial** |
| `compress` | ✅ Yes | Serial (1) | Pre-compress then transfer |
| `chunked` | Optional | Configurable | Split into chunks, transfer, reassemble |
| `stream` | ✅ Yes | Serial (1) | Compress while transferring |
| `turbo` | ✅ Yes | Configurable | Optimized chunked with compression |
| `auto` | Maybe | Serial (1) | Auto-decides based on file type |

## What Each Flag Does

### Compression-Related Flags

- `--strategy direct`: **No compression** (plain rsync)
- `--rsync-compress`: Enable rsync built-in compression (default: **disabled**)
- `--compress-chunks`: Compress chunks in chunked mode (default: **disabled**)
- `--strategy compress`: Pre-compress entire file before transfer
- `--strategy stream`: Compress while transferring

### Parallel-Related Flags

- `--parallel 1`: **Serial mode** (one transfer at a time) - **This is the default**
- `--parallel N`: Parallel mode (N simultaneous transfers)
- `--assemble-parallel N`: Parallel assembly on destination (for chunked)

## Verification

To verify you're running without compression and serially:

1. **Check strategy**: Look for `[direct]` in output (not `[compress]`)
2. **Check parallel**: Look for `parallel=1` or no parallel messages
3. **Check rsync command**: Should NOT have `--compress` flag
4. **Monitor CPU**: Compression uses CPU, direct transfer uses minimal CPU

## Performance Notes

### Why Serial?
- **Simpler**: Easier to debug
- **Lower resource usage**: Less CPU, memory, network overhead
- **More reliable**: Fewer concurrent connections to manage
- **Better for slow mounts**: Domain/CIFS mounts work better serially

### Why No Compression?
- **Faster for already-compressed files**: Images, videos, archives
- **Lower CPU usage**: No compression overhead
- **Simpler**: One less step in the pipeline
- **Better for fast networks**: If network is fast, compression adds latency

## Common Use Cases

### 1. Transfer Already-Compressed Files
```bash
# Images, videos, archives don't benefit from compression
./fast_xfer.py /mnt/source/videos/ /backup/ --strategy direct
```

### 2. Fast Network, Slow CPU
```bash
# Don't waste CPU on compression if network is fast
./fast_xfer.py /mnt/source/ /backup/ --strategy direct
```

### 3. Domain Mounts (Recommended)
```bash
# Domain mounts work better without compression and serially
./fast_xfer.py /mnt/cust-domain/data/ /backup/ \
  --strategy direct \
  --rsync-no-inc-recursive
```

### 4. Simple, Reliable Transfer
```bash
# Simplest possible transfer
./fast_xfer.py /source/ /destination/ --strategy direct
```

## Summary

**For no compression + serial:**
```bash
./fast_xfer.py /source/ /destination/ --strategy direct
```

That's it! The defaults already give you:
- ✅ No compression (`direct` strategy)
- ✅ Serial mode (`--parallel` defaults to 1)

No additional flags needed!
