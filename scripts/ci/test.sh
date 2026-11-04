#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
cd "$root"
python -m pytest -q
node --test web/logic.test.js web/widget.test.js
