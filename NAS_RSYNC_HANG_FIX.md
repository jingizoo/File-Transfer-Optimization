# rsync Hang Prevention on NAS Mounts

## Root Causes of rsync Hangs on NAS Mounts

### 1. **Deep Directory Recursion**
- **Problem**: rsync uses incremental recursion by default, which can hang when scanning very large directory trees on slow NAS
- **Symptom**: rsync appears to hang during initial directory scanning
- **Solution**: Use `--no-inc-recursive` flag (enabled via `--rsync-no-inc-recursive`)

### 2. **Slow Metadata Operations**
- **Problem**: `stat()` calls on every file can hang if NAS is slow to respond
- **Symptom**: rsync hangs when reading file metadata (permissions, timestamps, etc.)
- **Solution**: Set `--rsync-timeout` to limit how long rsync waits for metadata operations

### 3. **Connection Timeouts**
- **Problem**: TCP connections can hang without proper timeout/keepalive
- **Symptom**: rsync hangs on initial connection or during transfer
- **Solution**: 
  - `--rsync-contimeout` sets connection timeout
  - SSH keepalive (automatically enabled: `ServerAliveInterval=30`, `ServerAliveCountMax=3`)

### 4. **Large Directory Listings**
- **Problem**: Reading directory contents from slow NAS can hang
- **Symptom**: rsync hangs when listing files in a directory
- **Solution**: `--no-inc-recursive` helps, also consider filtering with `--max-size` or `--min-size`

### 5. **File Locking Issues**
- **Problem**: Files in use by other processes can cause rsync to hang
- **Symptom**: rsync hangs on specific files
- **Solution**: Check for file locks with `lsof` or `fuser` before transfer

### 6. **Permission Issues**
- **Problem**: Access denied errors can cause silent hangs in some cases
- **Symptom**: rsync hangs without clear error message
- **Solution**: Check rsync output for permission errors, ensure proper access

### 7. **Symlink Issues**
- **Problem**: Following broken or problematic symlinks can hang
- **Symptom**: rsync hangs when encountering symlinks
- **Solution**: `--safe-links` flag (automatically enabled) prevents following symlinks outside the tree

## Solutions Implemented

### 1. **SSH Keepalive** (Automatic)
- `ServerAliveInterval=30`: Send keepalive every 30 seconds
- `ServerAliveCountMax=3`: Disconnect after 3 failed keepalives (90s total)
- Prevents connection hangs

### 2. **rsync Connection Timeout**
- `--contimeout`: Limits time to establish connection
- Default: same as `--rsync-timeout` if set
- Prevents hanging on initial connection

### 3. **rsync Operation Timeout**
- `--rsync-operation-timeout`: Maximum time for entire rsync operation
- Default: 300 seconds
- Automatically kills stuck rsync processes

### 4. **No Incremental Recursion**
- `--rsync-no-inc-recursive`: Use `--no-inc-recursive` flag
- Prevents deep recursion hangs on large directories
- **Recommended for NAS mounts**

### 5. **Safe Links**
- `--safe-links`: Automatically enabled
- Prevents following problematic symlinks

### 6. **Better Progress Reporting**
- `--info=progress2,name`: Shows both progress and file names
- Helps identify where rsync is stuck

### 7. **Automatic Retry**
- `--rsync-max-retries`: Retry failed operations (default: 3)
- Exponential backoff between retries
- Helps with transient network issues

## Usage Examples

### Basic NAS Transfer (Recommended Settings)
```bash
./fast_xfer.py /mnt/nas/data/ /backup/ \
  --rsync-timeout 60 \
  --rsync-contimeout 30 \
  --rsync-operation-timeout 300 \
  --rsync-no-inc-recursive \
  --rsync-max-retries 3
```

### For Very Slow NAS
```bash
./fast_xfer.py /mnt/nas/data/ /backup/ \
  --rsync-timeout 30 \
  --rsync-contimeout 15 \
  --rsync-operation-timeout 180 \
  --rsync-no-inc-recursive \
  --rsync-max-retries 5
```

### For Fast NAS (Minimal Timeouts)
```bash
./fast_xfer.py /mnt/nas/data/ /backup/ \
  --rsync-timeout 120 \
  --rsync-contimeout 60 \
  --rsync-operation-timeout 600
```

## Diagnostic Output

When rsync hangs or times out, the script now provides diagnostic information:

```
[rsync] Starting transfer (attempt 1/3)...
[rsync] If this hangs, it's likely stuck on:
        - Directory scanning/listing (large directories)
        - Metadata operations (stat() calls on slow NAS)
        - Network timeout (check NAS connectivity)
        - File permissions (access denied)

[retry] rsync timed out/hung on attempt 1/3
[diagnostic] This usually means rsync was stuck on:
            - Scanning directories (use --no-inc-recursive)
            - Reading file metadata (NAS is slow to respond)
            - Network connection (check NAS mount health)

[ERROR] rsync failed after 3 attempts.
[diagnostic] Common root causes for rsync hangs on NAS mounts:
  1. Deep directory recursion - rsync scans entire tree (fix: use --no-inc-recursive)
  2. Slow metadata operations - stat() calls hang on slow NAS (fix: reduce --timeout)
  3. Network timeouts - TCP connections hang without keepalive (fix: check SSH keepalive)
  4. Large directory listings - reading dir contents hangs (fix: use --max-size filter)
  5. File locking - files in use by other processes (fix: check lsof/fuser)
  6. Permission issues - access denied causes silent hangs (check rsync output above)
```

## Troubleshooting Steps

1. **Check NAS Mount Health**
   ```bash
   mount | grep nas
   df -h /mnt/nas
   ping nas-server-ip
   ```

2. **Check for File Locks**
   ```bash
   lsof /mnt/nas/data/
   fuser -v /mnt/nas/data/
   ```

3. **Test Basic rsync**
   ```bash
   rsync -rtv --timeout=60 --contimeout=30 /mnt/nas/data/test.txt /tmp/
   ```

4. **Monitor rsync Progress**
   - Use `--info=progress2,name` (already enabled)
   - Watch for which file/directory it's stuck on

5. **Check NAS Logs**
   - Check NAS server logs for connection issues
   - Check network connectivity between client and NAS

6. **Reduce Parallelism**
   - If using `--parallel`, try reducing it
   - NAS may not handle multiple connections well

## Why `cp` Works But `rsync` Hangs

`cp` is simpler and doesn't:
- Scan entire directory trees recursively
- Check file metadata (timestamps, permissions) in detail
- Use network protocols that can timeout
- Follow symlinks by default

However, `cp` is slower and doesn't preserve all metadata. The solutions above make `rsync` as reliable as `cp` while keeping its advantages.
