# Why rsync Hangs When Destination is Out of Space

## Root Cause

When a filesystem runs out of space, **rsync can hang indefinitely** because:

1. **Write operations block**: When rsync tries to write data to a full filesystem, the write system call blocks waiting for space to become available. The filesystem doesn't immediately return an error - it just waits.

2. **Buffering delays error detection**: rsync buffers data before writing. It may not detect the "no space" error until the buffer fills up, which can take a long time for large transfers.

3. **No immediate ENOSPC**: The filesystem may not return `ENOSPC` (No space left on device) immediately. It might:
   - Wait for space to be freed by other processes
   - Wait for filesystem cleanup/trim operations
   - Block indefinitely if no space becomes available

4. **Silent failure**: rsync doesn't always show clear error messages when this happens - it just appears to hang.

## Solutions Implemented

### 1. **Pre-Flight Space Check** (Automatic)
Before starting any transfer, the script now:
- Calculates the total size of the source (file or directory)
- Checks available space on the destination (local or remote)
- Compares required space (with 10% safety margin) vs available space
- **Aborts with clear error message if insufficient space**

**Example output:**
```
[space-check] Calculating source size...
[space-check] Source size: 500.0 GB
[space-check] Destination available space: 100.0 GB
[space-check] ERROR: Destination out of space: need 550.0 GB, have 100.0 GB (short by 450.0 GB)
[space-check] Transfer will likely HANG when destination runs out of space.
[space-check] Solutions:
  - Free up space on destination
  - Delete old files or increase filesystem size
  - Use compression to reduce transfer size: --rsync-compress or --strategy compress
  - Transfer in smaller batches
  - Use --skip-space-check to proceed anyway (NOT RECOMMENDED)
```

### 2. **Real-Time Out-of-Space Detection**
During transfer, the script monitors rsync output for out-of-space errors:
- Detects phrases like "no space left", "disk full", "ENOSPC", etc.
- Immediately stops transfer and shows clear error message
- Explains why the hang occurred

**Example output when detected during transfer:**
```
[ERROR] DESTINATION OUT OF SPACE - This is why rsync hung!
        When a filesystem runs out of space, rsync can hang because:
        1. Write operations block indefinitely waiting for space
        2. The filesystem may not immediately return an error
        3. rsync buffers data and doesn't detect the error until buffer fills

        Solutions:
        - Free up space on destination: df -h <destination_path>
        - Delete old files or increase filesystem size
        - Use --skip-space-check to disable pre-flight checks (not recommended)
        - Transfer smaller batches or use compression to reduce size
```

### 3. **Space Check Functions**
- `get_local_available_space()`: Checks local filesystem space using `statvfs` or `shutil.disk_usage`
- `get_remote_available_space()`: Checks remote filesystem space via SSH using `df`
- `calculate_source_size()`: Calculates total size of files/directories
- `check_destination_space()`: Main function that compares source size vs available space

## Usage

### Normal Operation (Space Check Enabled by Default)
```bash
./fast_xfer.py /source/data/ /destination/
# Automatically checks space before transfer
# Aborts if insufficient space with clear error message
```

### Skip Space Check (Not Recommended)
```bash
./fast_xfer.py /source/data/ /destination/ --skip-space-check
# Proceeds even if destination appears full
# WARNING: rsync may hang if destination runs out of space during transfer
```

### With Compression to Reduce Size
```bash
./fast_xfer.py /source/data/ /destination/ --rsync-compress
# Compression reduces transfer size, may help if space is tight
```

## How to Free Up Space

### Check Current Space
```bash
# Local
df -h /destination/path

# Remote
ssh user@host "df -h /destination/path"
```

### Find Large Files to Delete
```bash
# Local
du -h /destination/path | sort -h | tail -20

# Remote
ssh user@host "du -h /destination/path | sort -h | tail -20"
```

### Delete Old Files
```bash
# Delete files older than 30 days
find /destination/path -type f -mtime +30 -delete

# Delete files larger than 10GB
find /destination/path -type f -size +10G -delete
```

## Why This Happens More on NAS Mounts

NAS (Network Attached Storage) mounts are particularly prone to this issue because:

1. **Network latency**: Network filesystems (NFS, SMB/CIFS) have additional latency that can mask the out-of-space condition
2. **Server-side buffering**: The NAS server may buffer writes, delaying error detection
3. **Quota systems**: Some NAS systems use quotas that aren't immediately visible to clients
4. **Slow error propagation**: Network filesystem errors take longer to propagate back to the client

## Prevention Tips

1. **Always check space first**: Use `df -h` before large transfers
2. **Monitor during transfer**: Watch destination space in another terminal: `watch -n 5 df -h /destination`
3. **Use compression**: `--rsync-compress` reduces transfer size
4. **Transfer in batches**: Break large transfers into smaller chunks
5. **Set up alerts**: Monitor filesystem usage and alert when space is low

## Technical Details

### Space Check Safety Margin
The script uses a **10% safety margin** by default:
- Required space = Source size × 1.1
- This accounts for:
  - Filesystem overhead
  - Temporary files during transfer
  - Metadata (inodes, directories, etc.)
  - Small variations in size calculation

### Remote Space Check
For remote transfers, the script uses:
```bash
df -B1 /path | tail -1 | awk '{print $4}'
```
This gets available space in bytes directly from the remote system.

### Source Size Calculation
- **Files**: Uses `stat().st_size`
- **Directories**: Walks the directory tree and sums all file sizes
- **Large directories**: May take a moment to calculate, but prevents hangs later

## Error Codes

- **Exit code 1**: Pre-flight space check failed (insufficient space detected)
- **Exit code 2**: Other errors (missing tools, invalid paths, etc.)
- **RuntimeError**: Out-of-space detected during transfer (with clear diagnostic message)
