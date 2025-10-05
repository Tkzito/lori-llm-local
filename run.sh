#!/usr/bin/env bash
set -euo pipefail

# Run from this script's directory so Python finds the package
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODEL="${ASSISTANT_MODEL:-mistral}"

# Ensure local venv exists and dependencies are installed
if [ ! -d .venv ]; then
  echo "[bootstrap] creating venv at .venv"
  python3 -m venv .venv
fi

PY=".venv/bin/python"
PIP=".venv/bin/pip"

if [ -f requirements.txt ]; then
  if [ ! -f .venv/requirements.fingerprint ] || ! cmp -s requirements.txt .venv/requirements.fingerprint; then
    echo "[bootstrap] installing/updating dependencies from requirements.txt"
    "$PIP" install -r requirements.txt
    cp requirements.txt .venv/requirements.fingerprint
  fi
fi

"$PY" -m assistant_cli.cli --model "$MODEL" "$@"
