#!/usr/bin/env sh

set -eu

WAIT_RETRIES="${OLLAMA_WAIT_RETRIES:-60}"
WAIT_INTERVAL="${OLLAMA_WAIT_INTERVAL:-2}"

if [ -n "${OLLAMA_BASE_URL:-}" ]; then
  TARGET="${OLLAMA_BASE_URL%/}/api/tags"
  echo "[entrypoint] Waiting for Ollama at ${TARGET} ..."
  ATTEMPT=0
  until curl -fsS "${TARGET}" >/dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "${ATTEMPT}" -ge "${WAIT_RETRIES}" ]; then
      echo "[entrypoint] Ollama did not become ready after ${WAIT_RETRIES} attempts."
      exit 1
    fi
    echo "[entrypoint] Ollama not ready (attempt ${ATTEMPT}/${WAIT_RETRIES}). Retrying in ${WAIT_INTERVAL}s..."
    sleep "${WAIT_INTERVAL}"
  done
  echo "[entrypoint] Ollama is ready."
fi

exec uvicorn --app-dir src web.main:app --host 0.0.0.0 --port 8001
