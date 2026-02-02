# Transfer a Date Range of Files (Using `--include-from`)

This repo’s `fast-xfer` supports **directory transfers** that copy only a selected list of files via:

- `--include-from <file>` → implemented with `rsync --files-from`

This is the easiest way to transfer files in a **date range** (between two timestamps), because `fast-xfer` does **not** allow using `--before-date` and `--after-date` together.

## 1) Generate an include list for a date range (GNU/Linux)

Set your source/destination and date range:

```bash
SRC=/data/src
DST='user@10.0.0.15:/data/dst'

# Keep files with mtime in (AFTER, BEFORE]
AFTER='2026-01-01'
BEFORE='2026-02-01'
```

Generate an include list:

```bash
tmpdir=$(mktemp -d)
touch -d "$AFTER"  "$tmpdir/after"
touch -d "$BEFORE" "$tmpdir/before"

find "$SRC" -type f -newer "$tmpdir/after" ! -newer "$tmpdir/before" -printf '%P\n' > "$tmpdir/include.txt"
```

## 2) Run `fast-xfer` using the include list

```bash
fast-xfer "$SRC/" "$DST/" --include-from "$tmpdir/include.txt"
```

### Notes

- The include list must contain **paths relative to `SRC`**, one per line.
- Empty lines and lines starting with `#` are ignored.
- `fast-xfer` normalizes common list formats like `./path` or `/path` automatically.
- `--include-from` is **mutually exclusive** with `--before-date` / `--after-date`.

## Common add-ons

### Skip permission denied and keep going + write skipped log

```bash
fast-xfer "$SRC/" "$DST/" \
  --include-from "$tmpdir/include.txt" \
  --skip-permission-denied \
  --skipped-log-file skipped.log
```

### Exclude patterns while using include-from

```bash
fast-xfer "$SRC/" "$DST/" \
  --include-from "$tmpdir/include.txt" \
  --exclude '*.tmp' \
  --exclude 'cache/'
```
