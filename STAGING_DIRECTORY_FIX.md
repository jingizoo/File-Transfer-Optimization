# Fix: /var/tmp Full Error - Change Staging Directory

## Problem

When using `chunked` or `turbo` strategy, the script may try to stage chunks in `/var/tmp` on the destination, and if that directory is full, the transfer fails.

## Why /var/tmp is Used

The script automatically uses `/var/tmp` as a staging directory when:
- **Destination is NFS mount**: Staging on local disk (`/var/tmp`) is faster than staging on NFS
- **Remote transfers with NFS destination**: Same reason - faster assembly on local disk

However, if `/var/tmp` is full, you need to use a different directory.

## Solution: Use `--remote-stage-base`

Specify a different staging directory using the `--remote-stage-base` flag:

```bash
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /tmp
```

Or use the destination directory itself:

```bash
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /destination/path
```

## Complete Examples

### Example 1: Use /tmp Instead
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remote-stage-base /tmp
```

### Example 2: Use Destination Directory
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remote-stage-base /backup
```
**Note**: This stages chunks directly in the destination directory (slower for NFS, but works if /var/tmp is full)

### Example 3: Use Custom Directory
```bash
./fast_xfer.py /mnt/source/largefile.bin /backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remote-stage-base /data/staging
```
**Note**: Make sure `/data/staging` exists and has enough space

### Example 4: For Remote Transfers
```bash
./fast_xfer.py /mnt/source/largefile.bin user@host:/backup/ \
  --strategy chunked \
  --chunk-size 10G \
  --remote-stage-base /home/user/staging
```
**Note**: The path is on the **remote** server, not local

## How Staging Works

1. **Chunks are created locally** (in `--workdir` or temp directory)
2. **Chunks are transferred** to remote staging directory (`--remote-stage-base`)
3. **Chunks are reassembled** on remote staging directory
4. **Final file is moved** from staging to destination
5. **Staging directory is cleaned up**

## Space Requirements

The staging directory needs **at least as much space as the source file** because:
- All chunks are stored there temporarily
- The reassembled file is created there before moving to final destination

**Check available space:**
```bash
# Local staging (if using local transfer)
df -h /var/tmp

# Remote staging (if using remote transfer)
ssh user@host "df -h /var/tmp"
```

## Alternative Solutions

### Option 1: Free Up /var/tmp
```bash
# Check what's using space
du -sh /var/tmp/* | sort -h | tail -10

# Clean up old files (be careful!)
find /var/tmp -type f -mtime +7 -delete
```

### Option 2: Use Destination Directory
```bash
# Stage directly in destination (works but slower for NFS)
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /destination
```

### Option 3: Use Different Temp Directory
```bash
# Use /tmp (usually has more space)
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /tmp
```

### Option 4: Use User's Home Directory
```bash
# For remote transfers, use user's home
./fast_xfer.py /source/file user@host:/destination/ \
  --strategy chunked \
  --remote-stage-base ~/staging
```

## For Local Transfers

For **local transfers**, the staging directory logic is:
- If destination is **NFS**: Uses `/var/tmp` (local disk, faster)
- If destination is **local disk**: Uses destination directory itself

To override for local transfers, you can still use `--remote-stage-base`:

```bash
./fast_xfer.py /mnt/nfs-source/file /mnt/nfs-dest/ \
  --strategy chunked \
  --remote-stage-base /tmp
```

## Troubleshooting

### Error: "No space left on device" in /var/tmp
**Solution**: Use `--remote-stage-base` to specify different directory

### Error: "Permission denied" in staging directory
**Solution**: 
- Check permissions: `ls -ld /var/tmp`
- Use directory you have write access to: `--remote-stage-base /home/user/staging`

### Error: "Staging directory doesn't exist"
**Solution**: 
- Create the directory first: `mkdir -p /path/to/staging`
- Or use existing directory: `--remote-stage-base /tmp`

### Warning: "Staging on NFS is slow"
**Solution**: 
- If you must use NFS for staging, it will work but be slower
- Consider using local disk staging if possible

## Best Practices

1. **Check space before transfer:**
   ```bash
   df -h /var/tmp
   ```

2. **Use staging directory with enough space:**
   ```bash
   # Check available space
   df -h /tmp
   
   # Use it if it has space
   --remote-stage-base /tmp
   ```

3. **For large files, ensure staging has space:**
   ```bash
   # File is 100GB, staging needs at least 100GB free
   ./fast_xfer.py /source/100gb-file /dest/ \
     --strategy chunked \
     --remote-stage-base /data/staging  # Make sure /data/staging has 100GB+ free
   ```

4. **Clean up staging after transfer:**
   - The script automatically cleans up staging directory after successful transfer
   - If transfer fails, you may need to manually clean: `rm -rf /var/tmp/._xfer_*`

## Summary

**To fix "/var/tmp full" error:**

```bash
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /tmp
```

**Or use destination directory:**
```bash
./fast_xfer.py /source/file /destination/ \
  --strategy chunked \
  --remote-stage-base /destination
```

**Key points:**
- `--remote-stage-base` specifies where to stage chunks on **destination side**
- Staging directory needs **at least as much space as source file**
- For remote transfers, path is on **remote server**
- Script automatically cleans up staging after successful transfer
