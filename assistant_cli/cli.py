from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Optional

from .agent import Agent
from .config import HISTORY_PATH

def _strip_internal_markers(text: str) -> str:
    text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text or "")
    text = re.sub(r"<tool_result>[\s\S]*?</tool_result>", "", text)
    return text.strip()


def show_history(limit: int) -> int:
    max_items = limit if limit and limit > 0 else 5
    if not HISTORY_PATH.exists():
        print("Nenhum histórico encontrado.")
        return 0
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        print(f"Erro ao ler o histórico: {exc}", file=sys.stderr)
        return 1

    entries = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    if not entries:
        print("Nenhum histórico registrado ainda.")
        return 0

    total = len(entries)
    selected = entries[-max_items:]
    print(f"Histórico recente (mostrando {len(selected)} de {total}):")

    def _trim(sample: str) -> str:
        normalized = (sample or "").replace("\n", " ").strip()
        return normalized[:177] + "..." if len(normalized) > 180 else normalized

    for item in reversed(selected):
        ts = item.get("ts", "?")
        model = item.get("model", "?")
        messages = item.get("messages") or []
        first_user = ""
        last_assistant = ""
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user" and not first_user:
                first_user = content
            elif role == "assistant":
                last_assistant = content

        first_user = _trim(_strip_internal_markers(first_user))
        last_assistant = _trim(_strip_internal_markers(last_assistant))

        print(f"- [{ts}] modelo: {model}")
        if first_user:
            print(f"  usuário: {first_user}")
        if last_assistant:
            print(f"  assistente: {last_assistant}")
        print()

    return 0


def run_once(text: str, model: Optional[str] = None) -> int:
    agent = Agent(model=model)
    answer = agent.run(text)
    print(answer)
    return 0


def repl(model: Optional[str] = None) -> int:
    agent = Agent(model=model)
    print("Assistant CLI — digite Ctrl+D para sair")
    try:
        while True:
            try:
                prompt = input("you> ")
            except EOFError:
                print()
                break
            if not prompt.strip():
                continue
            
            # A função run agora pode retornar um gerador se a resposta for do LLM
            response = agent.run(prompt)
            
            print("assistant> ", end="", flush=True)
            if isinstance(response, str):
                # Resposta direta (de um atalho de ferramenta)
                print(response)
            else:
                # Resposta em streaming do LLM
                for chunk in response:
                    print(chunk, end="", flush=True)
            print("\n")
    except KeyboardInterrupt:
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Local terminal assistant (Ollama)")
    ap.add_argument("prompt", nargs="?", help="One-shot prompt. If omitted, starts REPL")
    ap.add_argument("--model", dest="model", help="Model name (override env ASSISTANT_MODEL)")
    ap.add_argument("--verbose", action="store_true", help="Print tool calls/results while running")
    ap.add_argument("--history", action="store_true", help="Show recent conversation history and exit")
    ap.add_argument("--history-limit", type=int, default=5, help="Number of history entries to display")
    args = ap.parse_args()

    # Allow enabling verbose from flag without exporting env
    if args.verbose:
        os.environ["ASSISTANT_VERBOSE"] = "1"

    if args.history:
        return show_history(args.history_limit)

    if args.prompt:
        return run_once(args.prompt, model=args.model)
    return repl(model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
