#!/usr/bin/env bash
set -euo pipefail

# Garante que o script seja executado a partir do diretório raiz do projeto
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Garante que o ambiente virtual exista e as dependências estejam instaladas
if [ ! -d .venv ]; then
  echo "[bootstrap] Criando ambiente virtual em .venv..."
  python3 -m venv .venv
fi

if [ -f requirements.txt ]; then
  if [ ! -f .venv/requirements.fingerprint ] || ! cmp -s requirements.txt .venv/requirements.fingerprint; then
    echo "[bootstrap] Instalando/atualizando dependências de requirements.txt..."
    .venv/bin/pip install -r requirements.txt
    cp requirements.txt .venv/requirements.fingerprint
  fi
fi

echo "[web] Iniciando servidor Uvicorn em http://127.0.0.1:8001"
.venv/bin/uvicorn --app-dir src web.main:app --reload --port 8001 "$@"