#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$root"
./scripts/check_public_safe.sh
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --no-git --redact --verbose
else
  echo "scan: gitleaks not installed; check_public_safe.sh only"
fi
