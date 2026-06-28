#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$DIR"
if [ -f venv/bin/activate ]; then
  . venv/bin/activate
fi
python -m weinstein entry "$@"
