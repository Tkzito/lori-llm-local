from __future__ import annotations

import json
from typing import Any, Dict, List, Iterator, Iterable
from pathlib import Path
from datetime import datetime

try:
    from jsonschema import validate, ValidationError
except ImportError:
    validate = None
    ValidationError = Exception

from .config import ASSISTANT_MODEL, HISTORY_PATH, ASSISTANT_VERBOSE, DEFAULT_NOTE_FILE, ASSISTANT_ROOT
from .ollama_client import OllamaClient
from .tools import call_tool, registry as tools_registry
from .heuristic_processor import HeuristicProcessor


SYSTEM_PROMPT = (
    "## Persona\n"
    "- Você é a Lori, uma assistente de IA para o terminal, proativa, inteligente e amigável. Responda sempre em Português do Brasil.\n\n"
    "## Ciclo de Raciocínio (Think-Act Loop)\n"
    "1.  **Pense**: Analise o pedido do usuário. Se precisar de uma ferramenta, formule um plano passo a passo.\n"
    "2.  **Aja**: Execute uma ferramenta por vez usando o formato `<tool_call>{\"tool\": \"nome\", \"args\": {...}}</tool_call>`. Sua resposta DEVE conter apenas um bloco `<tool_call>`.\n"
    "3.  **Observe**: Analise o resultado em `<tool_result>`. Se for um erro, corrija seu plano e tente novamente. Se for o sucesso, continue para o próximo passo ou formule a resposta final.\n"
    "4.  **Responda**: Quando tiver a informação completa, responda ao usuário de forma clara. Se a tarefa não puder ser feita, informe a limitação.\n\n"
    "## Diretrizes de Ferramentas\n"
    "### Regras Gerais\n"
    "- **NÃO INVENTE FERRAMENTAS**: Use **APENAS** as ferramentas da lista fornecida.\n"
    "- **Conversa Casual**: Se o pedido não precisar de ferramentas (ex: 'olá'), responda diretamente.\n"
    "- **Sem Evidências, Sem Resposta**: Se você não tiver evidências suficientes das ferramentas ou do contexto para responder a uma pergunta, diga claramente: 'Não sei com base nas fontes disponíveis.' e sugira uma ação (ex: 'Posso buscar na web sobre X?'). **PROIBIDO**: inventar valores, caminhos, nomes de arquivos, URLs ou resultados.\n"
    "- **Correção de Erros**: Se o usuário apontar um erro ('verifique novamente', 'está errado'), refaça as chamadas às ferramentas relevantes para obter dados atualizados.\n"
    "- **Apresentação**: Use tabelas Markdown para dados tabulares e arte ASCII para visualizações simples (ex: `Progresso: ████░░░░░░ 40%`).\n"
    "### Arquivos e Diretórios\n"
    "- **Restrição**: Todas as operações de arquivo são restritas ao diretório de trabalho (`" f"{ASSISTANT_ROOT}`).\n"
    "- **Encontrar Arquivos**: Se o caminho de um arquivo não for fornecido, seu **primeiro passo DEVE ser** usar `fs.list` ou `fs.glob` para encontrar o nome do arquivo. Use `fs.search` apenas para buscar **texto dentro** dos arquivos.\n"
    "- **Contexto de Arquivos**: Se o conteúdo de um arquivo já foi fornecido na seção 'CONTEXTO DE ARQUIVOS', **NÃO** use `fs.read` nele novamente; prossiga diretamente para a análise.\n"
    "- **Anotações**: Prefira reutilizar e atualizar o arquivo de anotações principal (`" f"{DEFAULT_NOTE_FILE}`) em vez de criar novos arquivos para anotações simples.\n"
    "### Planilhas (CSV/Excel)\n"
    "- **Análise de Dados**: Para **consultar, filtrar ou calcular** dados, use `spreadsheet.query` com uma consulta SQL. A tabela para a consulta se chama sempre `df`. Exemplo: `SELECT Produto, Quantidade * Preco_Unitario AS ValorTotal FROM df WHERE Quantidade > 10`.\n"
    "- **Leitura Simples**: Para apenas **ver o conteúdo** bruto de uma planilha, use `spreadsheet.read_sheet`.\n"
    "### Web e Finanças\n"
    "- **Busca**: Para pesquisas gerais, use `web.search`. Para extrair o conteúdo de uma URL específica, use `web.get`.\n"
    "- **Cotações**: Para preços de criptoativos, use `crypto.price`. Para cotações de moedas (câmbio), use `fx.rate`."
)

