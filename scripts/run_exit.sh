#!/usr/bin/env bash
set -euo pipefail
if [ -f venv/bin/activate ]; then
  . venv/bin/activate
fi
python.exe weinstein_albert_exit_scanner.py "$@"
