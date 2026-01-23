# Domain/CIFS Mount Hang Fix

## Problem: rsync Hangs on Domain Mounts but Works on Corp Mounts

When transferring files from **domain mount points** (CIFS/SMB, Active Directory), rsync can hang even though it works fine on **corp mount points** (typically NFS).

## Root Causes

### 1. **Authentication Overhead**
- **Domain mounts** require Kerberos/Active Directory authentication
- Each file operation may trigger authentication checks
- This adds significant latency compared to NFS mounts
- Authentication can timeout or hang if domain controller is slow/unreachable

### 2. **Different Protocol Characteristics**
- **CIFS/SMB** is more complex than NFS
- More protocol overhead per operation
- Slower metadata operations (stat, readdir)
- More sensitive to network latency

### 3. **Timeout Mismatches**
- Default rsync timeouts are too short for domain mounts
- Domain authentication can take 30-60 seconds
- Directory listings on domain mounts are slower
- Connection establishment is slower

### 4. **Network Path Differences**
- Domain mounts may route through different network paths
- May have higher latency or packet loss
- Firewall rules may affect domain mounts differently

## Solutions Implemented

### 1. **Automatic Mount Type Detection**
The script now automatically detects mount types:
- **NFS mounts**: Standard handling
- **CIFS/SMB mounts**: Extended timeouts
- **Domain mounts**: Extended timeouts + special handling

**Detection output:**
```
[mount] Source detected on CIFS mount: server.example.com -> /mnt/domain
[mount] Domain/CIFS mount detected - using extended timeouts for authentication
[mount] Adjusted timeouts: rsync-timeout=120s, operation-timeout=600s
```

### 2. **Automatic Timeout Adjustment for Domain Mounts**
When a domain/CIFS mount is detected, the script automatically:
- Sets `rsync-timeout` to **120 seconds** (default: 0 = disabled)
- Sets `rsync-operation-timeout` to **600 seconds** (default: 300s)
- Sets `rsync-contimeout` to **60 seconds** (default: same as rsync-timeout)

These extended timeouts account for:
- Slow domain authentication
- Slower metadata operations
- Network latency on domain paths

### 3. **Enhanced Diagnostics**
The script now provides domain-specific diagnostics:

```
[rsync] If this hangs, it's likely stuck on:
        - Directory scanning/listing (large directories)
        - Metadata operations (stat() calls on slow NAS)
        - Network timeout (check NAS connectivity)
        - File permissions (access denied)
        - Domain authentication (CIFS/domain mounts - slower)

[ERROR] rsync failed after 3 attempts.
[diagnostic] Common root causes for rsync hangs on NAS mounts:
  ...
  7. Domain/CIFS mounts - authentication can be slow (fix: use extended timeouts)
     - Domain mounts require Kerberos/AD authentication which adds latency
     - CIFS mounts may need longer timeouts for initial connection
     - Check mount health: mount | grep -i cifs
     - Verify domain credentials: klist (for Kerberos) or smbclient -L //server
```

## Usage

### Automatic (Recommended)
The script automatically detects domain mounts and adjusts timeouts:
```bash
./fast_xfer.py /mnt/domain/data/ /backup/
# Automatically detects CIFS/domain mount and adjusts timeouts
```

### Manual Override
If automatic detection doesn't work, manually set extended timeouts:
```bash
./fast_xfer.py /mnt/domain/data/ /backup/ \
  --rsync-timeout 120 \
  --rsync-operation-timeout 600 \
  --rsync-contimeout 60 \
  --rsync-no-inc-recursive
```

### For Very Slow Domain Mounts
```bash
./fast_xfer.py /mnt/domain/data/ /backup/ \
  --rsync-timeout 180 \
  --rsync-operation-timeout 900 \
  --rsync-contimeout 90 \
  --rsync-no-inc-recursive \
  --rsync-max-retries 5
```

## Troubleshooting Domain Mount Issues

### 1. Check Mount Type
```bash
# Check what type of mount it is
findmnt -n -o FSTYPE,SOURCE,TARGET /mnt/domain

# Or check /proc/mounts
grep domain /proc/mounts
```

