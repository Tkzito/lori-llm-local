#!/usr/bin/env bash
set -euo pipefail

# Garante que o script seja executado a partir do diretório raiz do projeto
cd "$(dirname "$0")/.."

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Criando ambiente virtual em $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Instalando/atualizando dependências..."
pip install -r requirements.txt

if [[ "${1:-}" == "playwright" ]]; then
  echo "Instalando Playwright e navegador..."
  pip install playwright
  playwright install chromium
fi

echo "Executando testes unitários..."
python -m unittest -v assistant_cli/test_tools.py assistant_cli/test_agent.py
echo "Testes concluídos."