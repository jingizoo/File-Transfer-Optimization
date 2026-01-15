# Test Commands for fast-xfer

## Step 1: Verify Installation

```bash
# Check Python version (needs 3.6+)
python3 --version

# Check if Python zstandard is installed
python3 -c "import zstandard; print('✓ Python zstandard OK')"

# Check if rsync exists (for remote transfers)
which rsync || echo "rsync not found"

# Check if ssh exists (for remote transfers)
which ssh || echo "ssh not found"

# Test fast-xfer help
python3 fast_xfer.py --help
```

## Step 2: Create Test Files

```bash
# Create a test text file (compressible)
echo "This is a test file for compression. " | head -c 100M > /tmp/test_file.txt
# OR create a small test file
echo "Hello World! This is a test file." > /tmp/test_small.txt

# Check file size
ls -lh /tmp/test_file.txt
```

## Step 3: Test Commands

### Test 1: Local Transfer with Python zstd Compression (No Sudo Needed!)

```bash
# Transfer with Python zstd compression (no CLI tools needed)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_small_copy.txt \
  --strategy compress \
  --compressor zstd \
  --compression-level 3

# Verify the file was transferred
ls -lh /tmp/test_small_copy.txt
```

### Test 2: Local Transfer - Auto Strategy

```bash
# Let the tool decide (auto mode)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_small_auto.txt \
  --strategy auto \
  --compressor zstd

# Check result
ls -lh /tmp/test_small_auto.txt
```

### Test 3: Local Transfer - Direct (No Compression)

```bash
# Simple direct copy (fastest for incompressible files)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_small_direct.txt \
  --strategy direct

# Verify
diff /tmp/test_small.txt /tmp/test_small_direct.txt && echo "Files match!"
```

### Test 4: Remote Transfer with Python zstd (If you have rsync/ssh)

```bash
# Replace with your actual user@host and path
python3 fast_xfer.py /tmp/test_small.txt user@10.0.0.15:/tmp/test_small.txt \
  --strategy compress \
  --compressor zstd \
  --compression-level 3

# Verify on remote (if you have access)
ssh user@10.0.0.15 "ls -lh /tmp/test_small.txt"
```

### Test 5: Directory Transfer (Local)

```bash
# Create test directory
mkdir -p /tmp/test_dir
echo "file1" > /tmp/test_dir/file1.txt
echo "file2" > /tmp/test_dir/file2.txt
mkdir -p /tmp/test_dir/subdir
echo "file3" > /tmp/test_dir/subdir/file3.txt

# Transfer directory
python3 fast_xfer.py /tmp/test_dir/ /tmp/test_dir_copy/

# Verify
ls -R /tmp/test_dir_copy/
```

### Test 6: Compression Estimation Test

```bash
# Test if compression estimation works
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_estimate.txt \
  --strategy auto \
  --compressor zstd \
  --auto-sample-mib 1

# Should show compression ratio estimation
```

### Test 7: Keep Compressed (Don't Decompress)

```bash
# Compress and keep compressed file
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_compressed.zst \
  --strategy compress \
  --compressor zstd \
  --compression-level 3 \
  --keep-compressed

# Check compressed file exists
ls -lh /tmp/test_compressed.zst

# Decompress manually to verify
python3 -c "
import zstandard as zstd
with open('/tmp/test_compressed.zst', 'rb') as f_in, open('/tmp/test_decompressed.txt', 'wb') as f_out:
    zstd.ZstdDecompressor().copy_stream(f_in, f_out)
"
diff /tmp/test_small.txt /tmp/test_decompressed.txt && echo "Decompression OK!"
```

## Quick Test Script

Save this as `test_fast_xfer.sh`:

```bash
#!/bin/bash
set -e

echo "=== Testing fast-xfer ==="
echo ""

# Check Python zstandard
echo "1. Checking Python zstandard..."
python3 -c "import zstandard; print('   ✓ Python zstandard OK')" || {
    echo "   ✗ Python zstandard not found"
    echo "   Install with: pip3 install --user zstandard"
    exit 1
}

# Create test file
echo "2. Creating test file..."
echo "This is a test file for fast-xfer compression testing." > /tmp/fast_xfer_test.txt
for i in {1..1000}; do
    echo "Line $i: This is test data for compression." >> /tmp/fast_xfer_test.txt
done
echo "   ✓ Created /tmp/fast_xfer_test.txt ($(wc -c < /tmp/fast_xfer_test.txt) bytes)"

# Test local transfer with compression
echo "3. Testing local transfer with Python zstd compression..."
python3 fast_xfer.py /tmp/fast_xfer_test.txt /tmp/fast_xfer_test_copy.txt \
  --strategy compress \
  --compressor zstd \
  --compression-level 3

# Verify
if [ -f /tmp/fast_xfer_test_copy.txt ]; then
    if diff -q /tmp/fast_xfer_test.txt /tmp/fast_xfer_test_copy.txt > /dev/null; then
        echo "   ✓ Transfer successful, files match!"
    else
        echo "   ✗ Files don't match!"
        exit 1
    fi
else
    echo "   ✗ Output file not found!"
    exit 1
fi

# Test auto strategy
echo "4. Testing auto strategy..."
python3 fast_xfer.py /tmp/fast_xfer_test.txt /tmp/fast_xfer_test_auto.txt \
  --strategy auto \
  --compressor zstd

if [ -f /tmp/fast_xfer_test_auto.txt ]; then
    echo "   ✓ Auto strategy worked!"
else
    echo "   ✗ Auto strategy failed!"
    exit 1
fi

# Cleanup
echo "5. Cleaning up..."
rm -f /tmp/fast_xfer_test*.txt
echo "   ✓ Cleanup done"

echo ""
echo "=== All tests passed! ==="
```

Make it executable and run:
```bash
chmod +x test_fast_xfer.sh
./test_fast_xfer.sh
```

## Minimal Test (One Command)

```bash
# Create a small test file and transfer it
echo "Test file content" > /tmp/test.txt && \
python3 fast_xfer.py /tmp/test.txt /tmp/test_copy.txt \
  --strategy compress \
  --compressor zstd && \
diff /tmp/test.txt /tmp/test_copy.txt && \
echo "✓ Test passed!"
```

## Test with Different Compression Levels

```bash
# Test level 1 (fastest)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_l1.txt \
  --strategy compress --compressor zstd --compression-level 1

# Test level 3 (balanced)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_l3.txt \
  --strategy compress --compressor zstd --compression-level 3

# Test level 19 (best compression, slowest)
python3 fast_xfer.py /tmp/test_small.txt /tmp/test_l19.txt \
  --strategy compress --compressor zstd --compression-level 19
```

## Verify Python zstd is Being Used

The tool will automatically use Python zstandard if installed. You'll see messages like:
```
[compress] Using Python zstandard library with 4 threads...
```

If you see errors about `zstd` command not found, it means Python zstandard isn't installed. Install it with:
```bash
pip3 install --user zstandard
```
