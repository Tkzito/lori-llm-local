# Lori LLM Local

Lori é uma assistente local para linha de comando e navegador construída sobre modelos servidos pelo Ollama. O projeto oferece:

- **Backend FastAPI** com WebSocket para streaming de respostas do agente.
- **Interface web reativa** com histórico, painel de raciocínio, upload de arquivos de contexto e modo claro/escuro.
- **Ferramentas modulares** acessíveis via `assistant_cli.tools.*`, reaproveitadas tanto pelo web app quanto pelo CLI.

---

## 🆕 Atualizações recentes

- Histórico agrupado por dia, com título, horário e prévia de cada conversa.
- Handles laterais (☰ e 🧠) reabrem histórico e painel de raciocínio sem reduzir a área do chat.
- README e menu unificado revisados para refletir o fluxo atual da Web UI.

## 🚀 Primeiros passos

### Pré-requisitos

- Python 3.10 ou superior.
- Ollama instalado e executando (padrão em `http://localhost:11434`).
- Recomendado: modelos como `mistral` importados no Ollama (`ollama run mistral`).

### Menu unificado

Utilize o menu principal para escolher como interagir com a Lori:

```bash
./start.sh
```

O script cuida de:

1. Iniciar Lori no terminal (CLI)
2. Iniciar Lori no navegador (Web UI)
3. Verificar/iniciar o serviço Ollama
4. Encerrar o Ollama
5. Iniciar tudo (Ollama + Web UI em segundo plano)
6. Encerrar tudo (Web UI + Ollama)
7. Visualizar logs (Ollama, Web UI ou ambos)

O menu mostra o status atual de cada componente e mantém a Web UI sempre em `http://127.0.0.1:8001/`. Quando iniciada em segundo plano, os logs ficam em `.lori_web.log` e o PID em `.lori_web.pid`.

A cada ação, o script garante que o virtualenv `.venv` exista, instala dependências de `requirements.txt` quando necessário e verifica se o Ollama responde (perguntando se deve inicializá-lo caso esteja parado).

### Ver logs em tempo real

Utilize o script auxiliar `lori-logs.sh` para acompanhar os logs capturados pelo menu:

```bash
# Log do Ollama
./lori-logs.sh ollama

# Log da Web UI em background
./lori-logs.sh web

# Ambos os logs em uma única saída
./lori-logs.sh ambos
```

Os arquivos correspondentes são `.lori_ollama.log` e `.lori_web.log`; os PIDs ficam registrados em `.lori_ollama.pid` e `.lori_web.pid`.

### Execução direta (opcional)

Se preferir chamar os modos manualmente, os scripts originais continuam disponíveis:

```bash
./run.sh       # CLI
./run_web.sh   # interface web
```

---

## 🖥️ Visão geral da interface web

A interface é dividida em três áreas principais:

| Zona | Descrição |
| --- | --- |
| **Histórico** (coluna esquerda) | Conversas agrupadas por dia (Hoje, Ontem, dias da semana, etc.), com título, prévia e horário. Pode ser ocultado pelo botão ☰ e reaberto pelo handle lateral quando recolhido. |
| **Chat** (centro) | Mostra a conversa com a Lori. Inclui área de anexos, campo de mensagem com envio `Enter`, indicador de digitação e o contador de arquivos de contexto. |
| **Raciocínio do agente** (coluna direita) | Exibe pensamentos, chamadas de ferramenta e confirmações. Pode ser recolhido pelo botão 🧠 e reaberto pelo handle com ícone de cérebro na lateral direita. |

### Arquivos de contexto

- Adicione arquivos pelo botão 📎. Os arquivos são armazenados em `$(LORI_HOME)/uploads` (padrão: `/tmp/lori/uploads` em sistemas Unix-like).
- Cada arquivo aparece com nome, tamanho, ícone e botão **Remover**. Enquanto o backend processa o pedido o item exibe um spinner.
- O botão **Limpar** remove todos os arquivos carregados. O contador abaixo do título indica quantos arquivos estão ativos.

### Outros recursos úteis

- Alternância de tema claro/escuro pela opção ◑ na barra superior.
- Histórico e painel do agente lembram o estado (aberto/fechado) entre sessões via `localStorage`.
- Handles laterais (☰ e 🧠) facilitam reabrir os painéis sem tomar espaço do chat.

