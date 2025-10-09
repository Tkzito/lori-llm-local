#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BOOTSTRAP_SCRIPT="$SCRIPT_DIR/scripts/bootstrap.sh"
RUN_CLI="$SCRIPT_DIR/run.sh"
RUN_WEB="$SCRIPT_DIR/run_web.sh"
OLLAMA_BINARY="$(command -v ollama || true)"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
WEB_HOST="127.0.0.1"
WEB_PORT="8001"
WEB_PID_FILE="$SCRIPT_DIR/.lori_web.pid"
WEB_LOG_FILE="${LORI_WEB_LOG:-$SCRIPT_DIR/.lori_web.log}"
OLLAMA_PID_FILE="$SCRIPT_DIR/.lori_ollama.pid"
OLLAMA_LOG_FILE="${LORI_OLLAMA_LOG:-$SCRIPT_DIR/.lori_ollama.log}"
LOG_SCRIPT="$SCRIPT_DIR/lori-logs.sh"
OLLAMA_HOST="$(python - <<'PY'
from urllib.parse import urlparse
import os
url = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
parsed = urlparse(url)
host = parsed.hostname or 'localhost'
port = parsed.port or (443 if parsed.scheme == 'https' else 11434)
print(f"{host}:{port}")
PY
)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

echo_divider() {
  printf '\n%s\n' "----------------------------------------"
}

web_is_running() {
  if [[ -f "$WEB_PID_FILE" ]]; then
    local pid
    pid=$(cat "$WEB_PID_FILE" 2>/dev/null || true)
    if [[ -n "$pid" && -d "/proc/$pid" ]]; then
      return 0
    fi
  fi
  pgrep -f "uvicorn .*web.main:app" >/dev/null 2>&1
}

web_has_reloader() {
  pgrep -f "watchfiles.*web.main:app" >/dev/null 2>&1
}

print_status() {
  local ollama_status="parado"
  local web_status="parada"

  if ollama_is_running; then
    ollama_status="ativo ($OLLAMA_URL)"
  fi

  if web_is_running; then
    web_status="ativa (http://$WEB_HOST:$WEB_PORT/)"
  fi

  printf '  %-6s %s\n' "Ollama:" "$ollama_status"
  printf '  %-6s %s\n' "Web UI:" "$web_status"
}

start_web_background() {
  if web_is_running; then
    echo "[ok] Web UI já está rodando em http://$WEB_HOST:$WEB_PORT/"
    return 0
  fi

  ensure_bootstrap
  echo "[info] Iniciando Web UI em segundo plano (http://$WEB_HOST:$WEB_PORT/)..."
  nohup "$SCRIPT_DIR/.venv/bin/uvicorn" --app-dir "$SCRIPT_DIR/src" web.main:app \
    --host "$WEB_HOST" --port "$WEB_PORT" >"$WEB_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$WEB_PID_FILE"

  for _ in {1..20}; do
    sleep 0.5
    if curl -sf --connect-timeout 1 --max-time 2 "http://$WEB_HOST:$WEB_PORT" >/dev/null 2>&1; then
      echo "[ok] Web UI disponível em http://$WEB_HOST:$WEB_PORT/"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
  done

  echo "[erro] Não foi possível confirmar a Web UI. Veja $WEB_LOG_FILE para detalhes." >&2
  rm -f "$WEB_PID_FILE"
  return 1
}

stop_web_background() {
  local quiet=0
  if [[ "${1:-}" == "--silent" ]]; then
    quiet=1
    shift || true
  fi

  if web_is_running; then
    local pid
    pid=$(cat "$WEB_PID_FILE" 2>/dev/null || true)
    [[ $quiet -eq 0 ]] && echo "[info] Encerrando Web UI..."
    if [[ -n "$pid" && -d "/proc/$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      pkill -f "uvicorn .*web.main:app" 2>/dev/null || true
    fi
    pkill -f "watchfiles.*web.main:app" 2>/dev/null || true
    rm -f "$WEB_PID_FILE"
    [[ $quiet -eq 0 ]] && echo "[ok] Web UI encerrada."
  else
    [[ $quiet -eq 0 ]] && echo "[info] Web UI já está parada."
    rm -f "$WEB_PID_FILE"
  fi
}

cleanup_orphan_web_instances() {
  local orphan_ports=(8000)
  for port in "${orphan_ports[@]}"; do
    pkill -f "uvicorn .*web.main:app --host 127.0.0.1 --port $port" 2>/dev/null || true
  done
  pkill -f "watchfiles.*web.main:app" 2>/dev/null || true
}

view_logs() {
  if [[ ! -x "$LOG_SCRIPT" ]]; then
    echo "[erro] Script de logs não encontrado em $LOG_SCRIPT."
    echo "       Certifique-se de que 'lori-logs.sh' existe e tem permissão de execução."
    return 1
  fi

  while true; do
    echo_divider
    echo "Visualizar logs (Ctrl+C para sair do acompanhamento)"
    echo "  1) Ollama"
    echo "  2) Web UI"
    echo "  3) Ambos"
    echo "  q) Voltar"
    read -rp "Escolha uma opção: " log_choice
    case "${log_choice,,}" in
      1)
        "$LOG_SCRIPT" ollama || true
        ;;
      2)
        "$LOG_SCRIPT" web || true
        ;;
      3)
        "$LOG_SCRIPT" ambos || true
        ;;
      q|quit|exit)
        break
        ;;
      *)
        echo "Opção inválida."
        ;;
    esac
  done
}

