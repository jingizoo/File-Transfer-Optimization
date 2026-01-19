# Compression Timing: When Does Compression Happen?

This document explains when compression occurs relative to transfer in each strategy.

## Summary Table

| Strategy | Compression Timing | How It Works |
|----------|-------------------|--------------|
| **`compress`** | **Compress FIRST, then transfer** | Sequential: Compress → Transfer → Decompress |
| **`stream`** | **Compress and transfer SIMULTANEOUSLY** | Pipeline: Compress → Transfer → Decompress (all at once) |
| **`chunked`** (with `--compress-chunks`) | **Compress chunks FIRST, then transfer** | Parallel compress chunks → Parallel transfer chunks |
| **`turbo`** | **Compress each chunk FIRST, then transfer** | Per chunk: Compress → Transfer (chunks in parallel) |
| **`direct`** (with `--rsync-compress`) | **Compress during transfer** | rsync compresses on-the-fly during transfer |

---

## Detailed Breakdown

### Strategy: `compress` - **Compress FIRST, then Transfer**

**Timeline:**
1. ✅ **Compress entire file** (wait for completion)
2. ✅ **Transfer compressed file**
3. ✅ **Decompress on destination** (unless `--keep-compressed`)

**Code Flow:**
```python
# Step 1: Compress (lines 1031-1084)
eprint("[compress] Compressing...")
comp_start = time.time()
# ... compression happens here ...
comp_elapsed = time.time() - comp_start
eprint(f"[compress] Compressed: {src_size} -> {comp_size} in {comp_elapsed:.1f}s")

# Step 2: Transfer (lines 1094-1121)
eprint("[compress] Transferring compressed file...")
transfer_start = time.time()
# ... transfer happens here ...
transfer_elapsed = time.time() - transfer_start
eprint(f"[compress] Transfer completed in {transfer_elapsed:.1f}s")
```

**Pros:**
- ✅ Know compression ratio before transfer
- ✅ Can verify compression worked
- ✅ Better for slow links (smaller file to transfer)

**Cons:**
- ❌ Must wait for full compression before transfer starts
- ❌ Uses disk space for compressed file
- ❌ Slower overall time (compression + transfer time)

---

### Strategy: `stream` - **Compress and Transfer SIMULTANEOUSLY**

**Timeline:**
1. ✅ **Compress, Transfer, and Decompress ALL AT ONCE** (pipeline)

**Code Flow:**
```python
# All happens in one pipeline (lines 920-932)
comp_proc = subprocess.Popen(comp_cmd_list, stdout=subprocess.PIPE, ...)
ssh_proc = subprocess.Popen(ssh_cmd, stdin=comp_proc.stdout, ...)
# Compression stdout → SSH stdin → Remote decompression
# All three processes run simultaneously!
```

**Message printed:**
```
[stream] Compressing and transferring simultaneously (no pre-compression wait)...
[stream] Pipeline: COMPRESS → TRANSFER → DECOMPRESS (all simultaneously)
```

**Pros:**
- ✅ **No waiting** - transfer starts immediately
- ✅ **Faster overall** - compression and transfer happen in parallel
- ✅ **No disk space** for compressed file (streams through pipes)
- ✅ **Best for real-time** transfers

**Cons:**
- ❌ Can't see compression ratio before transfer
- ❌ If compression fails, transfer also fails (but you know immediately)

---

### Strategy: `chunked` (with `--compress-chunks`) - **Compress Chunks FIRST, then Transfer**

**Timeline:**
1. ✅ **Split file into chunks**
2. ✅ **Compress all chunks in parallel** (wait for all to complete)
3. ✅ **Transfer compressed chunks in parallel**
4. ✅ **Reassemble on destination**

**Code Flow:**
```python
# Step 1: Split (line 1505)
parts = split_file(src, part_prefix, args.chunk_size, parallel=args.parallel)

# Step 2: Compress chunks (line 1536)
parts_to_send = compress_parts(parts, compressor, ...)
# All chunks compressed in parallel, but we wait for all to finish

# Step 3: Transfer (line 1570)
rsync_many_parallel(parts_to_send, ...)
# All compressed chunks transferred in parallel
```

**Pros:**
- ✅ **Parallel compression** (multiple chunks at once)
- ✅ **Parallel transfer** (multiple chunks at once)
- ✅ **Better link utilization** (multiple streams)

**Cons:**
- ❌ Must wait for all chunks to compress before transfer starts
- ❌ Uses disk space for compressed chunks

---

### Strategy: `turbo` - **Compress Each Chunk FIRST, then Transfer**

