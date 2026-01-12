# Chunk Size Optimization Guide

## Overview

The optimal chunk size for `--strategy chunked` depends on several factors. This guide helps you choose the best chunk size for your use case.

## Factors to Consider

### 1. Network Bandwidth

**High-speed links (10Gbps, 25Gbps, 40Gbps+):**
- **Recommended**: 10G - 50G per chunk
- **Rationale**: Larger chunks reduce overhead and better utilize bandwidth
- **Example**: `--chunk-size 20G --parallel 4` for 10G link

**Medium-speed links (1Gbps - 5Gbps):**
- **Recommended**: 2G - 10G per chunk
- **Rationale**: Balance between overhead and transfer efficiency
- **Example**: `--chunk-size 5G --parallel 2`

**Slow links (< 1Gbps):**
- **Recommended**: 500M - 2G per chunk
- **Rationale**: Smaller chunks allow better progress tracking and resume capability
- **Example**: `--chunk-size 1G --parallel 2`

### 2. File Size

**Very large files (500GB+):**
- Use larger chunks (20G - 50G) to minimize overhead
- More parallel workers (4-8) to saturate bandwidth

**Large files (50GB - 500GB):**
- Medium chunks (10G - 20G)
- Moderate parallelism (2-4 workers)

**Medium files (5GB - 50GB):**
- Smaller chunks (2G - 10G)
- Fewer workers (1-2) may be sufficient

**Small files (< 5GB):**
- Consider using `--strategy direct` instead of chunked
- If chunked, use 500M - 2G chunks

### 3. Available Memory

**High memory systems (32GB+):**
- Can handle larger chunks (20G - 50G)
- More parallel workers possible

**Medium memory (8GB - 32GB):**
- Moderate chunks (5G - 20G)
- Limit parallel workers to 2-4

**Low memory (< 8GB):**
- Smaller chunks (1G - 5G)
- Fewer parallel workers (1-2)

### 4. Disk I/O Performance

**Fast storage (NVMe SSD, high-end SAN):**
- Larger chunks (20G - 50G) are fine
- Can handle more parallel I/O

**Standard storage (SATA SSD, HDD):**
- Medium chunks (5G - 20G)
- Moderate parallelism to avoid I/O contention

**Slow storage (network storage, slow HDD):**
- Smaller chunks (2G - 10G)
- Fewer parallel workers

## Quick Reference Table

| Network Speed | File Size | Recommended Chunk Size | Parallel Workers |
|--------------|-----------|----------------------|------------------|
| 10Gbps+      | 500GB+    | 20G - 50G            | 4 - 8            |
| 10Gbps+      | 50-500GB  | 10G - 20G            | 2 - 4            |
| 1-5Gbps      | 100GB+    | 5G - 10G             | 2 - 4            |
| 1-5Gbps      | 10-100GB  | 2G - 5G              | 1 - 2            |
| < 1Gbps      | Any       | 500M - 2G            | 1 - 2            |

## Calculation Formula

**Rough guideline:**
```
Optimal chunk size ≈ (Network bandwidth × 10 seconds) / Parallel workers
```

**Example for 10Gbps link with 4 workers:**
- 10Gbps = 1.25GB/s
- 1.25GB/s × 10s = 12.5GB
- 12.5GB / 4 workers ≈ 3GB per chunk
- **Recommended**: 5G - 10G (accounting for overhead)

## Best Practices

1. **Start conservative**: Begin with smaller chunks (5G) and increase if needed
2. **Match parallelism**: More workers = can use larger chunks
3. **Consider compression**: With `--compress-chunks`, chunks may be smaller after compression
4. **Monitor performance**: Watch transfer speeds and adjust accordingly
5. **Avoid too many chunks**: Too many small chunks increases overhead

## Examples

### High-speed link, huge file
```bash
fast-xfer 1TB_file.dat user@host:/dest/ \
  --strategy chunked \
  --chunk-size 25G \
  --parallel 6 \
  --compress-chunks
```

### Medium-speed link, large file
```bash
fast-xfer 200GB_file.dat user@host:/dest/ \
  --strategy chunked \
  --chunk-size 10G \
  --parallel 3
```

### Slow link, any file
```bash
fast-xfer file.dat user@host:/dest/ \
  --strategy chunked \
  --chunk-size 1G \
  --parallel 2
```

## Troubleshooting

**If transfers are slow:**
- Try increasing chunk size
- Increase parallel workers
- Check if compression is helping or hurting

**If you see memory issues:**
- Reduce chunk size
- Reduce parallel workers
- Don't use compression

**If network isn't saturated:**
- Increase parallel workers
- Increase chunk size
- Check network conditions

## Auto-Detection (Future Enhancement)

The tool may in the future auto-detect optimal chunk size based on:
- File size
- Available memory
- Network speed (if detectable)
- Disk I/O capabilities

For now, use the guidelines above and experiment to find what works best for your environment.
