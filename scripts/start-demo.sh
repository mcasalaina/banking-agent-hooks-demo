#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Follow the dependency installation steps in README.md." >&2
  exit 1
fi

pnpm --dir web build
exec .venv/bin/python -u -m banking_demo.server --port "${PORT:-5173}"