### Evoluções planejadas

- Automação para reconhecer pedidos de atualização (ex.: "atualize o preço do BTC") e refazer consultas relevantes automaticamente.
- Aperfeiçoar heurísticas para aprender preferências por conversa utilizando o histórico agrupado.

---

## 📁 Estrutura do projeto

```
assistant-cli/
├── assistant_cli/          # Núcleo do agente e ferramentas
│   ├── __init__.py         # Inicializador do módulo
│   ├── agent.py            # Loop principal do agente
│   ├── cli.py              # Entrada do CLI
│   ├── config.py           # Variáveis de ambiente e diretórios padrão
│   ├── heuristic_processor.py # Processador de heurísticas
│   ├── ollama_client.py    # Cliente para o Ollama
│   ├── test_agent.py       # Testes para o agente
│   ├── test_tools.py       # Testes para as ferramentas
│   ├── tools_cli.py        # Ferramentas de linha de comando
│   └── tools.py            # Registro de ferramentas/bindings
├── web/                    # Backend FastAPI (serviços REST/WebSocket)
│   ├── main.py             # Aplicação FastAPI e rotas
│   └── static/             # Front-end (index.html, style.css, app.js)
├── scripts/                # Scripts de automação
│   ├── bootstrap.sh        # Script de inicialização
│   ├── run_lori_tests.sh   # Script para rodar testes da Lori
│   ├── run_tests.sh        # Script para rodar testes
│   ├── smoke.sh            # Script para testes de fumaça
│   └── test_tools.sh       # Script para testar ferramentas
├── run.sh                  # Inicializador do CLI
├── run_web.sh              # Inicializador da interface web
├── start.sh                # Menu unificado com bootstrapping
├── lori-logs.sh            # Script para visualizar logs
├── requirements.txt        # Dependências Python
├── setup.py                # Script de setup do projeto
└── config.ini.template     # Template opcional de configuração
```

---

## ⚙️ Configuração

As principais variáveis de ambiente aceitas estão em `assistant_cli/config.py`. Algumas relevantes:

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `ASSISTANT_MODEL` | Modelo a ser usado no Ollama | `mistral` |
| `OLLAMA_BASE_URL` | Endpoint do Ollama | `http://localhost:11434` |
| `LORI_HOME` | Diretório base para workspace/cache/uploads | `/tmp/lori` (via `tempfile.gettempdir()`) |
| `ASSISTANT_ROOT` | Raiz permitida para operações de arquivo | `/tmp/lori/workspace` |
| `ASSISTANT_VERBOSE` | Habilita logs de ferramentas no agente | `0` |
| `OLLAMA_USE_GPU` | Define se o Ollama deve usar GPU (`1`) | auto |

Para customizar permanentemente, você pode criar um `.env` (carregado manualmente) ou exportar as variáveis antes de rodar os scripts.

> **Dica GPU**: assegure-se de instalar a versão do Ollama com suporte CUDA, exporte `OLLAMA_USE_GPU=1` (ou configure `~/.ollama/config`) e baixe o modelo desejado (`ollama pull mistral`) antes de iniciar o menu.

---

## 🧪 Desenvolvimento e testes

- **Testes:** `pytest`
- **Lint:** `ruff check .`
- Os arquivos do front ficam em `web/static/`. Após alterar CSS ou JS basta recarregar a página; o backend roda com `--reload`.
- Anexos enviados pela interface são salvos em `$(LORI_HOME)/uploads` (por padrão, `/tmp/lori/uploads`). Limpe manualmente se necessário.

---

## 🛠️ Solução de problemas

| Sintoma | Como resolver |
| --- | --- |
| Modelo não responde | Verifique se o Ollama está em execução e se o modelo foi baixado (`ollama list`). |
| Não consigo remover arquivo de contexto | Confirme se o item aparece com spinner; se a operação falhar o aviso embaixo do cabeçalho trará o motivo. |
| Portas ocupadas | Ajuste `run_web.sh` passando `--port` para outro valor (`./run_web.sh --port 9000`). |

---

## 📄 Licença

Este projeto é distribuído nos termos definidos pelo autor. Consulte o repositório original para mais detalhes sobre uso e contribuições.