### 2. Verify Mount Health
```bash
# Check if mount is responsive
ls -la /mnt/domain/

# Check mount options
mount | grep domain

# Test basic operations
stat /mnt/domain/somefile
```

### 3. Check Domain Authentication
```bash
# For Kerberos
klist
# Should show valid tickets

# For SMB/CIFS
smbclient -L //server -U username
# Should list shares without hanging
```

### 4. Test Network Connectivity
```bash
# Ping domain server
ping domain-server.example.com

# Check DNS resolution
nslookup domain-server.example.com

# Test SMB port
telnet domain-server 445
```

### 5. Check for Mount Issues
```bash
# Check mount statistics
cat /proc/self/mountstats | grep -A 20 domain

# Check for I/O errors
dmesg | grep -i cifs
dmesg | grep -i smb
```

## Common Domain Mount Issues

### Issue: "Permission Denied" Hangs
**Cause**: Domain authentication failing silently
**Fix**: 
- Verify Kerberos tickets: `klist`
- Renew tickets: `kinit username@DOMAIN`
- Check mount credentials

### Issue: Slow Directory Listings
**Cause**: Each directory entry requires authentication check
**Fix**: 
- Use `--rsync-no-inc-recursive`
- Increase `--rsync-timeout`
- Consider mounting with `cache=strict` option

### Issue: Connection Timeouts
**Cause**: Domain controller unreachable or slow
**Fix**:
- Check domain controller connectivity
- Increase `--rsync-contimeout`
- Check firewall rules for SMB ports (445, 139)

### Issue: Intermittent Hangs
**Cause**: Network latency spikes or authentication delays
**Fix**:
- Increase all timeout values
- Use `--rsync-max-retries` for automatic retry
- Check network quality between client and domain server

## Mount Options for Better Performance

When mounting domain shares, consider these options:

```bash
# Mount with better caching and timeouts
mount -t cifs //server/share /mnt/domain \
  -o username=user,domain=DOMAIN,uid=1000,gid=1000,\
  cache=strict,actimeo=60,rsize=1048576,wsize=1048576
```

**Key options:**
- `cache=strict`: Better caching reduces authentication overhead
- `actimeo=60`: Cache attributes for 60 seconds
- `rsize/wsize=1048576`: Larger I/O buffers (1MB)

## Comparison: Corp vs Domain Mounts

| Characteristic | Corp Mount (NFS) | Domain Mount (CIFS) |
|---------------|------------------|---------------------|
| Protocol | NFS v3/v4 | CIFS/SMB 2.0/3.0 |
| Authentication | Simple (IP-based or Kerberos) | Complex (AD/Kerberos per-op) |
| Metadata Speed | Fast | Slower (more auth checks) |
| Default Timeout | 0 (disabled) | 120s (auto-adjusted) |
| Operation Timeout | 300s | 600s (auto-adjusted) |
| Connection Timeout | Same as timeout | 60s (auto-adjusted) |
| Recommended Flags | Standard | `--rsync-no-inc-recursive` |

## Best Practices for Domain Mounts

1. **Always use extended timeouts** (now automatic)
2. **Use `--rsync-no-inc-recursive`** for large directories
3. **Monitor mount health** before large transfers
4. **Verify authentication** (klist, smbclient)
5. **Test with small transfers first**
6. **Use compression** to reduce transfer size: `--rsync-compress`
7. **Transfer in smaller batches** if issues persist

## Example: Working Domain Mount Transfer

```bash
# The script automatically detects and adjusts:
./fast_xfer.py /mnt/cust-domain/data/ /backup/

# Output:
# [mount] Source detected on CIFS mount: cust-server.example.com -> /mnt/cust-domain
# [mount] Domain/CIFS mount detected - using extended timeouts for authentication
# [mount] Adjusted timeouts: rsync-timeout=120s, operation-timeout=600s
# [rsync] Starting transfer...
# ... transfer proceeds with extended timeouts ...
```

The script now automatically handles domain mounts with appropriate timeouts and diagnostics!
