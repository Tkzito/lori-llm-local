#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$HERE")"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[i] Using sandbox: $TMP_DIR"
export ASSISTANT_ROOT="$TMP_DIR"

cd "$TMP_DIR"

echo "[i] fs.write"
python -m assistant_cli.tools_cli fs.write --args-json '{"path":"notas.txt","content":"Primeira linha"}'

echo "[i] fs.read"
python -m assistant_cli.tools_cli fs.read --args-json '{"path":"notas.txt"}'

printf 'alpha\nbeta\nbeta gamma\n' > sample.txt

echo "[i] fs.search"
python -m assistant_cli.tools_cli fs.search --args-json '{"query":"beta"}'

echo 'versao=1.0' > config.ini
echo "[i] edit.replace"
python -m assistant_cli.tools_cli edit.replace --args-json '{"path":"config.ini","find":"1.0","replace":"2.0"}'

echo "[i] git (init repo)"
git init >/dev/null
git config user.email you@example.com
git config user.name you

echo "[i] git.status"
python -m assistant_cli.tools_cli git.status

echo "[i] git.commit (add_all)"
python -m assistant_cli.tools_cli git.commit --args-json '{"message":"Teste","add_all":true}'

echo "[i] git.diff (staged)"
python -m assistant_cli.tools_cli git.diff --args-json '{"staged":true}'

echo "[i] Done."

