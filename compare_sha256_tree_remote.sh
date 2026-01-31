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
set -euo pipefail

usage() {
  cat <<'EOF'
Compare SHA-256 hashes for a local directory vs a remote directory.

Usage:
  compare_sha256_tree_remote.sh <source_dir> <user@host:/absolute/target_dir>

Example:
  ./compare_sha256_tree_remote.sh /data/src user@10.0.0.15:/data/dst
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

echo "Comparing SHA-256"
echo "  source:  $src_dir"
echo "  target:  $remote_spec:$remote_root"
echo

while IFS= read -r -d '' src_file; do
  rel="${src_file#"$src_dir"/}"
  remote_file="$remote_root/$rel"

  # Local hash
  if [[ "$LOCAL_HASH_TOOL" == "sha256sum" ]]; then
    local_out="$(sha256sum -- "$src_file" 2>/dev/null || true)"
  else
    local_out="$(shasum -a 256 "$src_file" 2>/dev/null || true)"
  fi
  local_hash="${local_out%% *}"
  if [[ -z "$local_hash" ]]; then
    echo "ERROR  $rel  (failed to hash local file)" >&2
    ((errors++)) || true
    continue
  fi

  # Remote exists?
  if ! ssh "${SSH_OPTS[@]}" "$remote_spec" "test -f $(sq "$remote_file")"; then
    echo "MISSING $rel"
    ((missing++)) || true
    continue
  fi

  # Remote hash
  if [[ "$REMOTE_HASH_TOOL" == "sha256sum" ]]; then
    remote_out="$(ssh "${SSH_OPTS[@]}" "$remote_spec" "sha256sum -- $(sq "$remote_file")" 2>/dev/null || true)"
  else
    remote_out="$(ssh "${SSH_OPTS[@]}" "$remote_spec" "shasum -a 256 $(sq "$remote_file")" 2>/dev/null || true)"
  fi
  remote_hash="${remote_out%% *}"
  if [[ -z "$remote_hash" ]]; then
    echo "ERROR  $rel  (failed to hash remote file: $remote_file)" >&2
    ((errors++)) || true
    continue
  fi

  if [[ "$local_hash" == "$remote_hash" ]]; then
    echo "MATCH   $rel"
    ((matched++)) || true
  else
    echo "MISMATCH $rel"
    echo "  local : $local_hash"
    echo "  remote: $remote_hash"
    ((mismatched++)) || true
  fi
done < <(find "$src_dir" -type f -print0)

echo
echo "Summary:"
echo "  matched   : $matched"
echo "  mismatched: $mismatched"
echo "  missing   : $missing"
echo "  errors    : $errors"

if (( mismatched > 0 || missing > 0 || errors > 0 )); then
  exit 1
fi
