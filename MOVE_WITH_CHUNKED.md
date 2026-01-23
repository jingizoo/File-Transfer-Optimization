# Move Files with Chunked Strategy

## Current Status

**The script currently only COPIES files - it does not support move operations.**

However, you can achieve a "move" by:
1. Using the script to copy (with chunked strategy)
2. Manually deleting the source after successful transfer

## Why Chunked Works for Moves

The **chunked strategy works the same way for moves as for copies**:
- ✅ Splits file into chunks
- ✅ Transfers chunks
- ✅ Reassembles on destination
- ❌ **Does NOT delete source** (you need to do this manually)

## Current Workaround

### Option 1: Copy then Delete Manually

```bash
# Step 1: Copy with chunked strategy
./fast_xfer.py /source/largefile.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G

# Step 2: Verify transfer succeeded (check exit code)
if [ $? -eq 0 ]; then
    # Step 3: Delete source after successful copy
    rm /source/largefile.bin
fi
```

### Option 2: One-Liner with Verification

```bash
./fast_xfer.py /source/largefile.bin /destination/ \
  --strategy chunked \
  --chunk-size 10G && rm /source/largefile.bin
```

### Option 3: Script Wrapper

Create a wrapper script:

```bash
#!/bin/bash
# move_with_chunked.sh

SOURCE="$1"
DEST="$2"
CHUNK_SIZE="${3:-10G}"

# Copy with chunked strategy
./fast_xfer.py "$SOURCE" "$DEST" \
  --strategy chunked \
  --chunk-size "$CHUNK_SIZE"

# Delete source only if copy succeeded
if [ $? -eq 0 ]; then
    echo "Copy successful, removing source..."
    rm "$SOURCE"
    echo "Move complete!"
else
    echo "Copy failed, source file preserved"
    exit 1
fi
```

Usage:
```bash
./move_with_chunked.sh /source/file.bin /destination/ 10G
```

## Why No Built-in Move?

The script doesn't have a `--remove-source` or `--move` flag because:

1. **Safety**: Copy-then-delete is safer - you verify the copy worked first
2. **Resume capability**: If transfer fails, source is still there
3. **Flexibility**: You can verify the copy before deleting

## Using Chunked for Large File Moves

Chunked strategy is **perfect for moving large files** because:

✅ **Handles large files**: Splits into manageable chunks
✅ **Resumable**: Can retry individual chunks
✅ **Parallelizable**: Can transfer multiple chunks simultaneously
✅ **Works on slow mounts**: Better for domain/NFS mounts

### Example: Move Large File with Chunked

```bash
# Copy with chunked (no compression, serial)
./fast_xfer.py /mnt/source/hugefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --parallel 1 \
  --remote-stage-base /tmp && \
rm /mnt/source/hugefile.bin
```

### Example: Move Directory with Chunked

For directories, chunked strategy doesn't apply (it's for single files). Use direct strategy:

```bash
# Copy directory
./fast_xfer.py /mnt/source/data/ /backup/ \
  --strategy direct && \
# Remove source directory
rm -rf /mnt/source/data/
```

## Future Enhancement

A `--remove-source` flag could be added to automatically delete source after successful transfer. This would:

- ✅ Verify transfer succeeded first
- ✅ Only delete if exit code is 0
- ✅ Provide safety checks (verify destination exists, etc.)

**Would you like me to add this feature?**

## Comparison: Copy vs Move

| Operation | Current Support | Chunked Works? |
|-----------|----------------|----------------|
| **Copy** | ✅ Yes | ✅ Yes |
| **Move** | ❌ No (manual delete) | ✅ Yes (copy part works) |

## Best Practices for Moves

1. **Always verify first**: Check that copy succeeded before deleting
2. **Use checksums**: Verify integrity before deleting source
3. **Test with small file first**: Make sure your process works
4. **Keep backups**: Don't delete source until you're sure

### Example with Verification

```bash
#!/bin/bash
SOURCE="/mnt/source/largefile.bin"
DEST="/backup/largefile.bin"

# Copy with chunked
./fast_xfer.py "$SOURCE" "$DEST" \
  --strategy chunked \
  --chunk-size 10G \
  --verify-sha256

# Only delete if copy succeeded AND checksums match
if [ $? -eq 0 ]; then
    echo "Transfer and verification successful"
    rm "$SOURCE"
    echo "Source deleted - move complete"
else
    echo "ERROR: Transfer or verification failed - source preserved"
    exit 1
fi
```

## Summary

**Current situation:**
- ✅ Chunked strategy works for copying large files
- ❌ No built-in move/delete-source option
- ✅ You can manually delete source after successful copy

**To move with chunked:**
```bash
./fast_xfer.py /source/file /dest/ --strategy chunked --chunk-size 10G && rm /source/file
```

**For safety, verify first:**
```bash
./fast_xfer.py /source/file /dest/ --strategy chunked --chunk-size 10G --verify-sha256 && rm /source/file
```
