# Lori LLM Local

Assistente local orientada a desenvolvedores que desejam integrar modelos servidos pelo Ollama em fluxos de terminal ou navegador, mantendo dados sob controle. O repositório consolida o agente Python, a interface web, scripts de automação e orientações de operação.

---

## Visão Geral

- Backend FastAPI com WebSocket para streaming de respostas.
- Interface web reativa com histórico, painel de raciocínio e anexos.
- CLI completa com REPL, histórico local e suporte a streaming.
- Ferramentas modulares em `assistant_cli.tools` reutilizadas entre CLI e Web.
- Scripts de automação para bootstrap, execução de testes, smoke tests e coleta de logs.

---

## Arquitetura

| Componente | Responsabilidade |
| --- | --- |
| `assistant_cli/agent.py` | Loop central do agente, orquestra ferramentas e chamadas ao LLM. |
| `assistant_cli/tools.py` | Operações de arquivos, web scraping, consultas financeiras e utilidades. |
| `assistant_cli/config.py` | Configuração de diretórios, sandbox, variáveis e limites de segurança. |
| `web/main.py` | API FastAPI e servidor do front-end. |
| `start.sh` | Menu interativo que inicializa CLI, Web UI e Ollama. |
| `run.sh` / `run_web.sh` | Execução direta do CLI ou da Web UI. |
| `scripts/*.sh` | Bootstrap de dependências, testes e diagnósticos. |

Todo acesso a arquivos respeita `ASSISTANT_ROOT`, negando rotas presentes na denylist ou fora do workspace configurado.

---

## Pré-requisitos

1. Python 3.10 ou superior.  
2. Ollama instalado e executando em `http://localhost:11434`.  
3. Modelos disponíveis no Ollama (ex.: `ollama pull mistral`).  
4. Dependências opcionais para funcionalidades específicas:  
   - Automação web: `pip install playwright` e `playwright install`.  
   - Consultas SQL sobre CSV: `pip install pandas pandasql`.  
   - Parsing HTML fallback: `pip install beautifulsoup4`.  
   - Buscas web: `pip install duckduckgo-search`.  

Instalação típica:

```bash
python3 -m venv .venv
. .venv/bin/activate            # Linux/macOS (bash/zsh)
.\.venv\Scripts\Activate.ps1    # Windows PowerShell
.\.venv\Scripts\activate.bat    # Windows CMD
pip install -r requirements.txt
```

---

## Configuração

### Diretórios de trabalho

- `LORI_HOME` padrão: `/tmp/lori` (derivado de `tempfile.gettempdir()`).
- Estrutura criada automaticamente:
  - `workspace/` – arquivos do usuário e `lori-notas.txt`.
  - `cache/` – artefatos temporários das ferramentas.
  - `uploads/` – anexos recebidos pela Web UI.
- Sobrescreva com `LORI_HOME=/caminho/customizado` ou edite `config.ini`.

### Variáveis principais

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `ASSISTANT_MODEL` | Modelo usado no Ollama | `mistral` |
| `OLLAMA_BASE_URL` | Endpoint do Ollama | `http://localhost:11434` |
| `LORI_HOME` | Raiz para workspace/cache/uploads | `/tmp/lori` |
| `ASSISTANT_ROOT` | Diretório permitido para operações de arquivo | `/tmp/lori/workspace` |
| `ASSISTANT_VERBOSE` | Exibe chamadas de ferramenta no terminal | `0` |
| `ASSISTANT_GLOBAL_READ` | Habilita leitura global (exceto denylist) | `0` |
| `ASSISTANT_GLOBAL_WRITE` | Habilita escrita global | `0` |
| `ASSISTANT_TIMEOUT_SECS` | Timeout padrão de ferramentas | `60` |

### Template `config.ini`

Crie uma configuração persistente copiando o template:

```bash
cp config.ini.template config.ini
```

Campos principais:

```
[assistant]
model = mistral
base_url = http://localhost:11434
root_dir = /tmp/lori
verbose = false
```

---

## Fluxos de Uso

### Menu unificado (`start.sh`)

```bash
./start.sh
```

Recursos do menu:

- Inicializa CLI interativa ou Web UI.
- Verifica e, se necessário, inicia o Ollama.
- Inicia Web UI em segundo plano com logging gerenciado.
- Encerra serviços e exibe logs (`.lori_web.log`, `.lori_ollama.log`).

O script garante que `.venv` exista, instala dependências e valida conectividade com o Ollama antes de executar componentes.

### CLI

```bash
./run.sh                   # inicia REPL
./run.sh --history         # mostra histórico recente
./run.sh "pergunta única"  # modo one-shot
```

### Web UI

```bash
./run_web.sh --port 8001
```

Interface disponível em `http://127.0.0.1:8001`. Destaques:

- Histórico agrupado por dia com título e prévia.
- Painel de raciocínio exibindo chamadas de ferramenta.
- Upload de anexos persistidos em `$(LORI_HOME)/uploads`.
- Alternância de tema e handles laterais para abrir/fechar painéis.

### Logs

```bash
./lori-logs.sh ollama
./lori-logs.sh web
./lori-logs.sh ambos
```

