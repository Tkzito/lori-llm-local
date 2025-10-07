#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d .venv ]; then
  echo "[bootstrap] creating venv at .venv"
  python3 -m venv .venv
fi

PIP=".venv/bin/pip"
if [ -f requirements.txt ]; then
  echo "[bootstrap] installing dependencies"
  "$PIP" install -r requirements.txt
fi

echo "[bootstrap] done. Activate with: source .venv/bin/activate"

