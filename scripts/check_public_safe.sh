#!/bin/sh
# Fail when a tracked or staged path is private, or a file matches a secret pattern.
# gitleaks is not required. Patterns are high-confidence prefixes, not the words
# "api_key" or "password" (those appear in safe source and tests).
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

mode=tracked
if [ "${1:-}" = "--staged" ]; then
  mode=staged
elif [ "${1:-}" != "" ]; then
  echo "usage: scripts/check_public_safe.sh [--staged]" >&2
  exit 2
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "check_public_safe: not a git checkout" >&2
  exit 1
fi

if [ "$mode" = staged ]; then
  files=$(git diff --cached --name-only --diff-filter=ACMR)
else
  files=$(git ls-files)
fi

is_private() {
  rel=$1
  base=$(basename "$rel")
  case "$rel" in
    .env.example)
      return 1
      ;;
    .env|.env.*)
      return 0
      ;;
    content|content/*|data|data/*|.venv|.venv/*|.cursor|.cursor/*)
      return 0
      ;;
    prompts/voice_samples.md|tests/fixtures/qa_answers.json)
      return 0
      ;;
  esac
  case "$base" in
    *.db|*.sqlite|*.sqlite3|*.sqlite-journal|*.db-wal|*.db-shm)
      return 0
      ;;
  esac
  return 1
}

# Self-safe: none of these regexes match their own source lines.
secret_re='sk-[A-Za-z0-9]{8,}|fpk_[A-Za-z0-9]|fpat_[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_[A-Za-z0-9]|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[a-z][a-z0-9+.-]*://[^/[:space:]:]+:[^/[:space:]@]+@|Bearer [A-Za-z0-9._-]{20,}'

fail=0
old_ifs=$IFS
IFS='
'
for rel in $files; do
  [ -n "$rel" ] || continue
  if is_private "$rel"; then
    echo "private path: $rel" >&2
    fail=1
    continue
  fi
  if [ ! -f "$rel" ]; then
    continue
  fi
  if grep -E -n -I -H "$secret_re" "$rel" >&2; then
    echo "secret pattern: $rel" >&2
    fail=1
  fi
done
IFS=$old_ifs

if [ "$fail" -ne 0 ]; then
  echo "check_public_safe: failed ($mode)" >&2
  exit 1
fi
echo "check_public_safe: ok ($mode)"
exit 0
