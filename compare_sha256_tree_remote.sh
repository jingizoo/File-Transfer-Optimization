#!/usr/bin/env bash
#
# Compare SHA-256 hashes for files in a local source directory vs a remote target directory.
#
# Usage:
#   ./compare_sha256_tree_remote.sh <source_dir> <user@host:/absolute/target_dir>
#
# Notes:
# - Files are matched by *relative path* under <source_dir> (not just basename).
# - Requires passwordless SSH (or SSH agent) for non-interactive operation.
# - Remote host must have either `sha256sum` or `shasum` available.
#
#
# If you accidentally run this via `sh script.sh`, re-exec under bash.
# (Use POSIX [ ] so this works even when started under /bin/sh.)
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

usage() {
  cat <<'EOF'
Compare SHA-256 hashes for a local directory vs a remote directory.

Usage:
  compare_sha256_tree_remote.sh <source_dir> <user@host:/absolute/target_dir>

Example:
  ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst

Logging:
  # Log to a file (in addition to stdout)
  COMPARE_LOG_FILE=compare.log ./compare_sha256_tree_remote.sh /data/src user@host:/data/dst

Faster modes (trade accuracy for speed):
  # Compare only file sizes (very fast, not cryptographic)
  COMPARE_MODE=size ./compare_sha256_tree_remote.sh /data/src user@host:/data/dst

  # Compare sizes + hash of first+last N MiB (fast, still not a full proof)
  COMPARE_MODE=sample COMPARE_SAMPLE_MIB=64 ./compare_sha256_tree_remote.sh /data/src user@host:/data/dst
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

src_dir="$1"
target="$2"

if [[ ! -d "$src_dir" ]]; then
  echo "ERROR: source_dir is not a directory: $src_dir" >&2
  exit 2
fi

# Parse target like user@host:/abs/path (or host:/abs/path)
if [[ "$target" != *:* ]]; then
  echo "ERROR: target must look like user@host:/absolute/path (missing ':'): $target" >&2
  exit 2
fi

remote_spec="${target%%:*}"
remote_root="${target#*:}"

if [[ -z "$remote_spec" || -z "$remote_root" ]]; then
  echo "ERROR: invalid target: $target" >&2
  exit 2
fi

if [[ "$remote_root" != /* ]]; then
  echo "ERROR: remote target path must be absolute (start with '/'): $remote_root" >&2
  exit 2
fi

# Normalize a bit (avoid double slashes later)
src_dir="${src_dir%/}"
remote_root="${remote_root%/}"

# Single-quote a string for safe use in a remote shell command.
sq() {
  local s="$1"
  s=${s//\'/\'\\\'\'}
  printf "'%s'" "$s"
}

LOCAL_HASH_TOOL=""
if command -v sha256sum >/dev/null 2>&1; then
  LOCAL_HASH_TOOL="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  LOCAL_HASH_TOOL="shasum"
else
  echo "ERROR: need sha256sum or shasum on local machine" >&2
  exit 2
fi

SSH_OPTS=(
  -o ConnectTimeout=10
)

batch_mode="${COMPARE_SSH_BATCHMODE:-1}"
if [[ "$batch_mode" == "1" ]]; then
  SSH_OPTS+=(-o BatchMode=yes)
else
  SSH_OPTS+=(-o BatchMode=no)
fi

# `StrictHostKeyChecking=accept-new` is only supported on newer OpenSSH.
ssh_v="$(ssh -V 2>&1 || true)"
strict_host_key="no"
if [[ "$ssh_v" =~ OpenSSH_([0-9]+)\.([0-9]+) ]]; then
  ssh_major="${BASH_REMATCH[1]}"
  ssh_minor="${BASH_REMATCH[2]}"
  if (( ssh_major > 7 || (ssh_major == 7 && ssh_minor >= 6) )); then
    strict_host_key="accept-new"
  fi
fi
SSH_OPTS+=(-o "StrictHostKeyChecking=$strict_host_key")

ssh_test_err="$(ssh "${SSH_OPTS[@]}" "$remote_spec" "true" 2>&1 || true)"
if [[ -n "$ssh_test_err" ]]; then
  # If SSH printed anything and exited non-zero, show it to help debugging.
  if ! ssh "${SSH_OPTS[@]}" "$remote_spec" "true" >/dev/null 2>&1; then
    echo "ERROR: cannot SSH to $remote_spec" >&2
    echo "SSH version: $ssh_v" >&2
    echo "SSH options: ${SSH_OPTS[*]}" >&2
    echo "SSH error:" >&2
    echo "$ssh_test_err" >&2
    echo >&2
    echo "If SSH works manually because it prompts for a password/passphrase, either:" >&2
    echo "  - set up SSH keys (recommended), or" >&2
    echo "  - rerun with interactive SSH: COMPARE_SSH_BATCHMODE=0 ./compare_sha256_tree_remote.sh ..." >&2
    exit 3
  fi
else
  # No stderr output; still ensure the command succeeds.
  if ! ssh "${SSH_OPTS[@]}" "$remote_spec" "true" >/dev/null 2>&1; then
    echo "ERROR: cannot SSH to $remote_spec" >&2
    exit 3
  fi
fi

REMOTE_HASH_TOOL="$(
  ssh "${SSH_OPTS[@]}" "$remote_spec" \
    "if command -v sha256sum >/dev/null 2>&1; then echo sha256sum;
     elif command -v shasum >/dev/null 2>&1; then echo shasum;
     else echo ''; fi"
)"

if [[ -z "$REMOTE_HASH_TOOL" ]]; then
  echo "ERROR: remote host needs sha256sum or shasum" >&2
  exit 3
fi

matched=0
mismatched=0
missing=0
errors=0

log_file="${COMPARE_LOG_FILE:-}"
compare_mode="${COMPARE_MODE:-sha256}"  # sha256 | size | sample
sample_mib="${COMPARE_SAMPLE_MIB:-64}"

case "$compare_mode" in
  sha256|size|sample) ;;
  *)
    echo "ERROR: invalid COMPARE_MODE=$compare_mode (use: sha256|size|sample)" >&2
    exit 2
    ;;
esac

if [[ "$compare_mode" == "sample" ]]; then
  if ! [[ "$sample_mib" =~ ^[0-9]+$ ]] || (( sample_mib <= 0 )); then
    echo "ERROR: invalid COMPARE_SAMPLE_MIB=$sample_mib (must be positive integer)" >&2
    exit 2
  fi
fi

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() {
  if [[ -n "$log_file" ]]; then
    printf '%s %s\n' "$(ts)" "$*" | tee -a "$log_file"
  else
    printf '%s %s\n' "$(ts)" "$*"
  fi
}
err() {
  if [[ -n "$log_file" ]]; then
    printf '%s %s\n' "$(ts)" "$*" | tee -a "$log_file" >&2
  else
    printf '%s %s\n' "$(ts)" "$*" >&2
  fi
}

local_size_bytes() {
  # Prefer GNU stat; fall back to BSD stat.
  local p="$1"
  stat -c '%s' -- "$p" 2>/dev/null || stat -f '%z' -- "$p" 2>/dev/null || echo ""
}

remote_size_bytes() {
  local p="$1"
  ssh "${SSH_OPTS[@]}" "$remote_spec" \
    "stat -c '%s' -- $(sq "$p") 2>/dev/null || stat -f '%z' -- $(sq "$p") 2>/dev/null" 2>/dev/null || true
}

local_sample_hash() {
  local p="$1"
  local bytes="$2"
  local smib="$3"
  local chunk_bytes=$(( smib * 1024 * 1024 ))

  # If file is small-ish, just hash the whole file.
  if (( bytes <= chunk_bytes * 2 )); then
    if [[ "$LOCAL_HASH_TOOL" == "sha256sum" ]]; then
      sha256sum -- "$p" 2>/dev/null | awk '{print $1}'
    else
      shasum -a 256 "$p" 2>/dev/null | awk '{print $1}'
    fi
    return 0
  fi

  local skip_mib=$(( (bytes - chunk_bytes) / 1024 / 1024 ))
  (
    dd if="$p" bs=1M count="$smib" status=none
    dd if="$p" bs=1M skip="$skip_mib" count="$smib" status=none
  ) | sha256sum 2>/dev/null | awk '{print $1}'
}

remote_sample_hash() {
  local p="$1"
  local bytes="$2"
  local smib="$3"
  local chunk_bytes=$(( smib * 1024 * 1024 ))

  if (( bytes <= chunk_bytes * 2 )); then
    if [[ "$REMOTE_HASH_TOOL" == "sha256sum" ]]; then
      ssh "${SSH_OPTS[@]}" "$remote_spec" "sha256sum -- $(sq "$p") 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true
    else
      ssh "${SSH_OPTS[@]}" "$remote_spec" "shasum -a 256 $(sq "$p") 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true
    fi
    return 0
  fi

  local skip_mib=$(( (bytes - chunk_bytes) / 1024 / 1024 ))
  ssh "${SSH_OPTS[@]}" "$remote_spec" \
    "(
       dd if=$(sq "$p") bs=1M count=$smib status=none
       dd if=$(sq "$p") bs=1M skip=$skip_mib count=$smib status=none
     ) | sha256sum 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true
}

log "Comparing mode: $compare_mode"
log "  source:  $src_dir"
log "  target:  $remote_spec:$remote_root"
if [[ -n "$log_file" ]]; then
  log "  log:     $log_file"
fi
if [[ "$compare_mode" == "sample" ]]; then
  log "  sample:  first+last ${sample_mib}MiB"
fi
log ""

tmp_list="$(mktemp -t compare_sha256.XXXXXX)"
cleanup() { rm -f "$tmp_list"; }
trap cleanup EXIT

# Build the file list.
# Default is newline-delimited for broad compatibility (Git-Bash/MSYS can be flaky with NULs).
# If you need full POSIX safety (handles filenames with newlines), set:
#   COMPARE_LIST_MODE=print0
list_mode="${COMPARE_LIST_MODE:-newline}"  # newline | print0
case "$list_mode" in
  newline|print0) ;;
  *)
    echo "ERROR: invalid COMPARE_LIST_MODE=$list_mode (use: newline|print0)" >&2
    exit 2
    ;;
esac

if [[ "$list_mode" == "print0" ]]; then
  find "$src_dir" -type f -print0 >"$tmp_list"
  total="$(tr -cd '\0' <"$tmp_list" | wc -c | tr -d '[:space:]')"
else
  find "$src_dir" -type f -print >"$tmp_list"
  total="$(wc -l <"$tmp_list" | tr -d '[:space:]')"
fi
idx=0

while :; do
  if [[ "$list_mode" == "print0" ]]; then
    IFS= read -r -d '' src_file || break
  else
    IFS= read -r src_file || break
    [[ -n "$src_file" ]] || continue
  fi
  ((idx++)) || true
  rel="${src_file#"$src_dir"/}"
  remote_file="$remote_root/$rel"

  # Print something immediately, before hashing large files.
  log "[$idx/$total] START    $rel"

  # Remote exists?
  if ! ssh "${SSH_OPTS[@]}" "$remote_spec" "test -f $(sq "$remote_file")"; then
    log "[$idx/$total] MISSING  $rel"
    ((missing++)) || true
    continue
  fi

  if [[ "$compare_mode" == "size" || "$compare_mode" == "sample" ]]; then
    lbytes="$(local_size_bytes "$src_file")"
    rbytes="$(remote_size_bytes "$remote_file")"
    if [[ -z "$lbytes" || -z "$rbytes" ]]; then
      err "[$idx/$total] ERROR    $rel  (failed to read size)"
      ((errors++)) || true
      continue
    fi

    if [[ "$lbytes" != "$rbytes" ]]; then
      log "[$idx/$total] MISMATCH $rel  (size local=$lbytes remote=$rbytes)"
      ((mismatched++)) || true
      continue
    fi

    if [[ "$compare_mode" == "size" ]]; then
      log "[$idx/$total] MATCH    $rel  (size=$lbytes)"
      ((matched++)) || true
      continue
    fi
  fi

  if [[ "$compare_mode" == "sample" ]]; then
    # Same size already checked above.
    local_hash="$(local_sample_hash "$src_file" "$lbytes" "$sample_mib" || true)"
    remote_hash="$(remote_sample_hash "$remote_file" "$rbytes" "$sample_mib" || true)"
    if [[ -z "$local_hash" || -z "$remote_hash" ]]; then
      err "[$idx/$total] ERROR    $rel  (failed to compute sample hash)"
      ((errors++)) || true
      continue
    fi

    if [[ "$local_hash" == "$remote_hash" ]]; then
      log "[$idx/$total] MATCH    $rel  (sample-hash)"
      ((matched++)) || true
    else
      log "[$idx/$total] MISMATCH $rel  (sample-hash)"
      log "           local : $local_hash"
      log "           remote: $remote_hash"
      ((mismatched++)) || true
    fi
    continue
  fi

  # Full SHA-256 (reads entire file on both sides)
  if [[ "$LOCAL_HASH_TOOL" == "sha256sum" ]]; then
    local_hash="$(sha256sum -- "$src_file" 2>/dev/null | awk '{print $1}' || true)"
  else
    local_hash="$(shasum -a 256 "$src_file" 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "$local_hash" ]]; then
    err "[$idx/$total] ERROR    $rel  (failed to hash local file)"
    ((errors++)) || true
    continue
  fi

  if [[ "$REMOTE_HASH_TOOL" == "sha256sum" ]]; then
    remote_hash="$(ssh "${SSH_OPTS[@]}" "$remote_spec" "sha256sum -- $(sq "$remote_file") 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true)"
  else
    remote_hash="$(ssh "${SSH_OPTS[@]}" "$remote_spec" "shasum -a 256 $(sq "$remote_file") 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true)"
  fi
  if [[ -z "$remote_hash" ]]; then
    err "[$idx/$total] ERROR    $rel  (failed to hash remote file: $remote_file)"
    ((errors++)) || true
    continue
  fi

  if [[ "$local_hash" == "$remote_hash" ]]; then
    log "[$idx/$total] MATCH    $rel"
    ((matched++)) || true
  else
    log "[$idx/$total] MISMATCH $rel"
    log "           local : $local_hash"
    log "           remote: $remote_hash"
    ((mismatched++)) || true
  fi
done <"$tmp_list"

log ""
log "Summary:"
log "  matched   : $matched"
log "  mismatched: $mismatched"
log "  missing   : $missing"
log "  errors    : $errors"

if (( mismatched > 0 || missing > 0 || errors > 0 )); then
  exit 1
fi
