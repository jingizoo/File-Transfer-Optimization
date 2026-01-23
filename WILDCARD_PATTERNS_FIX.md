# Wildcard Pattern Fix - All Patterns Now Supported

## Problem Fixed

Previously, patterns like `abc*fgh.txt` and multiple files matching the same pattern weren't working correctly. This has been fixed.

## All Supported Wildcard Patterns

### ✅ Basic Patterns
```bash
# Match any characters
*.txt
*.bin
file*

# Match single character
file?.txt
data?.log

# Match character set
file[0-9].txt
file[abc].log
```

### ✅ Complex Patterns (Now Fixed)
```bash
# Wildcard in middle of filename
abc*fgh.txt
file*backup.log
data*2024*.csv

# Multiple wildcards
*test*.txt
file*_*_backup.bin

# Wildcards in directory names
/path/*/files/*.txt
/data/*/backup/*.log
```

### ✅ Multiple Files Matching Same Pattern
```bash
# All files matching pattern are processed
./fast_xfer.py /source/abc*fgh.txt /destination/ \
  --strategy chunked \
  --chunk-size 10G

# Example: if you have:
#   abc123fgh.txt
#   abc456fgh.txt
#   abc789fgh.txt
# All three will be transferred
```

## Important: Quote Patterns in Shell

**Always quote wildcard patterns** to prevent shell expansion:

```bash
# ✅ CORRECT - Pattern is quoted
./fast_xfer.py "/source/abc*fgh.txt" /destination/

# ❌ WRONG - Shell expands before Python sees it
./fast_xfer.py /source/abc*fgh.txt /destination/
```

### Why Quoting Matters

Without quotes, the shell expands the pattern first:
```bash
# Shell expands: abc*fgh.txt -> abc123fgh.txt abc456fgh.txt
# Python receives: abc123fgh.txt (only first match)
./fast_xfer.py /source/abc*fgh.txt /destination/
```

With quotes, Python receives the pattern and expands it:
```bash
# Shell passes: "abc*fgh.txt" (literal string)
# Python expands: abc123fgh.txt, abc456fgh.txt, abc789fgh.txt
./fast_xfer.py "/source/abc*fgh.txt" /destination/
```

## Examples

### Example 1: Pattern in Middle of Filename
```bash
# Files: abc123fgh.txt, abc456fgh.txt, abc789fgh.txt
./fast_xfer.py "/source/abc*fgh.txt" /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

### Example 2: Multiple Wildcards
```bash
# Files: file_2024_01_backup.bin, file_2024_02_backup.bin
./fast_xfer.py "/source/file*_*_backup.bin" /destination/ \
  --strategy chunked \
  --chunk-size 10G
```

### Example 3: Wildcard in Directory
```bash
# Match files in any subdirectory
./fast_xfer.py "/source/*/data*.txt" /destination/ \
  --strategy chunked \
  --chunk-size 10G
```

### Example 4: Complex Pattern
```bash
# Files: data_2024_01_15.log, data_2024_02_20.log
./fast_xfer.py "/source/data_2024_*_*.log" /destination/ \
  --strategy chunked \
  --chunk-size 5G \
  --remove-source
```

## Testing Your Pattern

Before using in the script, test the pattern:

```bash
# Test with ls (quoted)
ls "/source/abc*fgh.txt"

# If that works, use in script (quoted)
./fast_xfer.py "/source/abc*fgh.txt" /destination/ ...
```

## Output for Multiple Matches

When multiple files match:

```
[wildcard] Detected wildcard pattern: /source/abc*fgh.txt
[wildcard] Expanded '/source/abc*fgh.txt' to 3 path(s):
  - /source/abc123fgh.txt
  - /source/abc456fgh.txt
  - /source/abc789fgh.txt
[wildcard] Processing 3 files/directories...

============================================================
[1/3] Processing: /source/abc123fgh.txt
============================================================
...
```

## Troubleshooting

### Issue: "No files/directories match pattern"
**Solutions:**
1. **Quote the pattern**: `"/source/abc*fgh.txt"` not `/source/abc*fgh.txt`
2. **Test pattern first**: `ls "/source/abc*fgh.txt"`
3. **Check path**: Make sure the directory exists
4. **Check permissions**: Make sure you can read the files

### Issue: Only First File Processed
**Cause**: Pattern not quoted, shell expanded it
**Solution**: Quote the pattern: `"/source/abc*fgh.txt"`

### Issue: Pattern Not Working
**Solutions:**
1. Test with `ls` first: `ls "/source/abc*fgh.txt"`
2. Use absolute path: `/full/path/to/abc*fgh.txt`
3. Check for special characters that need escaping

## Pattern Examples Reference

| Pattern | Matches | Example Files |
|---------|---------|---------------|
| `*.txt` | All .txt files | file.txt, data.txt |
| `file*` | Files starting with "file" | file1.txt, file_backup.bin |
| `*test*` | Files containing "test" | test.txt, mytest.bin |
| `abc*fgh.txt` | Files starting "abc" and ending "fgh.txt" | abc123fgh.txt, abc456fgh.txt |
| `file?.txt` | Single char wildcard | file1.txt, fileA.txt |
| `file[0-9].txt` | Character set | file0.txt, file9.txt |
| `file*_*_backup.bin` | Multiple wildcards | file_2024_01_backup.bin |

## Best Practices

1. **Always quote patterns**: `"/source/abc*fgh.txt"`
2. **Test first**: `ls "/source/abc*fgh.txt"`
3. **Use absolute paths**: `/full/path/to/abc*fgh.txt`
4. **Check output**: Look for `[wildcard] Expanded` message

## Summary

**Fixed Issues:**
- ✅ Patterns like `abc*fgh.txt` now work
- ✅ Multiple files matching same pattern are all processed
- ✅ Better error messages and diagnostics
- ✅ Handles both absolute and relative paths

**Usage:**
```bash
# Always quote the pattern!
./fast_xfer.py "/source/abc*fgh.txt" /destination/ \
  --strategy chunked \
  --chunk-size 10G \
  --remove-source
```

**Key Point**: **Always quote wildcard patterns** to prevent shell expansion!
