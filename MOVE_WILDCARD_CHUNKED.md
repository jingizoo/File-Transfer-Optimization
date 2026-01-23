# Move Files with Wildcards and Chunked Strategy

## Quick Answer

Move multiple files using wildcards with chunked strategy:

```bash
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

## Complete Examples

### Example 1: Move All .bin Files with Chunked
```bash
./fast_xfer.py /mnt/source/*.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

### Example 2: Move Files Matching Pattern
```bash
./fast_xfer.py /mnt/source/file_*.log /backup/ \
  --strategy chunked \
  --chunk-size 5G \
  --remove-source \
  --parallel 1
```

### Example 3: Move Large Files with Verification
```bash
./fast_xfer.py /mnt/source/*.large /backup/ \
  --strategy chunked \
  --chunk-size 20G \
  --remove-source \
  --verify-sha256
```

### Example 4: Move with Domain Mount (Extended Timeouts)
```bash
./fast_xfer.py /mnt/cust-domain/*.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source \
  --rsync-no-inc-recursive \
  --remote-stage-base /tmp
```

## How It Works

1. **Wildcard Expansion**: Script finds all files matching the pattern
2. **Process Each File**: Each file is transferred using chunked strategy
3. **Delete Source**: After successful transfer, source file is deleted (if `--remove-source` is set)

## Features

### ✅ Wildcard Support
- `*` - matches any characters
- `?` - matches single character  
- `[abc]` - matches any character in brackets

**Examples:**
```bash
# All .bin files
*.bin

# Files starting with "data"
data*

# Files with pattern
file_*.log

# Single character wildcard
file?.txt
```

### ✅ Chunked Strategy
- Splits large files into chunks
- Transfers chunks (optionally in parallel)
- Reassembles on destination
- Works great for large files

### ✅ Move Operation
- `--remove-source` flag deletes source after successful transfer
- Only deletes if transfer succeeds
- Preserves source if transfer fails

## Complete Command Breakdown

```bash
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \          # Use chunked strategy
  --chunk-size 10G \            # 10GB chunks
  --remove-source \             # Delete source after transfer (MOVE)
  --parallel 1 \                # Serial mode (one chunk at a time)
  --remote-stage-base /tmp      # Use /tmp for staging (if /var/tmp full)
```

## Output Example

When processing multiple files:

```
[wildcard] Expanded '/mnt/source/*.bin' to 3 path(s):
  - /mnt/source/file1.bin
  - /mnt/source/file2.bin
  - /mnt/source/file3.bin
[wildcard] Processing 3 files/directories...

============================================================
[1/3] Processing: /mnt/source/file1.bin
============================================================
=== Strategy: chunked | src=/mnt/source/file1.bin -> /backup/file1.bin (local) ===
[chunked] Splitting file1.bin into 10G chunks...
...
=== Done in 45.2s ===
[move] Removing source file: /mnt/source/file1.bin
[move] Source file removed successfully

============================================================
[2/3] Processing: /mnt/source/file2.bin
============================================================
...
[move] Source file removed successfully

============================================================
[3/3] Processing: /mnt/source/file3.bin
============================================================
...
[move] Source file removed successfully

============================================================
[wildcard] Summary: 3/3 succeeded
```

## Safety Features

### 1. Only Delete on Success
- Source is only deleted if transfer succeeds (exit code 0)
- If transfer fails, source is preserved
- Error message shows which files failed

### Example with Failure:
```
[1/3] Processing: /mnt/source/file1.bin
...
ERROR: Transfer failed
[move] Transfer failed for /mnt/source/file1.bin, source file preserved

[wildcard] Summary: 2/3 succeeded
[wildcard] Failed transfers:
  - /mnt/source/file1.bin (exit code: 1)
```

### 2. Verification Before Delete
Use `--verify-sha256` to verify integrity before deleting:

```bash
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source \
  --verify-sha256
```

This ensures the file was transferred correctly before deleting source.

## Best Practices

### 1. Test First
Test with a single file before using wildcards:

```bash
# Test with one file first
./fast_xfer.py /source/test.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source

# If successful, use wildcard
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

### 2. Use Verification for Important Files
```bash
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source \
  --verify-sha256
```

### 3. Monitor Progress
The script shows progress for each file:
- File number (1/3, 2/3, etc.)
- Transfer progress
- Success/failure status
- Summary at the end

### 4. Check Space First
```bash
# Check destination has enough space
df -h /destination

# Then transfer
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

## Common Use Cases

### Move Large Archive Files
```bash
./fast_xfer.py /mnt/source/*.tar.gz /backup/ \
  --strategy chunked \
  --chunk-size 20G \
  --remove-source
```

### Move Database Dumps
```bash
./fast_xfer.py /mnt/source/db_*.sql /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source \
  --verify-sha256
```

### Move Log Files (Smaller Chunks)
```bash
./fast_xfer.py /mnt/source/*.log /backup/ \
  --strategy chunked \
  --chunk-size 1G \
  --remove-source
```

### Move with Compression
```bash
./fast_xfer.py /mnt/source/*.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --compress-chunks \
  --remove-source
```

## Troubleshooting

### Issue: "No files/directories match pattern"
**Solution**: Check the wildcard pattern and path:
```bash
# Test pattern first
ls /source/*.bin

# Then use in script
./fast_xfer.py /source/*.bin /destination/ ...
```

### Issue: Some files fail to transfer
**Solution**: Check the summary output - failed files are preserved:
```
[wildcard] Summary: 2/3 succeeded
[wildcard] Failed transfers:
  - /mnt/source/file2.bin (exit code: 1)
```

### Issue: Source deleted but transfer failed
**Solution**: This shouldn't happen - `--remove-source` only deletes on success. If it does, check:
- Disk space on destination
- File permissions
- Network connectivity

## Summary

**Move files with wildcards and chunked:**
```bash
./fast_xfer.py /source/*.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

**Key flags:**
- `--strategy chunked`: Use chunked strategy
- `--chunk-size 10G`: Specify chunk size
- `--remove-source`: Delete source after successful transfer (MOVE)
- `--verify-sha256`: Verify integrity before deleting (recommended)

**Safety:**
- ✅ Only deletes source if transfer succeeds
- ✅ Shows progress for each file
- ✅ Summary shows success/failure count
- ✅ Failed files are preserved