stop_ollama() {
  if ollama_is_running; then
    echo "[info] Encerrando Ollama..."
    local pid=""
    if [[ -f "$OLLAMA_PID_FILE" ]]; then
      pid=$(cat "$OLLAMA_PID_FILE" 2>/dev/null || true)
    fi
    if [[ -n "$pid" && -d "/proc/$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      pkill -TERM -f "ollama serve" 2>/dev/null || true
    fi
    rm -f "$OLLAMA_PID_FILE"
    echo "[ok] Ollama foi encerrado."
  else
    echo "[info] Ollama já está parado."
    rm -f "$OLLAMA_PID_FILE"
  fi
}

ensure_bootstrap() {
  if [[ -x "$BOOTSTRAP_SCRIPT" ]]; then
    "$BOOTSTRAP_SCRIPT"
  else
    # Fallback para compatibilidade com versões anteriores.
    "$SCRIPT_DIR/run.sh" --help >/dev/null 2>&1 || true
  fi
}

ollama_is_running() {
  curl -sf --connect-timeout 2 --max-time 3 "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1
}

start_ollama() {
  if [[ -z "$OLLAMA_BINARY" ]]; then
    echo "[erro] Ollama não encontrado no PATH. Instale ou exporte OLLAMA_BASE_URL." >&2
    return 1
  fi
  echo "[info] Iniciando Ollama…"
  touch "$OLLAMA_LOG_FILE"
  nohup "$OLLAMA_BINARY" serve >"$OLLAMA_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$OLLAMA_PID_FILE"
  # Aguarda alguns segundos para o serviço responder.
  for _ in {1..10}; do
    sleep 0.5
    if ollama_is_running; then
      echo "[ok] Ollama disponível em $OLLAMA_URL"
      return 0
    fi
  done
  echo "[erro] Não foi possível confirmar o Ollama em $OLLAMA_URL." >&2
  if [[ -n "$pid" && -d "/proc/$pid" ]]; then
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$OLLAMA_PID_FILE"
  return 1
}

ensure_ollama() {
  if ollama_is_running; then
    echo "[ok] Ollama já está rodando em $OLLAMA_URL."
    return 0
  fi
  echo "[alerta] Ollama não está respondendo em $OLLAMA_URL."
  read -rp "Deseja iniciar 'ollama serve' agora? [s/N]: " ans
  ans=${ans,,}
  if [[ "$ans" == "s" || "$ans" == "sim" || "$ans" == "y" || "$ans" == "yes" ]]; then
    start_ollama
  else
    echo "[info] Continuando sem iniciar o Ollama."
    rm -f "$OLLAMA_PID_FILE"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------------------

show_menu() {
  echo_divider
  cleanup_orphan_web_instances
  print_status
  echo
  cat <<'MENU'
Menu Lori Assistant
  1) Iniciar Lori no terminal (CLI)
  2) Iniciar Lori no navegador (Web UI)
  3) Verificar/iniciar Ollama
  4) Encerrar Ollama
  5) Iniciar tudo (Ollama + Web UI)
  6) Encerrar tudo (Web UI + Ollama)
  7) Visualizar logs
  q) Sair
MENU
}

while true; do
  show_menu
  read -rp "Escolha uma opção: " choice
  case "${choice,,}" in
    1)
      ensure_bootstrap
      if ensure_ollama; then
        "$RUN_CLI"
      else
        echo "[info] CLI não foi iniciada porque o Ollama não está ativo."
      fi
      ;;
    2)
      ensure_bootstrap
      if ensure_ollama; then
        "$RUN_WEB"
      else
        echo "[info] Web UI interativa não foi iniciada porque o Ollama não está ativo."
      fi
      ;;
    3)
      echo "[info] Verificando Ollama em $OLLAMA_URL..."
      ensure_ollama
      ;;
    4)
      stop_ollama
      ;;
    5)
      ensure_bootstrap
      if ensure_ollama; then
        stop_web_background --silent
        start_web_background
      else
        echo "[info] Ollama não foi iniciado; Web UI não será iniciada."
      fi
      ;;
    6)
      stop_web_background
      stop_ollama
      ;;
    7)
      view_logs
      ;;
    q|quit|exit)
      echo "Até mais!"
      exit 0
      ;;
    *)
      echo "Opção inválida."
      ;;
  esac
  echo_divider
  echo "Status atual:"
  print_status
  read -rp "Pressione Enter para continuar…" _
done
