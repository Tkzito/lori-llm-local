# Lori LLM Local

Lori é uma assistente 100% local para linha de comando e navegador construída sobre modelos servidos pelo Ollama. A stack combina:

- **Backend FastAPI** com WebSocket para streaming do raciocínio do agente.
- **Interface web reativa** (HTML + CSS + JS puro) com histórico agrupado, painel de raciocínio e envio de arquivos de contexto.
- **CLI** integrada ao mesmo núcleo (`assistant_cli`) e um conjunto modular de ferramentas (leitura/escrita de arquivos, Git, busca web, cotações, etc.).

---

## 🆕 Atualizações recentes

- Histórico reorganizado por dia (Hoje, Ontem e nome da semana), exibindo título, horário e prévia de cada conversa.
- Handles laterais (☰ à esquerda e 🧠 à direita) para recolher/reabrir histórico e painel de raciocínio sem ocupar o espaço do chat.
- README revisado para refletir o menu unificado, o fluxo atual da Web UI e o roteiro de evolução.

---

## 🚀 Primeiros passos

### Pré-requisitos

- Python 3.10 ou superior.
- Ollama instalado e em execução (`http://localhost:11434` por padrão).
- Recomendado baixar previamente um modelo, ex.: `ollama pull mistral`.

### Inicialização via menu unificado

```bash
./start.sh
```

O script oferece as opções:

1. Iniciar Lori no terminal (CLI).
2. Iniciar Lori no navegador (Web UI).
3. Verificar/iniciar o Ollama local.
4. Encerrar o Ollama.
5. Iniciar tudo (Ollama + Web UI em segundo plano).
6. Encerrar tudo.
7. Visualizar logs (Ollama, Web UI ou ambos).

O menu:

- Garante a criação/uso do virtualenv `.venv` e instala `requirements.txt` quando necessário.
- Mantém a Web UI disponível em `http://127.0.0.1:8001/`.
- Registra PIDs (`.lori_web.pid`, `.lori_ollama.pid`) e logs (`.lori_web.log`, `.lori_ollama.log`) para fácil inspeção.

### Ver logs rapidamente

```bash
# Log apenas do Ollama
./lori-logs.sh ollama

# Log da Web UI quando está em segundo plano
./lori-logs.sh web

# Ambos em paralelo
./lori-logs.sh ambos
```

### Execução direta (opcional)

```bash
./run.sh       # CLI
./run_web.sh   # Web UI
```

---

## 🖥️ Visão geral da Web UI

A interface é composta por três zonas:

| Zona | Descrição |
| --- | --- |
| **Histórico** (esquerda) | Conversas agrupadas por dia, com título, prévia e horário. Pode ser ocultado pelo botão ☰ e reaberto pelo handle lateral. |
| **Chat** (centro) | Área principal da conversa, com envio `Enter`, indicador de digitação e suporte a anexos. |
| **Raciocínio do agente** (direita) | Mostra pensamentos, chamadas de ferramentas e confirmações. Pode ser recolhido pelo botão 🧠 ou reaberto pelo handle com ícone de cérebro. |

### Anexando arquivos de contexto

- Botão 📎 adiciona arquivos; eles são salvos em `~/lori/uploads`.
- Cada item exibe nome, tamanho e botão **Remover** com feedback visual (spinner) durante operações.
- Botão **Limpar** remove todos os anexos; o contador indica quantos arquivos estão ativos.

### Outros recursos

- Alternância entre tema claro/escuro (ícone ◑).
- Histórico e painel de raciocínio lembram o estado (aberto/recolhido) via `localStorage`.
- Handles laterais permitem abrir painéis rapidamente sem comprometer o espaço do chat.

### Evoluções planejadas

- Automação para detectar pedidos de atualização (“atualize o preço do BTC”) e disparar consultas relevantes automaticamente.
- Heurísticas que utilizam o histórico agrupado para inferir preferências por conversa.

---

## 📁 Estrutura do projeto

```
assistant-cli/
├── assistant_cli/          # Núcleo do agente e ferramentas
│   ├── agent.py            # Loop principal do agente
│   ├── cli.py              # Entrada do CLI
│   ├── tools.py            # Registro de ferramentas/bindings
│   └── config.py           # Diretórios padrão e variáveis de ambiente
├── web/                    # Backend FastAPI (REST + WebSocket)
│   ├── main.py             # Rotas/serviços
│   └── static/             # Front-end (index.html, style.css, app.js)
├── run.sh                  # Inicializador do CLI
├── run_web.sh              # Inicializador da Web UI
├── start.sh                # Menu unificado com bootstrapping
├── requirements.txt        # Dependências Python
└── config.ini.template     # Template opcional
```

---

## ⚙️ Configuração

Principais variáveis em `assistant_cli/config.py`:

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `ASSISTANT_MODEL` | Modelo utilizado via Ollama | `mistral` |
| `OLLAMA_BASE_URL` | Endpoint do Ollama | `http://localhost:11434` |
| `LORI_HOME` | Diretório base (`workspace`, `uploads`, etc.) | `~/lori` |
| `ASSISTANT_ROOT` | Raiz permitida para operações de arquivo | `~/lori/workspace` |
| `ASSISTANT_VERBOSE` | Ativa logs detalhados de ferramentas | `0` |
| `OLLAMA_USE_GPU` | Força uso de GPU (`1`) | auto |

> **Dica GPU:** instale a versão do Ollama com suporte CUDA, exporte `OLLAMA_USE_GPU=1` (ou configure `~/.ollama/config`) e baixe o modelo desejado antes de iniciar o menu.

---

## 🧪 Desenvolvimento e testes

- **Testes:** `pytest`
- **Lint:** `ruff check .`
- Alterações em `web/static` são aplicadas ao recarregar o navegador; o backend pode rodar com `uvicorn --reload`.
- Anexos ficam em `~/lori/uploads` — limpe manualmente se precisar.

---

## 🛠️ Solução de problemas

| Sintoma | Como resolver |
| --- | --- |
| Modelo não responde | Verifique se o Ollama está ativo e se o modelo foi baixado (`ollama list`). |
| Remoção de arquivo falha | Observe o alerta sob o cabeçalho de contexto; ele informa o motivo. |
| Porta ocupada | Execute `./run_web.sh --port 9000` (ou ajuste a variável `WEB_PORT` no `start.sh`). |

---

## 📄 Licença

Projeto distribuído nos termos definidos pelo autor original. Consulte o repositório para diretrizes de uso e contribuição.
