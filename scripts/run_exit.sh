#!/usr/bin/env bash
set -euo pipefail
# Change to project root (parent of this scripts folder)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$DIR"
if [ -f venv/bin/activate ]; then
  . venv/bin/activate
fi
python weinstein_albert_exit_scanner.py "$@"
