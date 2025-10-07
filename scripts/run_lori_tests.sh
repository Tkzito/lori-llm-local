#!/usr/bin/env bash
set -euo pipefail

RUNNER="$HOME/workspace/assistant-cli/run.sh"
if [ ! -x "$RUNNER" ]; then
  echo "assistant-cli runner não encontrado: $RUNNER" >&2
  exit 1
fi

SANDBOX="$HOME/workspace/assistant-tests"
mkdir -p "$SANDBOX"
cd "$SANDBOX"
export ASSISTANT_ROOT="$SANDBOX"

export ASSISTANT_VERBOSE=1

echo "[test] criar e ler arquivo"
"$RUNNER" "Crie um arquivo notas.txt com 'linha1' e depois leia o conteúdo."

echo "[test] buscar termo"
printf 'alpha\nbeta\nbeta gamma\n' > sample.txt
"$RUNNER" "Procure por 'beta' no diretório atual e mostre as ocorrências."

echo "[test] edição find/replace"
echo 'versao=1.0' > config.ini
"$RUNNER" "No arquivo config.ini, substitua '1.0' por '2.0' e confirme a mudança."

# Git workflow via tools (init, config, commit, diff)
echo "[test] git flow (init, status, commit, diff)"
"$RUNNER" "Use estritamente as ferramentas. 1) shell.exec {cmd:'git init'}; 2) shell.exec {cmd:'git config user.email you@example.com'}; 3) shell.exec {cmd:'git config user.name you'}; 4) fs.write {path:'repo.txt', content:'linha repo'}; 5) git.status {}; 6) git.commit {message:'Teste via ferramentas', add_all:true}; 7) git.diff {staged:true}. Resuma o resultado."

# Shell exec simple check
echo "[test] shell.exec uname"
"$RUNNER" "Execute shell.exec com cmd 'uname -a' e mostre a saída."

# Web search and get (requires bs4)
echo "[test] web.search + web.get (pode exigir bs4)"
"$RUNNER" "Faça web.search {query:'Open WebUI tools', limit:2}; depois use web.get no primeiro link retornado e resuma o conteúdo extraído. Se a ferramenta web não estiver disponível, informe o erro retornado."

echo "[test] git branches (create/switch/list)"
"$RUNNER" "Use git.branch {action:'create', name:'feature/teste'}; depois git.branch {action:'switch', name:'feature/teste'}; por fim, git.branch {action:'list'}."

echo "[test] format (black) + lint (ruff)"
cat > sample.py << 'PY'
import os,sys
def f(x):
  return 1+  2
PY
"$RUNNER" "Rode fmt.black {paths:['sample.py']}; depois rode lint.ruff {paths:['sample.py']}. Mostre o resultado do lint."

echo "[done] veja os logs [tool_call]/[tool_result] acima"
