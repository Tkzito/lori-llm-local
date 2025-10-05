import os
from pathlib import Path


def env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val is not None and val != "" else default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


def get_home() -> Path:
    return Path(os.environ.get("HOME", str(Path.cwd()))).expanduser()


HOME = get_home()

# Ollama
OLLAMA_BASE_URL = env_str("OLLAMA_BASE_URL", "http://localhost:11434")
ASSISTANT_MODEL = env_str("ASSISTANT_MODEL", "mistral")

# Root restriction for all fs ops
ASSISTANT_ROOT = Path(env_str("ASSISTANT_ROOT", str(HOME))).resolve()

# Storage
STATE_DIR = Path(env_str("ASSISTANT_STATE_DIR", str(HOME / ".local" / "share" / "assistant_cli"))).resolve()
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_PATH = STATE_DIR / "history.jsonl"

# Safety
SHELL_ALLOW = set(
    (os.environ.get("ASSISTANT_SHELL_ALLOW", "cat,ls,rg,sed,awk,head,tail,cut,stat,date,uname,df,du,wc,sort,uniq,whoami,python,python3,git,echo,black,ruff" ).split(","))
)
MAX_WEB_CHARS = env_int("ASSISTANT_MAX_WEB_CHARS", 6000)
MAX_READ_BYTES = env_int("ASSISTANT_MAX_READ_BYTES", 512 * 1024)
TIMEOUT_SECS = env_int("ASSISTANT_TIMEOUT_SECS", 60)

# Verbose prints of tool calls/results
ASSISTANT_VERBOSE = os.environ.get("ASSISTANT_VERBOSE", "0") not in ("", "0", "false", "False")


def env_paths_list(name: str, default: str = "") -> list[Path]:
    raw = os.environ.get(name, default)
    if not raw:
        return []
    parts = [p for p in raw.split(":") if p]
    out: list[Path] = []
    for p in parts:
        try:
            out.append(Path(p).expanduser().resolve())
        except Exception:
            continue
    return out


# Allow read-only access outside of ASSISTANT_ROOT for these absolute directories
ASSISTANT_READONLY_DIRS = env_paths_list("ASSISTANT_READONLY_DIRS", "")

# Admin mode toggles
ASSISTANT_GLOBAL_READ = os.environ.get("ASSISTANT_GLOBAL_READ", "0") not in ("", "0", "false", "False")
ASSISTANT_GLOBAL_WRITE = os.environ.get("ASSISTANT_GLOBAL_WRITE", "0") not in ("", "0", "false", "False")
ASSISTANT_DENYLIST = env_paths_list(
    "ASSISTANT_DENYLIST",
    "/proc:/sys:/dev:/run:/boot",
)
