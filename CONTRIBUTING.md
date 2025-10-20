# Contribuindo para Lori LLM Local

Obrigado pelo interesse em melhorar o projeto! Este guia descreve como preparar o ambiente, trabalhar com Git e enviar contribuições de forma consistente.

---

## Visão Geral do Fluxo

1. Abra ou escolha uma issue descrevendo claramente o que será feito.
2. Crie um branch derivado de `main` (ex.: `feature/meu-recurso`).
3. Garanta que os testes e linters passem (`pytest`, `ruff check .`).
4. Atualize documentação e exemplos, se necessário.
5. Abra um Pull Request (PR) preenchendo o template disponível.
6. Aguarde revisão; responda aos comentários e ajuste o branch até a aprovação.

---

## Preparando o Ambiente

```bash
git clone https://github.com/Tkzito/lori-llm-local.git
cd lori-llm-local
python3 -m venv .venv
. .venv/bin/activate            # Linux/macOS (bash/zsh)
.\.venv\Scripts\Activate.ps1    # Windows PowerShell
.\.venv\Scripts\activate.bat    # Windows CMD
pip install -r requirements.txt
```

Dependências opcionais para determinadas ferramentas:

```bash
pip install playwright duckduckgo-search pandas pandasql beautifulsoup4
playwright install
```

Antes de contribuir, execute:

```bash
pytest
ruff check .
```

Se estiver adicionando dependências, atualize `requirements.txt` (ou `pyproject.toml` quando disponível) e mencione no PR.

---

## Convenções de Código

- **Estilo:** siga PEP 8; utilize `ruff` como lint principal.
- **Testes:** cubra novos comportamentos ou correções com testes em `assistant_cli/test_*.py`.
- **Documentação:** atualize `README.md` ou crie notas adicionais quando o comportamento público mudar.
- **Mensagens de commit:** curtas e descritivas (≤ 72 caracteres), ex.: `Adiciona suporte a csv remote`.

---

## Trabalhando com Branches

```bash
git checkout -b feature/nome-do-recurso
# ... faça alterações ...
git add <arquivos>
git commit -m "Mensagem clara do commit"
git push origin feature/nome-do-recurso
```

Abra o PR a partir desse branch, referenciando a issue correspondente (`Fixes #123` ou `Closes #123`).

---

## Processo de Revisão

- O PR deve passar pela suíte de CI (pytest + ruff).
- Pelo menos uma revisão é exigida antes do merge.
- Responda a feedbacks diretamente no PR; marque comentários como resolvidos após aplicar as mudanças.
- Após aprovação, o maintainer responsável faz merge usando *Squash & Merge* ou *Merge commit*, conforme o contexto.

---

## Relatório de Problemas

Use o template de issue disponível no repositório, informando:

- Contexto e comportamento esperado.
- Passos para reproduzir.
- Logs, capturas ou detalhes do ambiente (OS, versão do Python, modelo Ollama).

Se o problema estiver relacionado à empacotamento ou distros, inclua informações adicionais específicas (ex.: versão da distro, gestor de pacotes).

---

## Código de Conduta

Seja respeitoso e colaborativo. Discussões educadas e foco em solução são essenciais para manter a comunidade saudável.

---

## Dúvidas

Abra uma issue com a etiqueta “question” ou inicie uma discussão. Ficaremos felizes em ajudar.

Boas contribuições! 🚀
