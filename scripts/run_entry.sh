#!/usr/bin/env bash
set -euo pipefail
# Activate virtualenv if present
if [ -f venv/bin/activate ]; then
  . venv/bin/activate
fi
python.exe weinstein_albert_scanner.py "$@"
