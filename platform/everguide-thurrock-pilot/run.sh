#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN=""
for candidate in python3.12 python3.13 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
done
if [[ -z "$PYTHON_BIN" ]]; then echo 'Python 3.11, 3.12 or 3.13 is required.' >&2; exit 1; fi
[[ -x .venv/bin/python ]] || "$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_pilot.py "$@"
