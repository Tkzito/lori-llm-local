from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from .tools import call_tool, registry


def main() -> int:
    ap = argparse.ArgumentParser(description="Call assistant tools directly (bypass LLM)")
    ap.add_argument("name", help="Tool name, e.g., fs.read")
    ap.add_argument("--args-json", default="{}", help='JSON object of arguments, e.g., {"path":"file.txt"}')
    ap.add_argument("--list", action="store_true", help="List available tools")
    args = ap.parse_args()

    if args.list:
        for t in sorted(registry().keys()):
            print(t)
        return 0

    try:
        payload: Dict[str, Any] = json.loads(args.args_json)
    except Exception as e:
        print(f"Invalid JSON for --args-json: {e}", file=sys.stderr)
        return 2

    res = call_tool(args.name, payload)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

