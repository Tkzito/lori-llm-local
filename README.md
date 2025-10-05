Assistant CLI (local Ollama)

Overview
- Terminal-first assistant using your local Ollama.
- Tools: filesystem (read/write/list/search), quick edits, web fetch/search, safe shell.
- Model-agnostic: set model via env var; defaults to `mistral` (you can change).

Install
- Create venv: `python3 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Set env (optional):
  - `export OLLAMA_BASE_URL=http://localhost:11434`
  - `export ASSISTANT_MODEL=mistral`

Run
- One-shot: `python -m assistant_cli.cli "Resuma README.md"`
- Interactive: `python -m assistant_cli.cli`
- With working dir root: `ASSISTANT_ROOT=$PWD python -m assistant_cli.cli`
- Verbose tool logs: `python -m assistant_cli.cli --verbose "Liste arquivos"`

Direct tool calls (for testing)
- List tools: `python -m assistant_cli.tools_cli --list`
- Call a tool directly: `python -m assistant_cli.tools_cli fs.read --args-json '{"path":"README.md"}'`
 - Git branch: `python -m assistant_cli.tools_cli git.branch --args-json '{"action":"list"}'`
 - Format: `python -m assistant_cli.tools_cli fmt.black --args-json '{"paths":["sample.py"]}'`
 - Lint: `python -m assistant_cli.tools_cli lint.ruff --args-json '{"paths":["sample.py"]}'`

Notes
- Web search uses DuckDuckGo HTML (no API key). If you install `duckduckgo_search`, CLI will use it.
- File ops are restricted under `ASSISTANT_ROOT` (default: current working directory or `$HOME`).
- Safe shell only allows a small allowlist of commands (configurable).

Quick Test Plan
- Set a sandbox: `mkdir -p ~/workspace/assistant-tests && cd ~/workspace/assistant-tests && export ASSISTANT_ROOT=$PWD`
- Files:
  - `python -m assistant_cli.tools_cli fs.write --args-json '{"path":"notas.txt","content":"Primeira linha"}'`
  - `python -m assistant_cli.tools_cli fs.read  --args-json '{"path":"notas.txt"}'`
- Search:
  - `printf 'alpha\nbeta\nbeta gamma\n' > sample.txt`
  - `python -m assistant_cli.tools_cli fs.search --args-json '{"query":"beta"}'`
- Edit:
  - `echo 'versao=1.0' > config.ini`
  - `python -m assistant_cli.tools_cli edit.replace --args-json '{"path":"config.ini","find":"1.0","replace":"2.0"}'`
- Git (in a repo):
  - `git init && git config user.email you@example.com && git config user.name you`
  - `python -m assistant_cli.tools_cli git.status`
  - `python -m assistant_cli.tools_cli git.diff --args-json '{"staged":true}'`
  - `python -m assistant_cli.tools_cli git.commit --args-json '{"message":"Teste","add_all":true}'`
  - `python -m assistant_cli.tools_cli git.branch --args-json '{"action":"create","name":"feature/test"}'`
  - `python -m assistant_cli.tools_cli git.branch --args-json '{"action":"switch","name":"feature/test"}'`
  - `python -m assistant_cli.tools_cli git.branch --args-json '{"action":"list"}'`

 - Format & Lint:
  - `printf 'import os,sys\n\n\n' > sample.py`
  - `python -m assistant_cli.tools_cli fmt.black --args-json '{"paths":["sample.py"]}'`
  - `python -m assistant_cli.tools_cli lint.ruff --args-json '{"paths":["sample.py"]}'`
Quick bootstrap
- All-in-one runner auto-creates venv and installs deps on first run:
  - `./run.sh "hello"`
- Or manual bootstrap: `bash scripts/bootstrap.sh`
