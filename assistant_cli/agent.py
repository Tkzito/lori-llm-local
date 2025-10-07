from __future__ import annotations

import json
from typing import Any, Dict, List, Iterator, Iterable
from pathlib import Path
from datetime import datetime

from .config import ASSISTANT_MODEL, HISTORY_PATH, ASSISTANT_VERBOSE, DEFAULT_NOTE_FILE, ASSISTANT_ROOT
from .ollama_client import OllamaClient
from .tools import call_tool, registry as tools_registry
from .heuristic_processor import HeuristicProcessor


SYSTEM_PROMPT = (
    "Você é a Lori, uma assistente de IA para o terminal, programada para ser proativa, inteligente e amigável, respondendo em Português do Brasil. "
    "Sua principal função é executar tarefas usando um conjunto de ferramentas. "
    "Para executar uma ação, sua resposta DEVE conter um único bloco <tool_call> com o JSON da chamada. Exemplo: <tool_call>{\"tool\":\"fs.read\",\"args\":{\"path\":\"arquivo.txt\"}}</tool_call>. "
    "Após o resultado da ferramenta (<tool_result>), você pode usar outra ferramenta ou fornecer a resposta final. "
    "Se a pergunta for uma conversa ou não precisar de ferramentas (ex: 'olá'), responda diretamente. "
    "Pense passo a passo. Se um caminho de arquivo não for fornecido, use 'fs.list' para encontrá-lo. Não invente caminhos. "
    f"Todas as operações de arquivo são restritas ao diretório ASSISTANT_ROOT (atualmente em '{ASSISTANT_ROOT}'). "
    f"Prefira reutilizar e atualizar arquivos existentes, especialmente {DEFAULT_NOTE_FILE}, em vez de criar novos. "
    "Quando o usuário apontar erros ou pedir para verificar, execute novamente as ferramentas relevantes para obter dados atualizados. "
    "Para cotações de criptoativos, use a ferramenta 'crypto.price'. "
    "Para apresentar dados tabulares, use a sintaxe de tabelas do Markdown. "
    "Para visualizações simples, como gráficos de barra, use arte ASCII (ex: 'BTC: ██████░░░░ 70%')."
)


def extract_tool_call(text: str) -> Dict[str, Any] | None:
    import re

    m = re.search(r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def format_tool_result(obj: Dict[str, Any]) -> str:
    return f"<tool_result>{json.dumps(obj, ensure_ascii=False)}</tool_result>"


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

            # Se for uma chamada de stream, já começamos a retornar os chunks
            if is_stream_call:
                full_response_content = yield from self._process_and_forward_stream(model_response_iter, agent_mode)
            else:
                full_response_content = "".join(c.get("message", {}).get("content", "") for c in model_response_iter)

            self.add_assistant(full_response_content)

            tool_call = extract_tool_call(full_response_content)

            if not tool_call:
                if expecting_tools and not tool_success and retries < 2:
                    retries += 1
                    nudge_msg = (
                        f"Lembre-se: para a tarefa '{last_prompt[:50]}...', você deve usar uma das ferramentas disponíveis. "
                        "Use a sintaxe <tool_call>{\"tool\":\"nome.da.ferramenta\", ...}</tool_call> para executar a ação."
                    )
                    self.add_user(nudge_msg)
                    if agent_mode:
                        yield {"type": "thought", "content": "O modelo não usou uma ferramenta. Tentando novamente com uma instrução mais clara."}
                    continue
                
                # Para chamadas não-stream, o comportamento permanece o mesmo
                self._save_history()
                return self._strip_internal(full_response_content)
            name = tool_call.get("tool")
            args = tool_call.get("args") or {}
            if agent_mode:
                yield {"type": "tool_call", "data": {"name": name, "args": args}}
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

            if isinstance(result, dict):
                is_ok = result.get("ok", True)
                error_code = str(result.get("error")) if not is_ok else ""

                if agent_mode:
                    yield {"type": "tool_result", "data": result}

                if not is_ok and error_code != "user_denied":
                    if retries < 2:
                        retries += 1
                        self.add_user(format_tool_result(result))
                        continue
                
                self.add_user(format_tool_result(result))
                if not is_ok:
                    if error_code == "user_denied":
                        expecting_tools = False
                    continue
                tool_success = True
            else:
                self.add_user(format_tool_result({"ok": True, "result": result}))

        final_fallback = "Não consegui processar a resposta após várias tentativas."
        self._save_history()
        if not is_stream_call:
            return final_fallback
        else:
            yield {"type": "content", "content": final_fallback}

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
