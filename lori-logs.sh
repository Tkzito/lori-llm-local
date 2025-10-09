#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OLLAMA_LOG="${LORI_OLLAMA_LOG:-$SCRIPT_DIR/.lori_ollama.log}"
WEB_LOG="${LORI_WEB_LOG:-$SCRIPT_DIR/.lori_web.log}"

usage() {
  cat <<'USAGE'
Uso: lori-logs.sh [arg]

Argumentos:
  ollama   Seguir o log do Ollama (.lori_ollama.log)
  web      Seguir o log da Web UI (.lori_web.log)
  ambos    Seguir os dois logs simultaneamente
  help     Mostrar esta ajuda

Pressione Ctrl+C para sair do modo de monitoramento.
USAGE
}

follow_log() {
  local file="$1"
  local label="$2"
  if [[ ! -f "$file" ]]; then
    echo "[info] Criando arquivo de log vazio: $file"
    touch "$file"
  fi
  echo "[log] Monitorando $label em tempo real."
  echo "[log] Caminho: $file"
  echo "----------------------------------------"
  if [[ ! -s "$file" ]]; then
    echo "[log] (sem entradas ainda; aguardando novas linhas...)"
  fi
  tail -n +1 -F "$file"
}

if [[ $# -eq 0 || "$1" == "help" ]]; then
  usage
  exit 0
fi

case "$1" in
  ollama)
    follow_log "$OLLAMA_LOG" "Ollama"
    ;;
  web)
    follow_log "$WEB_LOG" "Web UI"
    ;;
  ambos|all)
    [[ -f "$OLLAMA_LOG" ]] || touch "$OLLAMA_LOG"
    [[ -f "$WEB_LOG" ]] || touch "$WEB_LOG"
  echo "[log] Monitorando logs de Ollama e Web UI."
  echo "[log] Arquivos:"
    echo "  - $OLLAMA_LOG"
    echo "  - $WEB_LOG"
    echo "----------------------------------------"
    if [[ ! -s "$OLLAMA_LOG" && ! -s "$WEB_LOG" ]]; then
      echo "[log] (sem entradas ainda; aguardando novas linhas...)"
    fi
    tail -n +1 -F "$OLLAMA_LOG" "$WEB_LOG"
    ;;
  *)
    echo "[erro] Argumento desconhecido: $1" >&2
    usage
    exit 1
    ;;
 esac
