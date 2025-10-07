#!/usr/bin/env bash
set -euo pipefail

# Garante que o script seja executado a partir do diretório raiz do projeto
cd "$(dirname "$0")/.."

RUNNER="./run.sh"
if [ ! -x "$RUNNER" ]; then
  echo "Runner não encontrado ou não executável: $RUNNER" >&2
  exit 1
fi

export ASSISTANT_VERBOSE=1

echo -e "\n--- Teste de Busca Web ---"
"$RUNNER" "pesquisa na internet valor do dólar"

echo -e "\n--- Teste de Heurística de Preço ---"
"$RUNNER" "qual é o valor do bitcoin?"

echo -e "\n--- Teste de Leitura de Arquivo ---"
"$RUNNER" "leia o arquivo README.md e resuma em uma frase"