TOOL_SCHEMA = {
    "type": "object",
    "required": ["tool", "args"],
    "properties": {
        "tool": {"type": "string", "minLength": 1},
        "args": {"type": "object"},
    },
    "additionalProperties": False,
}

def extract_tool_call(text: str) -> Dict[str, Any] | None:
    import re

    m = re.search(r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
        if validate:
            validate(obj, TOOL_SCHEMA)
        
        # Bloqueia ferramenta "inventada"
        if obj["tool"] not in tools_registry():
            return None
            
        return obj
    except (Exception, ValidationError):
        return None


def format_tool_result(obj: Dict[str, Any]) -> str:
    return f"<tool_result>{json.dumps(obj, ensure_ascii=False)}</tool_result>"


def _classify_env_error(err: str) -> str:
    e = (err or "").lower()
    if "command not allowed: pip" in e or ("pip" in e and "not allowed" in e):
        return "pip_blocked"
    return ""


class Agent:
    def __init__(self, model: str | None = None, interactive: bool = True):
        self.model = model or ASSISTANT_MODEL
        self.client = OllamaClient()
        self.heuristic_processor = HeuristicProcessor(self)
        self.interactive = interactive
        self._approved_paths: set[Path] = set()
        self._last_asset: str | None = None
        self._last_price_vs: list[str] = ["brl", "usd"]
        self._last_search_query: str | None = None
        self._last_search_base_query: str | None = None
        self._last_search_site_filters: list[str] = []
        self._last_search_urls: list[str] = []
        self._last_search_limit: int = 3
        self._last_fx_request: dict[str, Any] | None = None
        self._help_context: dict[str, Any] = {}

        tools_help_lines: List[str] = ["Ferramentas disponíveis (use exatamente estes nomes):"]
        try:
            for name, spec in tools_registry().items():
                params = ", ".join(spec.params.keys()) if isinstance(spec.params, dict) else ""
                tools_help_lines.append(f"- {name} {{{params}}}")
        except Exception:
            pass
        system_prompt = SYSTEM_PROMPT + "\n" + "\n".join(tools_help_lines)
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    def add_context_files(self, file_paths: list[str]):
        """Lê arquivos e adiciona seu conteúdo ao prompt do sistema."""
        if not file_paths:
            return

        context_header = "\n\n--- CONTEXTO DE ARQUIVOS ---\n"
        context_content = ""
        for path_str in file_paths:
            try:
                content = Path(path_str).read_text(encoding="utf-8", errors="replace")
                context_content += f"Conteúdo de '{Path(path_str).name}':\n---\n{content}\n---\n\n"
            except Exception:
                context_content += f"Não foi possível ler o arquivo '{Path(path_str).name}'.\n"
        
        self.messages[0]["content"] += context_header + context_content

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def step(self, stream: bool = False):
        """Ask the client for a reply."""
        return self.client.chat(self.model, self.messages, stream=stream)

    def _run_logic(self, prompt: str, is_stream_call: bool = False, agent_mode: bool = False) -> str | Iterator[Dict[str, Any]]:
        """Internal logic to run the agent, shared by `run` and `run_stream`."""
        if not self.messages or self.messages[-1]["content"] != prompt:
            self.add_user(prompt)

        shortcut_answer = self.heuristic_processor.run_shortcuts(prompt)
        if shortcut_answer is not None and shortcut_answer != "continue":
            if is_stream_call:
                yield {"type": "content", "content": shortcut_answer}
                self._save_history()
                return 

        def expects_tool_use(text: str) -> bool:
            pl = (text or "").lower()
            keywords = [
                "<tool_call>", "fs.", "web.", "edit.", "shell.", "git.", "sys.", "geo.",
                "leia", "ler ", "abrir ", "liste", "listar", "busque", "pesquise", "pesquisa", "executar", "rodar", "use ",
            ]
            return any(k in pl for k in keywords)

        def is_path_approved(raw_path: str | None) -> bool:
            if not raw_path:
                return False
            try:
                target = Path(raw_path).resolve()
            except Exception:
                return False
            for approved in self._approved_paths:
                try:
                    target.relative_to(approved)
                    return True
                except Exception:
                    continue
            return False

        def remember_approval(raw_path: str | None):
            if not raw_path:
                return
            try:
                target = Path(raw_path).resolve()
            except Exception:
                return
            if target.is_dir():
                self._approved_paths.add(target)
            else:
                self._approved_paths.add(target.parent)

        expecting_tools = expects_tool_use(prompt)
        tool_success = shortcut_answer == "continue"
        retries = 0
        for i in range(12):
            model_response_iter = self.step(stream=True)
            
            if is_stream_call:
                raw_response = yield from self._process_and_forward_stream(model_response_iter, agent_mode)
            else:
                raw_response = "".join(c.get("message", {}).get("content", "") for c in model_response_iter)

            tool_call = extract_tool_call(raw_response)

            # Se esperamos uma ferramenta, a resposta DEVE ser um tool_call.
            if expecting_tools:
                if not tool_call:
                    retries += 1
                    if retries < 3:
                        self.add_user(
                            "Saída inválida. Você DEVE responder APENAS com um único bloco "
                            "`<tool_call>{...}</tool_call>`, sem texto fora do bloco."
                        )
                        if agent_mode:
                            yield {"type": "thought", "content": "Saída inválida. Reforçando JSON-only."}
                        continue
                    else:
                        # Aborta de forma limpa após múltiplas falhas
                        self._save_history()
                        final_fallback = "Não consegui executar uma ferramenta válida para isso."
                        if is_stream_call:
                            yield {"type": "content", "content": final_fallback}
                            return
                        return final_fallback
                # Se a chamada da ferramenta é válida, adicione apenas ela ao histórico.
                self.add_assistant(f"<tool_call>{json.dumps(tool_call, ensure_ascii=False)}</tool_call>")
            else:
                # Se não esperávamos ferramenta, adicione a resposta limpa.
                self.add_assistant(self._strip_internal(raw_response))

            if not tool_call:
                # Para chamadas não-stream, o comportamento permanece o mesmo
                self._save_history()
                return self._strip_internal(raw_response)

            name = tool_call.get("tool")
            args = tool_call.get("args") or {}

            # Sanitiza os argumentos para remover parâmetros não permitidos pela especificação da ferramenta
            spec = tools_registry().get(name)
            if spec and isinstance(spec.params, dict):
                allowed_keys = set(spec.params.keys())
                args = {k: v for k, v in args.items() if k in allowed_keys}

            if agent_mode:
                yield {"type": "tool_call", "data": {"name": name, "args": args}} # Mostra os args sanitizados
            result = call_tool(name, args)

            if isinstance(result, dict) and result.get("confirm_required"):
                path_for_prompt = result.get("path")
                if is_path_approved(path_for_prompt):
                    rerun_args = dict(args)
                    rerun_args["__allow_outside_root"] = True
                    result = call_tool(name, rerun_args)
                else:
                    # No modo agente, envia um pedido de confirmação e espera a resposta
                    if agent_mode:
                        confirmation = yield {"type": "confirm_required", "data": result}
                        resp = "s" if confirmation and confirmation.get("approved") else "n"
                    # No modo CLI interativo, usa o input do terminal
                    elif self.interactive:
                        print(f"[confirm] Ação requer aprovação: {json.dumps(result.get('reason'))}")
                        resp = input("Permitir? [s/N]: ").strip().lower()
                    else: # Modo não interativo (CLI ou testes) nega por padrão
                        resp = "n"

                    if resp in ("s", "sim", "y", "yes"):
                        remember_approval(path_for_prompt)
                        rerun_args = dict(args)
                        rerun_args["__allow_outside_root"] = True
                        result = call_tool(name, rerun_args)
                    else:
                        result = {"ok": False, "error": "user_denied"}
                        # Adiciona feedback explícito para o modelo
                        self.add_user(format_tool_result(result))

            if isinstance(result, dict):
                is_ok = result.get("ok", True)
                error_code = str(result.get("error") or "")

                if agent_mode:
                    yield {"type": "tool_result", "data": result}

                if not is_ok:
                    env_flag = _classify_env_error(error_code)
                    if env_flag == "pip_blocked":
                        self.add_user(format_tool_result({
                            "ok": False, "error": "environment_restriction",
                            "message": "Instalação de pacotes bloqueada. Não tente instalar novamente."
                        }))
                        continue

                    if error_code != "user_denied" and retries < 2:
                            retries += 1
                            self.add_user(format_tool_result(result))
                            continue
                
                self.add_user(format_tool_result(result))
                if not is_ok:
                    if error_code == "user_denied":
                        expecting_tools = False
                    continue
                
                simplified_result = self._simplify_tool_result(name, result)
                self.add_user(format_tool_result(simplified_result))
                tool_success = True # Mark as success only after adding the result
            else:
                self.add_user(format_tool_result({"ok": True, "result": result}))

        # Se o loop terminar sem uma resposta final, envia uma mensagem de falha.
        final_fallback_message = "Não consegui processar a resposta após várias tentativas."
        self._save_history()
        if not is_stream_call:
            return final_fallback_message
        else:
            yield {"type": "content", "content": final_fallback_message}

    def _simplify_tool_result(self, tool_name: str, result: dict) -> dict:
        """Simplifica o resultado de certas ferramentas para ser mais fácil para o LLM processar."""
        if tool_name == "spreadsheet.read_sheet" and result.get("ok"):
            sheets_data = result.get("sheets", {})
            simplified_sheets = {}
            for sheet_name, data in sheets_data.items():
                simplified_sheets[sheet_name] = data.get("head_csv", "Não foi possível ler o conteúdo.")
            return {"ok": True, "sheets_content": simplified_sheets}
        
        if tool_name == "fs.read" and result.get("ok"):
            # Não mostra o conteúdo completo para o LLM, apenas confirma a leitura.
            return {"ok": True, "path": result.get("path"), "bytes_read": len(result.get("content", "")), "message": "Arquivo lido com sucesso."}
        
        return result

    def _process_and_forward_stream(self, model_response_iter: Iterable[Dict[str, Any]], agent_mode: bool) -> str:
        """
        Processa o stream do modelo, encaminha os chunks e constrói a resposta completa
        para adicionar ao histórico de mensagens.
        """
        full_response_content = ""
        if agent_mode:
            yield {"type": "thought", "content": "O modelo está gerando a resposta..."}

        for chunk in model_response_iter:
            content_piece = (chunk.get("message", {}) or {}).get("content", "")
            if content_piece:
                full_response_content += content_piece
                yield {"type": "content", "content": content_piece}
        
        return full_response_content

    def _strip_internal(self, text: str) -> str:
        import re
        # Remove tool_call / tool_result blocks
        text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text or "")
        text = re.sub(r"<tool_result>[\s\S]*?</tool_result>", "", text)
        return text.strip()

    def _save_history(self):
        try:
            with HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "model": self.model,
                    "messages": self.messages,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def run(self, prompt: str) -> str:
        """Executes the agent logic for a given prompt, returning a single string response."""
        result = self._run_logic(prompt, is_stream_call=False)
        if not isinstance(result, str):
            # Fallback for safety, should not be hit in this mode.
            return "".join(m.get("content", "") for m in result)
        return result

    def run_stream(self, prompt: str, agent_mode: bool = False) -> Iterator[Dict[str, Any]]:
        """
        Executes the agent logic and yields the final response in chunks (streaming).
        """
        return self._run_logic(prompt, is_stream_call=True, agent_mode=agent_mode)
