from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .agent import Agent


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
    args = ap.parse_args()

    # Allow enabling verbose from flag without exporting env
    if args.verbose:
        import os
        os.environ["ASSISTANT_VERBOSE"] = "1"

    if args.prompt:
        return run_once(args.prompt, model=args.model)
    return repl(model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
