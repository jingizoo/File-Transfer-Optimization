# Compare SHA-256 Between Local Source and Remote Target (Directory Tree)

This repo includes `compare_sha256_tree_remote.sh` to compare files under a **local source directory** against files at the **same relative paths** under a **remote target directory** (reachable over SSH).

## Prereqs

- Local: `bash` + (`sha256sum` or `shasum`)
- Remote: (`sha256sum` or `shasum`)
- SSH connectivity to the remote (`user@ip:/absolute/path`)

## Example Commands

### Full SHA-256 (strongest, slowest)

```bash
./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

### Log to a file (still prints to console)

```bash
COMPARE_LOG_FILE=compare.log ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

### Interactive SSH (if your SSH prompts for password/passphrase)

```bash
COMPARE_SSH_BATCHMODE=0 ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

### Fast compare (size only; not cryptographic)

```bash
COMPARE_MODE=size ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

### Faster compare (size + sample hash of first+last N MiB)

Default sample size is 64 MiB:

```bash
COMPARE_MODE=sample ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

Custom sample size (e.g., 256 MiB):

```bash
COMPARE_MODE=sample COMPARE_SAMPLE_MIB=256 ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

## Troubleshooting (no code changes)

### It stops after the first file (e.g. shows `1/256` then exits)

Run these (in order) to identify whether it’s a list/compatibility issue or a real failure.

#### 1) Force the most compatible file-list mode (newline)

```bash
COMPARE_LIST_MODE=newline ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

#### 2) Prove it iterates everything quickly (size-only mode)

```bash
COMPARE_LIST_MODE=newline COMPARE_MODE=size ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

#### 3) Capture logs to a file (so you can see where it stopped)

```bash
COMPARE_LIST_MODE=newline COMPARE_LOG_FILE=run.log ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

#### 4) Trace execution (shows the exact command that caused an exit)

```bash
COMPARE_LIST_MODE=newline bash -x ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
```

If it still exits early, look at the last lines in `run.log` (or the last lines printed in `bash -x`) — it will typically be one of:

- SSH failure mid-run (connectivity, host key, auth)
- Remote `stat`/hash tool failing on a specific path
- A path quoting/escaping issue on the remote shell
