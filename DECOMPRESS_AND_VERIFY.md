# Decompression Commands and Verification Guide

## Decompression Commands

### For **zstd** compressed files (`.zst` extension)

**Fast parallel decompression (recommended):**
```bash
# Option 1: Use unzstd (if available, often faster)
unzstd -T0 --fast -f /path/to/file.zst

# Option 2: Use zstd -d with parallel threads
zstd -d -T0 --fast -f /path/to/file.zst

# Option 3: Basic decompression
zstd -d -f /path/to/file.zst
```

**Explanation:**
- `-T0` = Use all CPU cores (auto-detect)
- `--fast` = Fast decompression mode (faster than default)
- `-f` = Force overwrite if output exists
- `-d` = Decompress mode

**Output:** Creates `/path/to/file` (removes `.zst` extension)

---

### For **pigz/gzip** compressed files (`.gz` extension)

**Fast parallel decompression (recommended):**
```bash
# Option 1: Use unpigz (if available, parallel)
unpigz -p 0 -f /path/to/file.gz

# Option 2: Use pigz -d with parallel threads
pigz -d -p 0 -f /path/to/file.gz

# Option 3: Standard gunzip
gunzip -f /path/to/file.gz

# Option 4: Basic gzip
gzip -d -f /path/to/file.gz
```

**Explanation:**
- `-p 0` = Use all CPU cores (auto-detect)
- `-f` = Force overwrite if output exists
- `-d` = Decompress mode

**Output:** Creates `/path/to/file` (removes `.gz` extension)

---

## Verification Methods

### Method 1: Use Built-in Verification (Recommended)

Add `--verify-sha256` to your transfer command:

```bash
fast-xfer /source/file /dest/file \
  --strategy chunked \
  --compress-chunks \
  --keep-compressed \
  --verify-sha256
```

This will:
- Compute SHA256 checksum of source file
- Compute SHA256 checksum of destination file (after decompression)
- Compare them and report if they match
- **Note:** This reads the entire file on both ends, so it's slow for huge files

---

### Method 2: Manual Verification After Decompression

#### Step 1: Decompress the file
```bash
# For zstd
zstd -d -T0 --fast -f /dest/file.zst

# For pigz/gzip
unpigz -p 0 -f /dest/file.gz
```

#### Step 2: Compare file sizes
```bash
# Check source size
ls -lh /source/file

# Check destination size (after decompression)
ls -lh /dest/file

# They should match exactly
```

#### Step 3: Compare checksums (most reliable)
```bash
# On source machine
sha256sum /source/file

# On destination machine (after decompression)
sha256sum /dest/file

# Compare the checksums - they should be identical
```

#### Step 4: Test decompression integrity
```bash
# For zstd: Test decompression without extracting
zstd -t /dest/file.zst

# For gzip: Test decompression without extracting
gunzip -t /dest/file.gz
# or
gzip -t /dest/file.gz
```

---

### Method 3: Verify Compressed File Integrity

**Before decompressing, verify the compressed file is valid:**

```bash
# For zstd
zstd -t /dest/file.zst

# For gzip/pigz
gunzip -t /dest/file.gz
```

**If the test passes:** The compressed file is valid and can be decompressed.

**If the test fails:** The compressed file is corrupted - re-transfer it.

---

### Method 4: Compare File Contents (for text files)

```bash
# For small text files, you can use diff
diff /source/file /dest/file

# For binary files, use cmp
cmp /source/file /dest/file
```

---

## Complete Verification Workflow

### Example: Verify a zstd compressed file

```bash
# 1. Transfer with verification
fast-xfer /source/myfile.dat /dest/myfile.dat \
  --strategy chunked \
  --compress-chunks \
  --compressor zstd \
  --keep-compressed \
  --verify-sha256

# 2. Verify compressed file integrity
zstd -t /dest/myfile.dat.zst

# 3. Decompress
zstd -d -T0 --fast -f /dest/myfile.dat.zst

# 4. Verify decompressed file size
ls -lh /source/myfile.dat /dest/myfile.dat

# 5. Compare checksums
sha256sum /source/myfile.dat
sha256sum /dest/myfile.dat
```

### Example: Verify a pigz compressed file

```bash
# 1. Transfer with verification
fast-xfer /source/myfile.dat /dest/myfile.dat \
  --strategy chunked \
  --compress-chunks \
  --compressor pigz \
  --keep-compressed \
  --verify-sha256

# 2. Verify compressed file integrity
gunzip -t /dest/myfile.dat.gz

# 3. Decompress
unpigz -p 0 -f /dest/myfile.dat.gz

# 4. Verify decompressed file size
ls -lh /source/myfile.dat /dest/myfile.dat

# 5. Compare checksums
sha256sum /source/myfile.dat
sha256sum /dest/myfile.dat
```

---

## Quick Reference

| Compressor | Extension | Decompress Command | Test Integrity |
|------------|-----------|-------------------|----------------|
| **zstd** | `.zst` | `zstd -d -T0 --fast -f file.zst` | `zstd -t file.zst` |
| **pigz** | `.gz` | `unpigz -p 0 -f file.gz` | `gunzip -t file.gz` |
| **gzip** | `.gz` | `gunzip -f file.gz` | `gunzip -t file.gz` |

---

## Troubleshooting

### "zstd: error 72 : Frame checksum mismatch"
- **Cause:** Compressed file is corrupted
- **Solution:** Re-transfer the file

### "gzip: file.gz: unexpected end of file"
- **Cause:** Compressed file is incomplete or corrupted
- **Solution:** Re-transfer the file

### "Size mismatch after assembly"
- **Cause:** Chunks were not joined correctly
- **Solution:** Check logs for errors, re-transfer with `--verify-sha256`

### Checksums don't match
- **Cause:** File corruption during transfer or decompression
- **Solution:** 
  1. Verify compressed file: `zstd -t file.zst` or `gunzip -t file.gz`
  2. If compressed file is valid, try decompressing again
  3. If still mismatched, re-transfer the file

---

## Best Practices

1. **Always use `--verify-sha256`** for critical transfers (adds ~10-20% time but ensures integrity)
2. **Test compressed file** before decompressing: `zstd -t file.zst`
3. **Use parallel decompression** for large files: `-T0` for zstd, `-p 0` for pigz
4. **Keep compressed file** until verification is complete (use `--keep-compressed`)
5. **Compare checksums** after decompression for final verification
