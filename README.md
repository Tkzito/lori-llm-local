Lori CLI – Assistente Local em Português
=======================================

Lori é uma assistente de linha de comando que utiliza seu Ollama local para executar tarefas em português. O projeto inclui um conjunto de ferramentas para leitura/escrita de arquivos, buscas na web, manipulação de Git e consulta a cotações de moedas e criptoativos, tudo sob seu controle e **sem depender de serviços pagos**.

## Requisitos

- Python 3.10+ instalado
- Ollama rodando localmente (https://ollama.com)
- (Opcional) Chave SSH configurada para pushes ao GitHub

### Preparando o Ollama e o modelo local

1. Instale o Ollama conforme o sistema operacional:
   - **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`
   - **macOS/Windows**: baixe o instalador gráfico em <https://ollama.com/download>.
2. Garanta que o serviço `ollama serve` esteja em execução (no Linux ele inicia automaticamente após a instalação).
3. Faça o download do modelo que a Lori utilizará (ex.: `mistral`):
   ```bash
   ollama pull mistral
   ```
4. Teste o modelo localmente para confirmar que está respondendo:
   ```bash
   ollama run mistral "Qual a capital do Brasil?"
   ```
5. Caso deseje outro modelo (por exemplo `llama3`), repita o `ollama pull` com o nome desejado e ajuste a variável `ASSISTANT_MODEL` nas próximas etapas.

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Variáveis de ambiente (opcionais)
export OLLAMA_BASE_URL=http://localhost:11434
export ASSISTANT_MODEL=mistral
```

## Como executar

- Comando único:
  ```bash
  python -m assistant_cli.cli "Resuma README.md"
  ```
- Modo interativo:
  ```bash
  python -m assistant_cli.cli
  ```
- Limitando o acesso a um diretório específico:
  ```bash
  ASSISTANT_ROOT=$PWD python -m assistant_cli.cli
  ```
- Habilitando logs detalhados das ferramentas:
  ```bash
  python -m assistant_cli.cli --verbose "Liste arquivos"
  ```

## Principais ferramentas

| Ferramenta             | Descrição resumida                                                |
|------------------------|-------------------------------------------------------------------|
| `fs.*`                 | Ler, escrever, listar e buscar arquivos dentro do `ASSISTANT_ROOT`|
| `web.search`           | Busca na web via DuckDuckGo (HTML)                                |
| `web.get` / `web.get_many` | Captura o conteúdo de URLs (com fallback sem Playwright)      |
| `crypto.price`         | Cotação em tempo real de criptoativos via CoinGecko              |
| `fx.rate`              | Conversão de moedas em tempo real via exchangerate.host          |
| `git.*`                | Status, diff, commit, push, branch etc.                          |
| `sys.time*` / `geo.*`  | Utilidades de data/hora e informações geográficas                 |

Você pode listar todas as ferramentas disponíveis (com descrição e parâmetros) a qualquer momento:

```bash
python -m assistant_cli.tools_cli --list
```

### Exemplo de chamada direta

```bash
# Ler um arquivo
python -m assistant_cli.tools_cli fs.read --args-json '{"path":"README.md"}'

# Cotação em tempo real do Bitcoin
python -m assistant_cli.tools_cli crypto.price --args-json '{"asset":"bitcoin","vs_currencies":["brl","usd"]}'

# Converter 5 dólares para reais
python -m assistant_cli.tools_cli fx.rate --args-json '{"base":"USD","target":"BRL","amount":5}'
```

## Fluxo rápido de teste

```bash
mkdir -p ~/workspace/assistant-tests
cd ~/workspace/assistant-tests
export ASSISTANT_ROOT=$PWD

# Criar e ler um arquivo
python -m assistant_cli.tools_cli fs.write --args-json '{"path":"notas.txt","content":"Primeira linha"}'
python -m assistant_cli.tools_cli fs.read  --args-json '{"path":"notas.txt"}'

# Buscar texto
printf 'alpha\nbeta\nbeta gamma\n' > sample.txt
python -m assistant_cli.tools_cli fs.search --args-json '{"query":"beta"}'

# Editar conteúdo
echo 'versao=1.0' > config.ini
python -m assistant_cli.tools_cli edit.replace --args-json '{"path":"config.ini","find":"1.0","replace":"2.0"}'

# Ações de Git (dentro de um repositório)
git init
git config user.email you@example.com
git config user.name "Seu Nome"
python -m assistant_cli.tools_cli git.status
python -m assistant_cli.tools_cli git.commit --args-json '{"message":"Teste","add_all":true}'
```

## Rotina com Git

1. Configure sua identidade apenas uma vez:
   ```bash
   git config --global user.name "Seu Nome"
   git config --global user.email "seu.email@exemplo.com"
   ```
2. Ao iniciar uma sessão, ative o `ssh-agent` e adicione sua chave:
   ```bash
   eval "$(ssh-agent -s)"
   ssh-add ~/.ssh/id_ed25519
   ```
3. A Lori pode rodar `git status`, `git diff`, `git commit` e `git push` conforme você direcionar.

## Observações importantes

- As operações de arquivo são limitadas pelo `ASSISTANT_ROOT` para evitar mudanças indesejadas.
- A busca na web usa DuckDuckGo HTML (gratuito). Instalar o pacote `ddgs` melhora snippets e estabilidade.
- `web.get_many` funciona mesmo sem Playwright, usando `requests + BeautifulSoup` como fallback.
- Para dados financeiros, a Lori cruza CoinGecko/Exchangerate com fontes web. Se houver divergências, ela refaz as consultas automaticamente.

## Estrutura do repositório

```
assistant_cli/
 ├── agent.py          # Loop principal da Lori (heurísticas e controle)
 ├── cli.py            # Entrypoint da interface em linha de comando
 ├── tools.py          # Implementação das ferramentas
 ├── tools_cli.py      # CLI para chamar ferramentas diretamente
 ├── test_agent.py     # Testes de comportamento do agente
 └── test_tools.py     # Testes das ferramentas isoladas
scripts/               # Scripts auxiliares (bootstrap, smoke tests, etc.)
run.sh                 # Inicialização rápida (cria venv e instala deps)
.gitignore             # Regras para o Git
README.md              # Este arquivo
requirements.txt       # Dependências Python
```

## Contribuições e manutenção

- Issues e PRs: <https://github.com/Tkzito/llm-local>
- Antes de abrir PR, rode:
  ```bash
  source .venv/bin/activate
  python -m pytest assistant_cli/test_agent.py
  python -m pytest assistant_cli/test_tools.py -k fx_rate
  ```
- Se não conseguir rodar a suíte completa, explique no PR quais comandos foram usados.

## Licença

Projeto disponibilizado sob licença MIT. Sinta-se à vontade para adaptar, contribuir e redistribuir.