Os scripts leem os artefatos gerados pelo menu, úteis para diagnosticar sessões de longo prazo.

---

## Interface Web

A UI é dividida em três colunas principais (Histórico, Chat, Raciocínio). Cada painel pode ser recolhido via handles laterais; estados de exibição são persistidos em `localStorage`. O upload suporta múltiplos arquivos com remoção individual e limpeza geral.

---

## Desenvolvimento

### Testes e qualidade

```bash
pytest
ruff check .
```

Use `scripts/run_tests.sh` para rodar testes automatizados e `scripts/smoke.sh` para verificações rápidas. Ajuste a suíte conforme adicionar ferramentas ou integrações.

### Estrutura do código

- `assistant_cli/tools.py` registra ferramentas consumidas pelo agente; cada função recebe um `dict` e retorna dados serializáveis.
- `assistant_cli/tools_cli.py` oferece linha de comando para testar ferramentas isoladamente.
- `assistant_cli/heuristic_processor.py` concentra heurísticas aplicadas às respostas.
- `src/` replica o pacote para instalação (`pip install .`).

### Adicionando ferramentas

1. Implemente a função em `assistant_cli/tools.py`.
2. Registre a função no dicionário `TOOLS`.
3. Documente argumentos e retorno no docstring.
4. Adicione testes em `assistant_cli/test_tools.py`.

### Integração com Ollama

- Certifique-se de que `ollama serve` esteja ativo antes de iniciar CLI ou Web UI.
- Baixe modelos necessários (`ollama pull <modelo>`).
- Para GPU, exporte `OLLAMA_USE_GPU=1` ou configure `~/.ollama/config`.

---

## Administração

- **Limpeza de temporários**: `/tmp/lori` é volátil; redirecione `LORI_HOME` se precisar preservar dados entre reinicializações.
- **Backups**: mantenha `config.ini` e scripts customizados versionados no Git.
- **Dependências**: após atualizar `requirements.txt`, rode `pip install -r requirements.txt` dentro da `.venv`.
- **Logs antigos**: remova `.lori_*.log` e `.lori_*.pid` ao encerrar sessões prolongadas.
- **Homologação**: utilize `scripts/run_lori_tests.sh` antes de releases para validar integrações principais.

---

## Solução de Problemas

| Sintoma | Diagnóstico provável | Sugestão |
| --- | --- | --- |
| CLI informa ausência de histórico | Arquivo `history-*.jsonl` não criado | Execute uma sessão ou verifique permissões em `~/.local/share/assistant_cli`. |
| Web UI não responde | Porta ocupada ou serviço parado | Consulte `./lori-logs.sh web` e reinicie via `./start.sh`. |
| Ferramenta de scraping falha | `playwright` ou browser não instalado | Instale `playwright` e execute `playwright install`. |
| Acesso negado a arquivo | Sandbox bloqueou caminho | Ajuste `ASSISTANT_ROOT`, `ASSISTANT_READONLY_DIRS` ou exporte `ASSISTANT_GLOBAL_READ=1`. |
| Resposta vazia do modelo | Modelo não carregado no Ollama | Cheque `ollama list`, carregue o modelo e reinicie o serviço. |

---

## Contribuição

Relate issues ou proponha mudanças via pull requests. Antes de enviar:

- Atualize a documentação se a funcionalidade pública mudar.
- Garanta que testes (`pytest`) e lint (`ruff`) executem sem falhas.
- Inclua exemplos de uso ou notas de migração quando necessário.

Consulte o [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo completo e expectativas de revisão.

---

## Docker

`docker-compose.yml` define os serviços `ollama` (modelos) e `lori` (web/CLI). Um único comando sobe todo o ambiente com dados persistentes.

### Build e execução

```bash
docker compose build
docker compose up -d
```

- Web UI: `http://localhost:8001`
- API do Ollama: `http://localhost:11434`

Os volumes `lori_data` e `ollama_data` preservam workspace e modelos em `/data/lori` e `/root/.ollama`. O serviço do Ollama baixa automaticamente o modelo definido em `OLLAMA_DEFAULT_MODEL` (padrão: `mistral`) quando o stack sobe.

### Variáveis úteis

| Variável | Descrição | Padrão (docker-compose) |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | Endpoint usado pelo agente para o modelo | `http://ollama:11434` |
| `LORI_HOME` | Diretório raiz de dados da Lori | `/data/lori` |
| `ASSISTANT_ROOT` | Workspace padrão | `/data/lori/workspace` |
| `ASSISTANT_VERBOSE` | Verbose das ferramentas | `0` |

### CLI dentro do container

```bash
docker compose run --rm lori python -m assistant_cli.cli --history
docker compose run --rm lori python -m assistant_cli.cli "Olá, Lori!"
```

### GPU e ajustes

- Para GPUs NVIDIA, adicione `--gpus=all` ao serviço `ollama` (ou a configuração equivalente no Compose).
- Personalize portas/volumes direto em `docker-compose.yml`.
- Utilize `docker compose logs -f` para acompanhar a saída dos serviços.

---

## Licença

Distribuído conforme termos definidos pelo autor. Consulte o repositório original para detalhes sobre uso, distribuição e contribuições.