**Timeline:**
1. ✅ **For each chunk (in parallel):**
   - Compress chunk (dd → zstd)
   - Transfer compressed chunk
   - Delete local compressed chunk

**Code Flow:**
```python
# Per chunk (lines 1995-2062)
def process_chunk(idx: int):
    # Step 1: Compress chunk
    dd_p = subprocess.Popen(dd_cmd, ...)  # Read chunk from source
    z_p = subprocess.Popen(zstd_cmd, stdin=dd_p.stdout, ...)  # Compress
    # Wait for compression to finish
    
    # Step 2: Transfer compressed chunk
    rsync_cmd = [..., str(out_path), dest_stage]
    subprocess.run(rsync_cmd, ...)
    
    # Step 3: Cleanup
    out_path.unlink()

# All chunks processed in parallel (line 2075)
with ThreadPoolExecutor(max_workers=parallel) as ex:
    futs = {ex.submit(process_chunk, i) for i in range(n_chunks)}
```

**Pros:**
- ✅ **No uncompressed split files** on disk (reads directly from source via dd)
- ✅ **Parallel processing** (multiple chunks at once)
- ✅ **Efficient disk usage** (deletes compressed chunk after transfer)

**Cons:**
- ❌ Each chunk must compress before it transfers (but chunks are in parallel)
- ❌ More complex (requires dd, zstd, rsync)

---

### Strategy: `direct` (with `--rsync-compress`) - **Compress During Transfer**

**Timeline:**
1. ✅ **rsync compresses on-the-fly** during transfer

**How it works:**
- rsync's built-in compression compresses data as it transfers
- No pre-compression step
- Compression happens in the rsync process itself

**Pros:**
- ✅ **No waiting** - starts transferring immediately
- ✅ **Simple** - one command, one step

**Cons:**
- ❌ Less efficient compression (rsync's compression is weaker than zstd/pigz)
- ❌ Compression ratio not as good as pre-compression

---

## Visual Comparison

### `compress` Strategy (Sequential)
```
Time →
[========Compress========][====Transfer====][==Decompress==]
                          ↑
                    Must wait for
                    compression
                    to finish
```

### `stream` Strategy (Simultaneous)
```
Time →
[========Compress========]
[========Transfer========]
[========Decompress======]
↑
All happen
at once!
```

### `chunked` Strategy (Parallel Sequential)
```
Time →
Chunk 1: [==Compress==][==Transfer==]
Chunk 2: [==Compress==][==Transfer==]
Chunk 3: [==Compress==][==Transfer==]
Chunk 4: [==Compress==][==Transfer==]
         ↑
    All compress
    in parallel,
    then all
    transfer
```

### `turbo` Strategy (Pipelined Per Chunk)
```
Time →
Chunk 1: [==Compress==][==Transfer==]
Chunk 2: [==Compress==][==Transfer==]
Chunk 3: [==Compress==][==Transfer==]
Chunk 4: [==Compress==][==Transfer==]
         ↑
    Each chunk:
    compress then
    transfer, but
    chunks overlap
```

---

## Which Should You Use?

### Use `compress` when:
- ✅ You want to know compression ratio before transfer
- ✅ You have slow network (want maximum compression)
- ✅ You want to verify compression worked
- ✅ You don't mind waiting for compression

### Use `stream` when:
- ✅ You want **fastest overall time**
- ✅ You want to start transferring immediately
- ✅ You don't need to know compression ratio beforehand
- ✅ You want real-time pipeline

### Use `chunked` (with compression) when:
- ✅ File is very large (10GB+)
- ✅ You have multiple CPU cores
- ✅ You want parallel compression AND transfer
- ✅ You can wait for chunks to compress

### Use `turbo` when:
- ✅ File is huge (50GB+)
- ✅ You want maximum parallelism
- ✅ You want efficient disk usage
- ✅ You have zstd, dd, rsync available

### Use `direct` (with `--rsync-compress`) when:
- ✅ You want simplicity
- ✅ Compression ratio is less important
- ✅ You want to start immediately

---

## Performance Comparison Example

For a 20GB file that compresses to 679MB:

| Strategy | Compression Time | Transfer Time | Total Time |
|----------|-----------------|---------------|------------|
| **`compress`** | 45s (wait) | 68s | **113s** |
| **`stream`** | 0s (overlapped) | 68s | **68s** ⚡ |
| **`chunked`** (4 chunks) | 15s (parallel) | 17s (parallel) | **32s** ⚡⚡ |
| **`turbo`** (4 chunks) | ~15s (pipelined) | ~17s (pipelined) | **~32s** ⚡⚡ |

**Note:** `stream` and `chunked`/`turbo` are fastest because they overlap compression and transfer, or use parallelism.
