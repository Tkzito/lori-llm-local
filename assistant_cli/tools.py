from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import shutil
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
import os as _os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None  # type: ignore
    PLAYWRIGHT_AVAILABLE = False

try:
    from bs4 import BeautifulSoup  # fallback HTML parsing
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    from ddgs import DDGS  # type: ignore
    DDG_SEARCH_AVAILABLE = True
except Exception:
    DDG_SEARCH_AVAILABLE = False


try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False

try:
    from pandasql import sqldf
    PANDASQL_AVAILABLE = True
except ImportError:
    sqldf = None
    PANDASQL_AVAILABLE = False

from .config import (
    ASSISTANT_ROOT,
    ASSISTANT_READONLY_DIRS,
    ASSISTANT_GLOBAL_READ,
    ASSISTANT_GLOBAL_WRITE,
    ASSISTANT_DENYLIST,
    CACHE_DIR,
    MAX_READ_BYTES,
    MAX_WEB_CHARS,
    SHELL_ALLOW,
    TIMEOUT_SECS, # Padrão é 60
)


def _is_under(p: Path, base: Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def _resolve_safe_path(path: str) -> Path:
    p = (ASSISTANT_ROOT / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    # Denylist check always
    for d in ASSISTANT_DENYLIST:
        if _is_under(p, d):
            raise ValueError("path denied by admin denylist")
    if ASSISTANT_GLOBAL_WRITE or p == ASSISTANT_ROOT:
        return p
    if not _is_under(p, ASSISTANT_ROOT):
        raise ValueError("path outside ASSISTANT_ROOT")
    return p


def _resolve_readable_path(path: str, allow_outside_root: bool = False) -> Path:
    p = Path(path).resolve() if os.path.isabs(path) else (ASSISTANT_ROOT / path).resolve()
    # Denylist check always
    for d in ASSISTANT_DENYLIST:
        if _is_under(p, d):
            raise ValueError("path denied by admin denylist")
    # Allow if under root
    if _is_under(p, ASSISTANT_ROOT):
        return p
    if allow_outside_root:
        return p
    # Global read mode allows anywhere except denylist
    if ASSISTANT_GLOBAL_READ:
        return p
    # Else, allow read-only if under any whitelisted dir
    for base in ASSISTANT_READONLY_DIRS:
        if _is_under(p, base):
            return p
    raise ValueError("path outside allowed read locations")


def _resolve_write_path(path: str, allow_outside_root: bool = False) -> Path:
    p = Path(path).resolve() if os.path.isabs(path) else (ASSISTANT_ROOT / path).resolve()
    # Denylist check always
    for d in ASSISTANT_DENYLIST:
        if _is_under(p, d):
            raise ValueError("path denied by admin denylist")
    if _is_under(p, ASSISTANT_ROOT):
        return p
    if ASSISTANT_GLOBAL_WRITE or allow_outside_root:
        return p
    raise ValueError("write outside ASSISTANT_ROOT (confirmation required)")


def _confirm_required_response(action: str, path: str, args: Dict[str, Any], reason: str) -> Dict[str, Any]:
    sanitized = {k: v for k, v in args.items() if not str(k).startswith("__")}
    return {
        "ok": False,
        "confirm_required": True,
        "action": action,
        "path": path,
        "args": sanitized,
        "reason": reason,
    }


@dataclass
class ToolSpec:
    name: str
    description: str
    params: Dict[str, Any]
    func: Callable[[Dict[str, Any]], Any]


def tool_fs_read(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    max_bytes = int(args.get("max_bytes", MAX_READ_BYTES))
    encoding = args.get("encoding") or "utf-8"
    try:
        p = _resolve_readable_path(path, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        msg = str(e)
        if "outside allowed read locations" in msg:
            return _confirm_required_response("fs.read", str(Path(path)), {"path": path, "max_bytes": max_bytes}, msg)
        return {"ok": False, "error": msg}
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "file not found"}
    data = p.read_bytes()[:max_bytes]
    try:
        text = data.decode(encoding, errors="replace")
    except Exception:
        text = data.decode("utf-8", errors="replace")
    return {"ok": True, "path": str(p), "content": text, "truncated": len(p.read_bytes()) > max_bytes}


def tool_fs_write(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    content = args.get("content", "")
    create_dirs = bool(args.get("create_dirs", True))
    allow = bool(args.get("__allow_outside_root", False))
    try:
        p = _resolve_write_path(path, allow_outside_root=allow)
    except Exception as e:
        if "confirmation required" in str(e):
            return _confirm_required_response("fs.write", str(Path(path)), {"path": path, "bytes": len(content.encode("utf-8"))}, str(e))
        return {"ok": False, "error": str(e)}
    if create_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}


def tool_fs_append(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    content = args.get("content", "")
    allow = bool(args.get("__allow_outside_root", False))
    try:
        p = _resolve_write_path(path, allow_outside_root=allow)
    except Exception as e:
        if "confirmation required" in str(e):
            return _confirm_required_response("fs.append", str(Path(path)), {"path": path, "bytes": len(content.encode("utf-8"))}, str(e))
        return {"ok": False, "error": str(e)}
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True, "path": str(p), "appended": len(content)}


def tool_fs_list(args: Dict[str, Any]) -> Dict[str, Any]:
    directory = args.get("directory", ".")
    pattern = args.get("glob")
    try:
        d = _resolve_readable_path(directory, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        msg = str(e)
        if "outside allowed read locations" in msg:
            return _confirm_required_response("fs.list", str(Path(directory)), {"directory": directory, "glob": pattern}, msg)
        return {"ok": False, "error": msg}
    if not d.exists() or not d.is_dir():
        return {"ok": False, "error": "directory not found"}
    if pattern:
        items = [str(p) for p in d.rglob(pattern)]
    else:
        items = [str(p) for p in d.iterdir()]
    return {"ok": True, "directory": str(d), "items": items[:1000]}


def tool_fs_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query_raw = args.get("query")
    if query_raw is None or not str(query_raw).strip():
        return {"ok": False, "error": "parâmetro 'query' obrigatório"}
    query = str(query_raw)
    directory = args.get("directory", ".")
    try:
        d = _resolve_readable_path(directory, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        msg = str(e)
        if "outside allowed read locations" in msg:
            return _confirm_required_response("fs.search", str(Path(directory)), {"directory": directory, "query": query}, msg)
        return {"ok": False, "error": msg}
    if not d.exists():
        return {"ok": False, "error": "directory not found"}
    # Prefer ripgrep if available
    try:
        subprocess.run(["rg", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd = ["rg", "-n", "--no-heading", "--color", "never", str(query), str(d)]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=TIMEOUT_SECS)
        text = out.decode("utf-8", errors="replace")
    except Exception:
        # Fallback: naive Python search
        results: List[str] = []
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            try:
                data = path.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(data.splitlines(), 1):
                    if query in line:
                        results.append(f"{path}:{i}:{line}")
            except Exception:
                continue
        text = "\n".join(results)
    return {"ok": True, "matches": text[:200_000]}


def tool_fs_mkdir(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path") or args.get("dir") or args.get("directory")
    if not path:
        return {"ok": False, "error": "path required"}
    allow = bool(args.get("__allow_outside_root", False))
    try:
        p = _resolve_write_path(path, allow_outside_root=allow)
    except Exception as e:
        if "confirmation required" in str(e):
            return _confirm_required_response("fs.mkdir", str(Path(path)), {"path": path}, str(e))
        return {"ok": False, "error": str(e)}
    p.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(p)}


def tool_fs_copy(args: Dict[str, Any]) -> Dict[str, Any]:
    src = args.get("src") or args.get("source")
    dest = args.get("dest") or args.get("destination") or args.get("dst")
    if not src or not dest:
        return {"ok": False, "error": "src and dest required"}
    try:
        ps = _resolve_readable_path(src, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        msg = str(e)
        if "outside allowed read locations" in msg:
            return _confirm_required_response("fs.copy", str(Path(src)), {"src": src, "dest": dest}, msg)
        return {"ok": False, "error": msg}
    allow = bool(args.get("__allow_outside_root", False))
    try:
        pd = _resolve_write_path(dest, allow_outside_root=allow)
    except Exception as e:
        if "confirmation required" in str(e):
            return _confirm_required_response("fs.copy", str(Path(dest)), {"src": src, "dest": dest}, str(e))
        return {"ok": False, "error": str(e)}
    pd.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ps, pd)
    return {"ok": True, "src": str(ps), "dest": str(pd)}


def tool_fs_glob(args: Dict[str, Any]) -> Dict[str, Any]:
    base = args.get("path") or args.get("directory") or "."
    pattern = args.get("pattern") or "*"
    d = _resolve_safe_path(base)
    if not d.exists() or not d.is_dir():
        return {"ok": False, "error": "directory not found"}
    items = [str(p) for p in d.rglob(pattern)]
    return {"ok": True, "directory": str(d), "items": items[:2000]}


def tool_edit_replace(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    find = args.get("find")
    replace = args.get("replace", "")
    count = args.get("count")
    allow = bool(args.get("__allow_outside_root", False))
    # Read preview
    try:
        rp = _resolve_readable_path(path)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not rp.exists() or not rp.is_file():
        return {"ok": False, "error": "file not found"}
    text = rp.read_text(encoding="utf-8", errors="replace")
    n = 0
    if count is None:
        new_text, n = re.subn(re.escape(find), replace, text)
    else:
        new_text, n = re.subn(re.escape(find), replace, text, int(count))
    try:
        wp = _resolve_write_path(path, allow_outside_root=allow)
    except Exception as e:
        if "confirmation required" in str(e):
            return _confirm_required_response("edit.replace", str(Path(path)), {"path": path, "find": find, "replace": replace, "count": count, "matches": n}, str(e))
        return {"ok": False, "error": str(e)}
    if n > 0:
        wp.write_text(new_text, encoding="utf-8")
    return {"ok": True, "replaced": n}


def tool_web_get(args: Dict[str, Any]) -> Dict[str, Any]:
    url = args.get("url")
    if not url:
        return {"ok": False, "error": "URL não fornecida"}

    # Prefer Playwright when available for dynamic pages
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, timeout=TIMEOUT_SECS * 1000)
                page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
                page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_SECS * 1000)
                page.evaluate("() => { document.querySelectorAll('script, style, noscript, nav, footer, aside').forEach(el => el.remove()); }")
                title = page.title()
                text_content = page.evaluate("document.body.innerText")
                text_cleaned = re.sub(r"\s{2,}", " ", text_content)
                text = "\n".join(s.strip() for s in text_cleaned.splitlines() if s.strip())
                text = text[:MAX_WEB_CHARS]
                browser.close()
                return {"ok": True, "title": title, "text": text}
        except Exception as e:
            # Fall through to requests-based fetch
            pass

    # Fallback: requests + BeautifulSoup (if available), simple HTML extraction
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=TIMEOUT_SECS)
        resp.raise_for_status()
        html = resp.text
        title = None
        text = None
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html, "html.parser")
            # Remove elementos menos úteis
            for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
                tag.decompose()
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            raw = soup.get_text("\n")
            text_cleaned = re.sub(r"\s{2,}", " ", raw)
            text = "\n".join(s.strip() for s in text_cleaned.splitlines() if s.strip())[:MAX_WEB_CHARS]
        else:
            # Fallback mínimo sem bs4: regex simples para title e strip do HTML
            m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            # Remove tags rudimentarmente
            text_only = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
            text_only = re.sub(r"<[^>]+>", " ", text_only)
            text_only = re.sub(r"\s{2,}", " ", text_only)
            text = text_only.strip()[:MAX_WEB_CHARS]
        return {"ok": True, "title": title, "text": text}
    except Exception as e:
        return {"ok": False, "error": f"Erro ao acessar a URL: {e}"}


def tool_fs_tempfile(args: Dict[str, Any]) -> Dict[str, Any]:
    """Gera um nome de arquivo temporário seguro com um prefixo e sufixo."""
    import tempfile
    prefix = args.get("prefix", "temp_")
    suffix = args.get("suffix", ".txt")
    # Cria um arquivo temporário nomeado de forma segura no diretório raiz do assistente
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=CACHE_DIR)
    os.close(fd)  # Fecha o manipulador de arquivo, queremos apenas o nome
    return {"ok": True, "path": path}


def tool_web_get_many(args: Dict[str, Any]) -> Dict[str, Any]:
    """Busca e extrai texto de múltiplas URLs em paralelo."""
    urls = args.get("urls")
    if not isinstance(urls, list) or not urls:
        return {"ok": False, "error": "uma lista de 'urls' é necessária"}

    results: list[dict] = []
    
    def fetch_url(url: str) -> dict:
        try:
            return tool_web_get({"url": url})
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    max_workers = min(len(urls), int(args.get("max_workers", 5)) or 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_url, url): url for url in urls}
        for future in as_completed(future_to_url):
            res = future.result()
            res["url"] = future_to_url[future]
            results.append(res)
            
    return {"ok": True, "pages": results}


def tool_web_open(args: Dict[str, Any]) -> Dict[str, Any]:
    urls = args.get("urls") or []
    if not isinstance(urls, list) or not urls:
        return {"ok": False, "error": "urls list required"}
    url = str(urls[0])
    if isinstance(url, str) and url.startswith("//"):
        url = "https:" + url
    return tool_web_get({"url": url})


def _normalize_ddg_url(href: str | None) -> str | None:
    if not href:
        return None
    if "duckduckgo.com/l/" in href or "/l/?" in href:
        parsed_url = urlparse(href)
        return unquote(parse_qs(parsed_url.query).get("uddg", [href])[0])
    return href


def _extract_ddg_results_from_html(html: str, num_results: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if BS4_AVAILABLE:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.web-result")
        if not cards:
            cards = soup.select("div.result")
        for card in cards:
            link = card.select_one("h2 a, a.result__a, .result__title a")
            if not link:
                continue
            href = _normalize_ddg_url(link.get("href"))
            title = link.get_text(strip=True)
            if not (href and title):
                continue
            snippet_el = card.select_one(
                ".result__snippet, .result__snippet.js-result-snippet, .web-result-body, .result__body"
            )
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            out.append({"title": title, "url": href, "snippet": snippet})
            if len(out) >= num_results:
                break
    else:
        for m in re.finditer(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL
        ):
            href, title_html = m.group(1), m.group(2)
            href = _normalize_ddg_url(href)
            title = re.sub(r"<[^>]+>", " ", title_html)
            title = re.sub(r"\s+", " ", title).strip()
            if not (href and title):
                continue
            # Snippet parsing in regex mode is unreliable; leave empty string.
            out.append({"title": title, "url": href, "snippet": ""})
            if len(out) >= num_results:
                break
    return out


def _ddg_html_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """DuckDuckGo HTML search with snippet support.

    Prefere a API da biblioteca `duckduckgo_search` (gratuita) quando disponível,
    com fallback para raspagem HTML via Playwright ou requests.
    """

    if DDG_SEARCH_AVAILABLE:
        try:
            results: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=num_results):
                    href = item.get("href") or item.get("url")
                    url = _normalize_ddg_url(href)
                    title = (item.get("title") or "").strip()
                    snippet = (item.get("body") or item.get("snippet") or "").strip()
                    if not (url and title):
                        continue
                    results.append({"title": title, "url": url, "snippet": snippet})
                    if len(results) >= num_results:
                        break
            if results:
                return results
        except Exception:
            # Fallback to HTML scraping
            pass

    html = ""
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, timeout=TIMEOUT_SECS * 1000)
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                    )
                )
                page.goto(f"https://html.duckduckgo.com/html/?q={query}", timeout=TIMEOUT_SECS * 1000)
                html = page.content()
                browser.close()
        except Exception:
            html = ""

    if not html:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        url = f"https://html.duckduckgo.com/html/?q={query}"  # noqa
        resp = requests.get(url, headers=headers, timeout=TIMEOUT_SECS)
        resp.raise_for_status()
        html = resp.text

    return _extract_ddg_results_from_html(html, num_results)


def tool_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    if not query or not str(query).strip():
        return {"ok": False, "error": "parâmetro 'query' obrigatório"}
    limit = int(args.get("limit", 5))
    query_clean = " ".join(str(query).split())
    attempts: List[str] = [query_clean]
    ascii_variant = " ".join(_norm(query_clean).split()) if query_clean else ""
    if ascii_variant and ascii_variant not in attempts:
        attempts.append(ascii_variant)
    try:
        raw_results: List[Dict[str, str]] = []
        for attempt in attempts:
            raw_results = _ddg_html_search(attempt, limit)
            if raw_results:
                break
        seen: set[str] = set()
        results: List[Dict[str, str]] = []
        for item in raw_results:
            url = item.get("url")
            if url:
                if url in seen:
                    continue
                seen.add(url)
            snippet = (item.get("snippet") or "").strip()
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "snippet": snippet,
            })
            if len(results) >= limit:
                break
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": f"falha_na_busca ({type(e).__name__}): {e}"}


def tool_crypto_price(args: Dict[str, Any]) -> Dict[str, Any]:
    asset = args.get("asset")
    if not asset or not str(asset).strip():
        return {"ok": False, "error": "parâmetro 'asset' obrigatório"}

    vs = args.get("vs_currencies") or ["usd", "brl"]
    if isinstance(vs, str):
        vs_list = [vs]
    elif isinstance(vs, list):
        vs_list = [str(item).lower() for item in vs if str(item).strip()]
    else:
        vs_list = ["usd", "brl"]
    vs_clean = sorted(set(vs_list)) or ["usd", "brl"]

    asset_id, vs_default = _resolve_asset(str(asset), vs_clean)
    if not asset_id:
        return {"ok": False, "error": "asset_desconhecido"}
    vs_clean = sorted(set(vs_default))

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": asset_id,
        "vs_currencies": ",".join(vs_clean),
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": f"falha_coingecko: {exc}"}

    payload = data.get(asset_id)
    if not isinstance(payload, dict):
        return {"ok": False, "error": "resposta_invalida"}

    prices: Dict[str, float] = {}
    changes: Dict[str, float] = {}
    for fiat in vs_clean:
        value = payload.get(fiat)
        if isinstance(value, (int, float)):
            prices[fiat] = float(value)
        change_key = f"{fiat}_24h_change"
        change_val = payload.get(change_key)
        if isinstance(change_val, (int, float)):
            changes[fiat] = float(change_val)

    last_updated_ts = payload.get("last_updated_at")
    last_updated_iso = None
    if isinstance(last_updated_ts, (int, float)) and last_updated_ts > 0:
        try:
            dt_utc = datetime.fromtimestamp(last_updated_ts, tz=timezone.utc)
            last_updated_iso = dt_utc.isoformat().replace("+00:00", "Z")
        except Exception:
            last_updated_iso = None

    now_utc = datetime.now(timezone.utc)
    hours_diff: float | None = None
    if last_updated_iso:
        try:
            updated_dt = datetime.fromisoformat(last_updated_iso.replace("Z", "+00:00"))
            delta = now_utc - updated_dt
            hours_diff = max(delta.total_seconds() / 3600.0, 0.0)
        except Exception:
            hours_diff = None

    return {
        "ok": True,
        "asset": str(asset),
        "asset_id": asset_id,
        "prices": prices,
        "changes_24h": changes,
        "vs_currencies": vs_clean,
        "last_updated": last_updated_ts,
        "last_updated_iso": last_updated_iso,
        "last_updated_hours_ago": hours_diff,
        "source": "https://www.coingecko.com",
    }


def tool_fx_rate(args: Dict[str, Any]) -> Dict[str, Any]:
    base_raw = args.get("base") or "USD"
    target_raw = args.get("target") or "BRL"
    amount_raw = args.get("amount", 1)

    base = str(base_raw).strip().upper()
    target = str(target_raw).strip().upper()
    try:
        amount = float(str(amount_raw).replace(".", "").replace(",", "."))
    except Exception:
        try:
            amount = float(amount_raw)
        except Exception:
            return {"ok": False, "error": "valor inválido para 'amount'"}

    if amount <= 0:
        return {"ok": False, "error": "amount deve ser positivo"}

    url = "https://api.exchangerate.host/convert"
    params = {
        "from": base,
        "to": target,
        "amount": amount,
        "places": 6,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": f"falha_exchangerate: {exc}"}

    if not data or ("success" in data and not data.get("success")):
        return {"ok": False, "error": "resposta_invalida"}

    result_amount = data.get("result")
    info = data.get("info") or {}
    rate = info.get("rate")
    date_str = data.get("date")
    timestamp = info.get("timestamp")

    last_updated_iso = None
    hours_diff: float | None = None
    now_utc = datetime.now(timezone.utc)
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        try:
            dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            last_updated_iso = dt_utc.isoformat().replace("+00:00", "Z")
            hours_diff = max((now_utc - dt_utc).total_seconds() / 3600.0, 0.0)
        except Exception:
            last_updated_iso = None
            hours_diff = None
    elif isinstance(date_str, str):
        try:
            date_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            last_updated_iso = date_dt.isoformat().replace("+00:00", "Z")
            hours_diff = max((now_utc - date_dt).total_seconds() / 3600.0, 0.0)
        except Exception:
            last_updated_iso = None
            hours_diff = None

    return {
        "ok": True,
        "base": base,
        "target": target,
        "amount": amount,
        "rate": rate,
        "converted": result_amount,
        "date": date_str,
        "last_updated_iso": last_updated_iso,
        "last_updated_hours_ago": hours_diff,
        "source": "https://api.exchangerate.host/convert",
    }

# ----------------------
# System/time utilities (offline mapping BR)
# ----------------------
def _norm(s: str) -> str:
    s2 = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return " ".join("".join(ch for ch in s2.lower().strip() if ch.isalnum() or ch.isspace()).split())


_BR_TZ_MAP: Dict[str, str] = {
    "acre": "America/Rio_Branco", "ac": "America/Rio_Branco", "rio branco": "America/Rio_Branco",
    "amazonas": "America/Manaus", "am": "America/Manaus", "manaus": "America/Manaus",
    "rondonia": "America/Porto_Velho", "ro": "America/Porto_Velho", "porto velho": "America/Porto_Velho",
    "roraima": "America/Boa_Vista", "rr": "America/Boa_Vista", "boa vista": "America/Boa_Vista",
    "mato grosso": "America/Cuiaba", "mt": "America/Cuiaba", "cuiaba": "America/Cuiaba",
    "mato grosso do sul": "America/Campo_Grande", "ms": "America/Campo_Grande", "campo grande": "America/Campo_Grande",
    "tocantins": "America/Araguaina", "to": "America/Araguaina", "araguaina": "America/Araguaina",
    "bahia": "America/Bahia", "ba": "America/Bahia", "salvador": "America/Bahia",
    "pernambuco": "America/Recife", "pe": "America/Recife", "recife": "America/Recife",
    "alagoas": "America/Maceio", "al": "America/Maceio", "maceio": "America/Maceio",
    "sergipe": "America/Maceio", "se": "America/Maceio", "aracaju": "America/Maceio",
    "ceara": "America/Fortaleza", "ce": "America/Fortaleza", "fortaleza": "America/Fortaleza",
    "piaui": "America/Fortaleza", "pi": "America/Fortaleza", "teresina": "America/Fortaleza",
    "maranhao": "America/Fortaleza", "ma": "America/Fortaleza", "sao luis": "America/Fortaleza",
    "para": "America/Belem", "pa": "America/Belem", "belem": "America/Belem",
    # BRT (America/Sao_Paulo)
    "sao paulo": "America/Sao_Paulo", "sp": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo", "rj": "America/Sao_Paulo",
    "parana": "America/Sao_Paulo", "pr": "America/Sao_Paulo",
    "santa catarina": "America/Sao_Paulo", "sc": "America/Sao_Paulo",
    "rio grande do sul": "America/Sao_Paulo", "rs": "America/Sao_Paulo",
    "minas gerais": "America/Sao_Paulo", "mg": "America/Sao_Paulo",
    "espirito santo": "America/Sao_Paulo", "es": "America/Sao_Paulo",
    "goias": "America/Sao_Paulo", "go": "America/Sao_Paulo",
    "distrito federal": "America/Sao_Paulo", "df": "America/Sao_Paulo", "brasilia": "America/Sao_Paulo",
    # Capitais comuns do BRT
    "curitiba": "America/Sao_Paulo", "florianopolis": "America/Sao_Paulo", "porto alegre": "America/Sao_Paulo",
    "belo horizonte": "America/Sao_Paulo", "vitoria": "America/Sao_Paulo", "niteroi": "America/Sao_Paulo",
}

_CRYPTO_ID_MAP: Dict[str, str] = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "xbt": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "ether": "ethereum",
    "ethere": "ethereum",
    "ltc": "litecoin",
    "litecoin": "litecoin",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "ada": "cardano",
    "cardano": "cardano",
    "sol": "solana",
    "solana": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "bnb": "binancecoin",
    "binance": "binancecoin",
    "binance coin": "binancecoin",
    "matic": "matic-network",
    "polygon": "matic-network",
    "dot": "polkadot",
    "polkadot": "polkadot",
    "shib": "shiba-inu",
    "shiba": "shiba-inu",
    "avax": "avalanche-2",
    "avalanche": "avalanche-2",
    "xlm": "stellar",
    "stellar": "stellar",
    "busd": "binance-usd",
    "usdt": "tether",
    "tether": "tether",
    "usdc": "usd-coin",
    "usd coin": "usd-coin",
    "dai": "dai",
    "tron": "tron",
    "trx": "tron",
    "pep": "pepe",
    "pepe": "pepe",
}


def _resolve_asset(symbol: str, vs_override: list[str] | None = None) -> tuple[str | None, list[str]]:
    key = _norm(symbol).replace(" ", "")
    vs = vs_override or ["usd", "brl"]
    if key.startswith("id:") and len(key) > 3:
        return key[3:], vs
    asset_id = _CRYPTO_ID_MAP.get(key)
    return (asset_id, vs)

# País -> fuso padrão (capital/maior cidade). Não exaustivo, mas cobre a maioria dos casos.
_COUNTRY_DEFAULT_TZ: Dict[str, str] = {
    # Américas
    "brasil": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "argentina": "America/Argentina/Buenos_Aires",
    "chile": "America/Santiago",
    "uruguai": "America/Montevideo", "uruguay": "America/Montevideo",
    "paraguai": "America/Asuncion", "paraguay": "America/Asuncion",
    "bolivia": "America/La_Paz",
    "equador": "America/Guayaquil", "ecuador": "America/Guayaquil",
    "guiana": "America/Guyana", "guyana": "America/Guyana",
    "peru": "America/Lima",
    "suriname": "America/Paramaribo",
    "colombia": "America/Bogota",
    "mexico": "America/Mexico_City",
    "canada": "America/Toronto",
    "estados unidos": "America/New_York", "eua": "America/New_York", "usa": "America/New_York", "united states": "America/New_York",
    # Europa
    "portugal": "Europe/Lisbon",
    "espanha": "Europe/Madrid", "spain": "Europe/Madrid",
    "franca": "Europe/Paris", "frança": "Europe/Paris", "france": "Europe/Paris",
    "reino unido": "Europe/London", "uk": "Europe/London", "united kingdom": "Europe/London",
    "italia": "Europe/Rome", "itália": "Europe/Rome", "italy": "Europe/Rome",
    "alemanha": "Europe/Berlin", "germany": "Europe/Berlin",
    "austria": "Europe/Vienna", "áustria": "Europe/Vienna",
    "suica": "Europe/Zurich", "suíça": "Europe/Zurich", "switzerland": "Europe/Zurich",
    "venezuela": "America/Caracas",
    "russia": "Europe/Moscow", "rússia": "Europe/Moscow", "russian federation": "Europe/Moscow",
    "belgica": "Europe/Brussels", "bélgica": "Europe/Brussels",
    "paises baixos": "Europe/Amsterdam", "holanda": "Europe/Amsterdam", "netherlands": "Europe/Amsterdam",
    "irlanda": "Europe/Dublin", "ireland": "Europe/Dublin",
    "dinamarca": "Europe/Copenhagen", "denmark": "Europe/Copenhagen",
    "noruega": "Europe/Oslo", "norway": "Europe/Oslo",
    "suecia": "Europe/Stockholm", "suécia": "Europe/Stockholm", "sweden": "Europe/Stockholm",
    "finlandia": "Europe/Helsinki", "finlândia": "Europe/Helsinki", "finland": "Europe/Helsinki",
    "polonia": "Europe/Warsaw", "polônia": "Europe/Warsaw", "poland": "Europe/Warsaw",
    "republica tcheca": "Europe/Prague", "chéquia": "Europe/Prague", "tchequia": "Europe/Prague", "czech republic": "Europe/Prague",
    "grecia": "Europe/Athens", "grécia": "Europe/Athens", "greece": "Europe/Athens",
    "hungria": "Europe/Budapest", "hungary": "Europe/Budapest",
    "romenia": "Europe/Bucharest", "romênia": "Europe/Bucharest", "romania": "Europe/Bucharest",
    "ucrania": "Europe/Kiev", "ucrânia": "Europe/Kiev", "ukraine": "Europe/Kiev",
    "bielorrussia": "Europe/Minsk", "belarus": "Europe/Minsk",
    "croacia": "Europe/Zagreb", "croácia": "Europe/Zagreb", "croatia": "Europe/Zagreb",
    "servia": "Europe/Belgrade", "sérvia": "Europe/Belgrade", "serbia": "Europe/Belgrade",
    "bulgaria": "Europe/Sofia", "bulgária": "Europe/Sofia", "bulgaria": "Europe/Sofia",
    "eslovaquia": "Europe/Bratislava", "eslováquia": "Europe/Bratislava", "slovakia": "Europe/Bratislava",
    "eslovenia": "Europe/Ljubljana", "eslovênia": "Europe/Ljubljana", "slovenia": "Europe/Ljubljana",
    "lituania": "Europe/Vilnius", "lituânia": "Europe/Vilnius", "lithuania": "Europe/Vilnius",
    "letonia": "Europe/Riga", "letônia": "Europe/Riga", "latvia": "Europe/Riga",
    "estonia": "Europe/Tallinn", "estônia": "Europe/Tallinn", "estonia": "Europe/Tallinn",
    "islandia": "Atlantic/Reykjavik", "islândia": "Atlantic/Reykjavik", "iceland": "Atlantic/Reykjavik",
    "turquia": "Europe/Istanbul", "turkey": "Europe/Istanbul",

    # África
    "egito": "Africa/Cairo", "egypt": "Africa/Cairo",
    "africa do sul": "Africa/Johannesburg", "south africa": "Africa/Johannesburg",
    "nigeria": "Africa/Lagos", "nigéria": "Africa/Lagos",
    "quenia": "Africa/Nairobi", "quênia": "Africa/Nairobi", "kenya": "Africa/Nairobi",
    "marrocos": "Africa/Casablanca", "morocco": "Africa/Casablanca",
    "angola": "Africa/Luanda",
    "mocambique": "Africa/Maputo", "moçambique": "Africa/Maputo",

    # Ásia / Oceania
    "japao": "Asia/Tokyo", "japão": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "china": "Asia/Shanghai",
    "india": "Asia/Kolkata", "índia": "Asia/Kolkata",
    "coreia do sul": "Asia/Seoul", "south korea": "Asia/Seoul",
    "coreia do norte": "Asia/Pyongyang", "north korea": "Asia/Pyongyang",
    "australia": "Australia/Sydney", "austrália": "Australia/Sydney",
    "tailandia": "Asia/Bangkok", "tailândia": "Asia/Bangkok", "thailand": "Asia/Bangkok",
    "indonesia": "Asia/Jakarta", "indonésia": "Asia/Jakarta",
    "vietna": "Asia/Ho_Chi_Minh", "vietnã": "Asia/Ho_Chi_Minh", "vietnam": "Asia/Ho_Chi_Minh",
    "malasia": "Asia/Kuala_Lumpur", "malásia": "Asia/Kuala_Lumpur", "malaysia": "Asia/Kuala_Lumpur",
    "cingapura": "Asia/Singapore", "singapore": "Asia/Singapore",
    "filipinas": "Asia/Manila", "philippines": "Asia/Manila",
    "paquistao": "Asia/Karachi", "paquistão": "Asia/Karachi", "pakistan": "Asia/Karachi",
    "arabia saudita": "Asia/Riyadh", "saudi arabia": "Asia/Riyadh",
    "emirados arabes unidos": "Asia/Dubai", "uae": "Asia/Dubai", "united arab emirates": "Asia/Dubai",
    "ira": "Asia/Tehran", "irã": "Asia/Tehran", "iran": "Asia/Tehran",
    "israel": "Asia/Jerusalem",
    "nova zelandia": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
}

# Principais cidades do mundo (amostra prática, offline)
_WORLD_TZ_MAP: Dict[str, str] = {
    "new york": "America/New_York", "nyc": "America/New_York",
    "nova york": "America/New_York",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "mexico": "America/Mexico_City", "mexico city": "America/Mexico_City", "cidade do mexico": "America/Mexico_City",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "bogota": "America/Bogota", "lima": "America/Lima",
    "london": "Europe/London", "londres": "Europe/London", "lisbon": "Europe/Lisbon", "lisboa": "Europe/Lisbon", "madrid": "Europe/Madrid",
    "paris": "Europe/Paris", "berlin": "Europe/Berlin", "rome": "Europe/Rome", "roma": "Europe/Rome",
    "istanbul": "Europe/Istanbul", "istambul": "Europe/Istanbul",
    "cairo": "Africa/Cairo", "johannesburg": "Africa/Johannesburg", "cape town": "Africa/Johannesburg",
    "dubai": "Asia/Dubai", "doha": "Asia/Qatar", "riyadh": "Asia/Riyadh",
    "moscow": "Europe/Moscow", "moscou": "Europe/Moscow",
    "delhi": "Asia/Kolkata", "deli": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "beijing": "Asia/Shanghai", "pequim": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "xangai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "tokyo": "Asia/Tokyo", "toquio": "Asia/Tokyo", "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "bangkok": "Asia/Bangkok", "singapore": "Asia/Singapore",
        "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
        # Alguns exônimos comuns em PT-BR
        "zurique": "Europe/Zurich", "genebra": "Europe/Zurich",
        "copenhague": "Europe/Copenhagen",
        "estocolmo": "Europe/Stockholm",
        "viena": "Europe/Vienna",
        "praga": "Europe/Prague",
        "varsovia": "Europe/Warsaw", "varsóvia": "Europe/Warsaw",
        "atenas": "Europe/Athens",
        "bruxelas": "Europe/Brussels",
        "amesterda": "Europe/Amsterdam", "amsterda": "Europe/Amsterdam", "amsterdã": "Europe/Amsterdam",
        "munique": "Europe/Berlin", "colonia": "Europe/Berlin", "colônia": "Europe/Berlin",
    }


def _tz_from_location(q: str) -> Optional[str]:
    qn = _norm(q)
    words = set(qn.split())
    # 1) Dicionários rápidos (BR + mundo)
    for key, tz in {**_BR_TZ_MAP, **_WORLD_TZ_MAP}.items():
        kn = _norm(key)
        if (" " in kn and kn in qn) or (" " not in kn and len(kn) > 1 and kn in words):
            return tz
    # 2) País isolado -> fuso padrão do país
    for key, tz in _COUNTRY_DEFAULT_TZ.items():
        kn = _norm(key)
        if (" " in kn and kn in qn) or (" " not in kn and len(kn) > 1 and kn in words):
            return tz

    # 3) UTC/GMT com offset (ex.: UTC+3, GMT-5, UTC+05:30)
    import re as _re
    m = _re.search(r"\b(?:(?:utc)|(?:gmt))\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?\b", qn)
    if m:
        sign = -1 if m.group(1) == '-' else 1
        hh = int(m.group(2))
        mm = int(m.group(3) or 0)
        offset = sign * (hh + mm/60)
        # ZoneInfo aceita Etc/GMT±N com sinal invertido (padrão IANA)
        inv = -int(offset)
        tz_name = f"Etc/GMT{inv:+d}".replace("+", "+").replace("-", "-")
        try:
            ZoneInfo(tz_name)
            return tz_name
        except Exception:
            pass

    # 4) Indexar zona IANA do sistema e buscar por cidade/área
    tz = _search_iana_by_city_or_full(qn)
    if tz:
        return tz
    try:
        ZoneInfo(q)
        return q
    except Exception:
        return None


_TZ_INDEX_CANDIDATES: List[Dict[str, str]] | None = None
_TZ_SCAN_DIRS = [
    "/usr/share/zoneinfo",
    "/usr/lib/zoneinfo",
    "/usr/share/lib/zoneinfo",
]
_TZ_SKIP_TOP = {"posix", "right", "SystemV"}
_TZ_SKIP_FILES = {"posixrules", "leap-seconds.list", "localtime", "zone.tab", "zone1970.tab"}


def _build_tz_index() -> None:
    global _TZ_INDEX_CANDIDATES
    if _TZ_INDEX_CANDIDATES is not None:
        return
    cands: List[Dict[str, str]] = []
    for root in _TZ_SCAN_DIRS:
        if not _os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in _os.walk(root):
            # pular diretórios superiores indesejados
            parts = dirpath[len(root):].strip("/").split("/") if dirpath != root else []
            if parts and parts[0] in _TZ_SKIP_TOP:
                dirnames[:] = []
                continue
            for fn in filenames:
                if fn in _TZ_SKIP_FILES:
                    continue
                full = _os.path.join(dirpath, fn)
                rel = full[len(root):].lstrip("/")
                if not rel:
                    continue
                tzid = rel
                area = rel.split("/", 1)[0]
                city = rel.split("/")[-1]
                city_n = _norm(city.replace("_", " "))
                tz_full_n = _norm(rel.replace("_", " ").replace("/", " "))
                cands.append({
                    "tz": tzid,
                    "area": area,
                    "city": city,
                    "city_n": city_n,
                    "full_n": tz_full_n,
                })
    _TZ_INDEX_CANDIDATES = cands


def _search_iana_by_city_or_full(loc_norm: str) -> Optional[str]:
    _build_tz_index()
    if not _TZ_INDEX_CANDIDATES:
        return None
    words = set(loc_norm.split())
    # Preferência 1: city_n igual
    exact = [c for c in _TZ_INDEX_CANDIDATES if c["city_n"] == loc_norm]
    if exact:
        return sorted(exact, key=lambda c: (len(c["tz"]), c["tz"]))[0]["tz"]
    # Preferência 2: city_n contido
    contains = [c for c in _TZ_INDEX_CANDIDATES if c["city_n"] in loc_norm]
    if contains:
        return sorted(contains, key=lambda c: (len(c["tz"]), c["tz"]))[0]["tz"]
    # Preferência 3: full_n igual
    full_eq = [c for c in _TZ_INDEX_CANDIDATES if c["full_n"] == loc_norm]
    if full_eq:
        return sorted(full_eq, key=lambda c: (len(c["tz"]), c["tz"]))[0]["tz"]
    # Preferência 4: interseção de palavras razoável
    scored: List[tuple[int, str]] = []
    for c in _TZ_INDEX_CANDIDATES:
        cf = set(c["full_n"].split())
        inter = len(words & cf)
        if inter >= 2:
            scored.append((inter, c["tz"]))
    if scored:
        scored.sort(key=lambda t: (-t[0], len(t[1]), t[1]))
        return scored[0][1]
    return None


def tool_sys_time(args: Dict[str, Any]) -> Dict[str, Any]:
    tz = args.get("tz")
    loc = args.get("location") or args.get("loc")
    verify_online = bool(args.get("verify_online", False))
    resolved_tz = None
    if not tz and loc:
        resolved_tz = _tz_from_location(str(loc))
        tz = resolved_tz or tz
        if tz is None:
            return {"ok": False, "error": "localização não reconhecida"}
    try:
        tzinfo = ZoneInfo(tz) if tz else None
    except Exception:
        return {"ok": False, "error": "fuso horário inválido"}
    now = datetime.now(tzinfo) if tzinfo else datetime.now()
    iso = now.isoformat()
    txt = now.strftime("%d/%m/%Y %H:%M:%S %Z")
    out: Dict[str, Any] = {"ok": True, "iso": iso, "texto": txt, "tz": (tz or "local")}
    if resolved_tz:
        out["resolved_from"] = str(loc)
    if verify_online and tz:
        try:
            url = f"https://worldtimeapi.org/api/timezone/{tz}"
            r = requests.get(url, timeout=TIMEOUT_SECS, headers={"User-Agent": "assistant-cli/1.0"})
            r.raise_for_status()
            data = r.json()
            out["online"] = {
                "source": "worldtimeapi.org",
                "datetime": data.get("datetime"),
                "utc_offset": data.get("utc_offset"),
                "abbrev": data.get("abbreviation"),
            }
        except Exception as e:
            out["online"] = {"source": "worldtimeapi.org", "error": str(e)}
    return out


def tool_sys_time_bulk(args: Dict[str, Any]) -> Dict[str, Any]:
    """Obtém data/hora para múltiplos países de uma ou mais regiões."""
    regions_in = args.get("region") or []
    countries_in = args.get("countries") or []
    verify = bool(args.get("verify_online", False))

    countries_to_check: set[str] = set(c.strip() for c in countries_in if c)

    if isinstance(regions_in, str):
        regions_in = [regions_in]

    if isinstance(regions_in, list) and regions_in:
        geo_res = tool_geo_countries({"region": regions_in, "verify_online": False})
        if geo_res.get("ok"):
            for r in geo_res.get("regions", []):
                if r.get("ok"):
                    countries_to_check.update(r.get("countries", []))

    if not countries_to_check:
        return {"ok": False, "error": "nenhuma região ou país válido fornecido"}

    results: list[dict] = []
    sorted_countries = sorted(list(countries_to_check))

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_country = {executor.submit(tool_sys_time, {"location": c, "verify_online": verify}): c for c in sorted_countries}
        country_results = {}
        for future in as_completed(future_to_country):
            country = future_to_country[future]
            try:
                res = future.result()
                country_results[country] = res
            except Exception as e:
                country_results[country] = {"ok": False, "error": str(e)}

    for country in sorted_countries:
        res = country_results.get(country, {"ok": False, "error": "processamento falhou"})
        item = {"country": country, "ok": res.get("ok"), "texto": res.get("texto"), "tz": res.get("tz"), "iso": res.get("iso"), "error": res.get("error")}
        results.append(item)

    return {"ok": True, "items": results}

def _resolve_tz_any(q: Optional[str], allow_web: bool = False) -> Optional[str]:
    if not q:
        return None
    q = str(q)
    tz = _tz_from_location(q) or _tz_from_country(q)
    if not tz and allow_web:
        tz = _web_guess_tz(q)
    if tz:
        try:
            ZoneInfo(tz)
            return tz
        except Exception:
            return None
    return None


def tool_sys_time_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    """Compara horários entre dois locais/fusos.
    Args aceitos:
      - tz1|from_tz|tz_from, tz2|to_tz|tz_to
      - loc1|from|location_from, loc2|to|location_to
      - verify_online: bool (verifica o destino)
    """
    v = bool(args.get("verify_online", False))
    tz1 = args.get("tz1") or args.get("from_tz") or args.get("tz_from")
    tz2 = args.get("tz2") or args.get("to_tz") or args.get("tz_to")
    loc1 = args.get("loc1") or args.get("from") or args.get("location_from")
    loc2 = args.get("loc2") or args.get("to") or args.get("location_to")
    if not tz1:
        tz1 = _resolve_tz_any(loc1, allow_web=v)
    if not tz2:
        tz2 = _resolve_tz_any(loc2, allow_web=v)
    if not tz1 or not tz2:
        return {"ok": False, "error": "não foi possível resolver um dos fusos (origem/destino)"}
    try:
        z1 = ZoneInfo(tz1)
        z2 = ZoneInfo(tz2)
    except Exception:
        return {"ok": False, "error": "fuso horário inválido"}
    now_utc = datetime.utcnow()
    t1 = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(z1)
    t2 = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(z2)
    delta_minutes = int((t2.utcoffset().total_seconds() - t1.utcoffset().total_seconds()) // 60)
    sign = "+" if delta_minutes >= 0 else "-"
    hh, mm = divmod(abs(delta_minutes), 60)
    diff_txt = f"{sign}{hh:02d}:{mm:02d}"
    out: Dict[str, Any] = {
        "ok": True,
        "from": {"tz": tz1, "texto": t1.strftime("%d/%m/%Y %H:%M:%S %Z"), "iso": t1.isoformat()},
        "to": {"tz": tz2, "texto": t2.strftime("%d/%m/%Y %H:%M:%S %Z"), "iso": t2.isoformat()},
        "offset_diff": diff_txt,
    }
    if v:
        try:
            url = f"https://worldtimeapi.org/api/timezone/{tz2}"
            r = requests.get(url, timeout=TIMEOUT_SECS, headers={"User-Agent": "assistant-cli/1.0"})
            r.raise_for_status()
            data = r.json()
            out["online_to"] = {
                "source": "worldtimeapi.org",
                "datetime": data.get("datetime"),
                "utc_offset": data.get("utc_offset"),
                "abbrev": data.get("abbreviation"),
            }
        except Exception as e:
            out["online_to"] = {"source": "worldtimeapi.org", "error": str(e)}
    return out


def tool_shell_exec(args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = args.get("cmd")
    # A ferramenta agora espera uma lista, onde o primeiro item é o comando.
    if isinstance(cmd, str):
        # Tenta dividir a string, mas desencoraja comandos complexos.
        cmd_list = shlex.split(cmd)
        if len(cmd_list) > 1 and any(op in cmd_list for op in ["&&", ";", "|", ">", "<"]):
             return {"ok": False, "error": "Comandos complexos com operadores de shell não são permitidos. Execute um comando por vez."}
        cmd = cmd_list
    elif not isinstance(cmd, list):
        return {"ok": False, "error": "O parâmetro 'cmd' deve ser uma lista de strings (comando e argumentos)."}

    if not cmd:
        return {"ok": False, "error": "empty cmd"}
    # Allow any command when '*' present
    if "*" not in SHELL_ALLOW and cmd[0] not in SHELL_ALLOW:
        return {"ok": False, "error": f"command not allowed: {cmd[0]}"}
    # Minimal hazard guard for `rm -rf /` when fully open
    if "*" in SHELL_ALLOW and cmd[0] == "rm" and any(x in cmd for x in ("-rf", "-fr")) and "/" in cmd:
        return {"ok": False, "error": "dangerous rm detected (blocked)"}
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=TIMEOUT_SECS)
        return {"ok": True, "stdout": out.decode("utf-8", errors="replace")[:200_000]}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "code": e.returncode, "output": e.output.decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ----------------------
# Geografia: países por região (offline, PT-BR)
# ----------------------
_REGION_ALIASES = {
    "america do norte": "norte",
    "américa do norte": "norte",
    "north america": "norte",
    "norte": "norte",

    "america central": "central",
    "américa central": "central",
    "central america": "central",
    "central": "central",

    "america do sul": "sul",
    "américa do sul": "sul",
    "south america": "sul",
    "sul": "sul",

    "caribe": "caribe",
    "caribbean": "caribe",

    # Continentes
    "europa": "europa",
    "europe": "europa",

    "africa": "africa",
    "áfrica": "africa",
    "africa continent": "africa",

    "asia": "asia",
    "ásia": "asia",

    "oceania": "oceania",
    "australia and oceania": "oceania",

    "antartica": "antartica",
    "antártica": "antartica",
    "antarctica": "antartica",
}

_REGION_COUNTRIES_PT = {
    "norte": ["Canadá", "Estados Unidos", "México"],
    "central": [
        "Belize", "Costa Rica", "El Salvador", "Guatemala", "Honduras", "Nicarágua", "Panamá"
    ],
    "sul": [
        "Argentina", "Bolívia", "Brasil", "Chile", "Colômbia", "Equador", "Guiana",
        "Paraguai", "Peru", "Suriname", "Uruguai", "Venezuela"
    ],
    "caribe": [
        "Antígua e Barbuda", "Bahamas", "Barbados", "Cuba", "Dominica", "Granada",
        "Haiti", "Jamaica", "República Dominicana", "Santa Lúcia",
        "São Cristóvão e Nevis", "São Vicente e Granadinas", "Trinidad e Tobago"
    ],

    # Europa (países soberanos; inclui transcontinentais usuais)
    "europa": [
        "Albânia", "Alemanha", "Andorra", "Áustria", "Bélgica", "Bielorrússia", "Bósnia e Herzegovina",
        "Bulgária", "Croácia", "Dinamarca", "Eslováquia", "Eslovênia", "Espanha", "Estônia",
        "Finlândia", "França", "Grécia", "Hungria", "Irlanda", "Islândia", "Itália",
        "Letônia", "Liechtenstein", "Lituânia", "Luxemburgo", "Malta", "Moldávia", "Mônaco",
        "Montenegro", "Noruega", "Países Baixos", "Polônia", "Portugal", "Reino Unido",
        "Chéquia", "Romênia", "Rússia", "San Marino", "Sérvia", "Suécia", "Suíça",
        "Ucrânia", "Vaticano", "Macedônia do Norte"
    ],

    # África
    "africa": [
        "África do Sul", "Angola", "Argélia", "Benim", "Botsuana", "Burquina Fasso", "Burúndi",
        "Cabo Verde", "Camarões", "Chade", "Comores", "Congo", "Costa do Marfim", "Djibuti",
        "Egito", "Eritreia", "Eswatini", "Etiópia", "Gabão", "Gâmbia", "Gana", "Guiné",
        "Guiné Equatorial", "Guiné-Bissau", "Lesoto", "Libéria", "Líbia", "Madagascar", "Maláui",
        "Mali", "Marrocos", "Maurício", "Mauritânia", "Moçambique", "Namíbia", "Níger",
        "Nigéria", "Quênia", "República Centro-Africana", "República Democrática do Congo", "Ruanda",
        "São Tomé e Príncipe", "Seicheles", "Senegal", "Serra Leoa", "Somália", "Sudão",
        "Sudão do Sul", "Tanzânia", "Togo", "Tunísia", "Uganda", "Zâmbia", "Zimbábue"
    ],

    # Ásia
    "asia": [
        "Afeganistão", "Arábia Saudita", "Armênia", "Azerbaijão", "Bahrein", "Bangladesh", "Brunei",
        "Butão", "Camboja", "Catar", "Cazaquistão", "China", "Chipre", "Cingapura", "Coreia do Norte",
        "Coreia do Sul", "Emirados Árabes Unidos", "Filipinas", "Geórgia", "Iêmen", "Índia",
        "Indonésia", "Irã", "Iraque", "Israel", "Japão", "Jordânia", "Kuwait", "Laos", "Líbano",
        "Malásia", "Maldivas", "Mianmar", "Mongólia", "Nepal", "Omã", "Paquistão", "Quirguistão",
        "Rússia", "Síria", "Sri Lanka", "Tajiquistão", "Tailândia", "Timor-Leste", "Turcomenistão",
        "Turquia", "Uzbequistão", "Vietnã"
    ],

    # Oceania
    "oceania": [
        "Austrália", "Fiji", "Ilhas Marshall", "Ilhas Salomão", "Kiribati", "Micronésia", "Nauru",
        "Nova Zelândia", "Palau", "Papua-Nova Guiné", "Samoa", "Tonga", "Tuvalu", "Vanuatu"
    ],

    # Antártica (sem países)
    "antartica": [],
}


def _normalize_region(r: str) -> str:
    r2 = _norm(r)
    return _REGION_ALIASES.get(r2, r2)


def tool_geo_countries(args: Dict[str, Any]) -> Dict[str, Any]:
    region = args.get("region")
    verify = bool(args.get("verify_online", False))
    if not region:
        return {"ok": False, "error": "parâmetro 'region' obrigatório (string ou lista)"}
    regions_in: List[str]
    if isinstance(region, list):
        regions_in = [str(x) for x in region if x]
    else:
        regions_in = [str(region)]
    regions_norm = [_normalize_region(r) for r in regions_in]
    out_regions: List[Dict[str, Any]] = []
    for r in regions_norm:
        key = r
        if key not in _REGION_COUNTRIES_PT:
            out_regions.append({"region": r, "ok": False, "error": "região desconhecida"})
            continue
        countries = list(_REGION_COUNTRIES_PT[key])
        item: Dict[str, Any] = {"region": r, "ok": True, "countries": countries}
        if key == "antartica":
            item["note"] = "Não há países soberanos na Antártica"
        if verify:
            try:
                q = f"site:wikipedia.org países da {r}"
                refs = _ddg_html_search(q, 5)
                item["sources"] = [ref.get("url") for ref in refs if ref.get("url")]
            except Exception:
                item["sources"] = []
        out_regions.append(item)
    return {"ok": True, "regions": out_regions}


def tool_geo_continents(args: Dict[str, Any]) -> Dict[str, Any]:
    verify = bool(args.get("verify_online", False))
    continents = [
        "África",
        "Antártica",
        "Ásia",
        "Europa",
        "América do Norte",
        "América do Sul",
        "Oceania",
    ]
    out: Dict[str, Any] = {"ok": True, "continents": continents, "count": len(continents)}
    if verify:
        try:
            q = "site:wikipedia.org continentes do mundo"
            refs = _ddg_html_search(q, 5)
            out["sources"] = [ref.get("url") for ref in refs if ref.get("url")]
        except Exception:
            out["sources"] = []
    return out


def tool_spreadsheet_read_sheet(args: Dict[str, Any]) -> Dict[str, Any]:
    """Lê uma ou todas as abas de um arquivo de planilha (Excel, CSV)."""
    if not PANDAS_AVAILABLE:
        return {"ok": False, "error": "A biblioteca 'pandas' é necessária para ler planilhas."}

    path = args.get("path")
    try:
        p = _resolve_readable_path(path, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        msg = str(e)
        if "outside allowed read locations" in msg:
            return _confirm_required_response("spreadsheet.read_sheet", str(Path(path)), {"path": path}, msg)
        return {"ok": False, "error": msg}

    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "Arquivo de planilha não encontrado."}

    try:
        # Detecta o tipo de arquivo e usa a função de leitura correta
        if str(p).lower().endswith(".csv"):
            df = pd.read_csv(p)
            df_dict = {"Sheet1": df} # Trata o CSV como uma única aba
        else:
            # sheet_name=None lê todas as abas de um arquivo Excel
            df_dict = pd.read_excel(p, sheet_name=None)

        sheets_data = {}
        for sheet_name, df in df_dict.items():
            # Retorna as primeiras 50 linhas como CSV para o LLM analisar
            csv_preview = df.head(50).to_csv(index=False)
            sheets_data[sheet_name] = {"rows": len(df), "columns": list(df.columns), "head_csv": csv_preview}
        return {"ok": True, "path": str(p), "sheets": sheets_data}
    except Exception as e:
        return {"ok": False, "error": f"Falha ao ler a planilha: {e}"}

def tool_spreadsheet_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """Executa uma consulta em linguagem natural em um arquivo de planilha (Excel, CSV)."""
    if not PANDAS_AVAILABLE or not PANDASQL_AVAILABLE:
        return {"ok": False, "error": "As bibliotecas 'pandas' e 'pandasql' são necessárias para esta consulta."}

    path = args.get("path")
    query = args.get("query")
    if not query:
        return {"ok": False, "error": "O parâmetro 'query' é obrigatório."}

    # O LLM deve fornecer uma query SQL. O nome da tabela é sempre 'df'.
    if not re.search(r"\bselect\b", query, re.I) or not re.search(r"\bfrom\s+df\b", query, re.I):
        return {"ok": False, "error": "Consulta SQL inválida. A consulta DEVE ser no formato 'SELECT ... FROM df ...', usando 'df' como o nome da tabela."}

    try:
        p = _resolve_readable_path(path, allow_outside_root=bool(args.get("__allow_outside_root", False)))
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "Arquivo de planilha não encontrado."}
    try:
        if str(p).lower().endswith(".csv"):
            df = pd.read_csv(p)
        else:
            df = pd.read_excel(p)
        
        # Executa a query SQL no DataFrame
        result_df = sqldf(query, locals())
        return {"ok": True, "query": query, "result": result_df.to_markdown(index=False)}
    except Exception as e:
        return {"ok": False, "error": f"Falha ao executar a consulta na planilha: {e}"}

def registry() -> Dict[str, ToolSpec]:
    return {
        "help.tools": ToolSpec(
            name="help.tools",
            description="Lista as ferramentas disponíveis com descrições e parâmetros",
            params={},
            func=tool_help_tools,
        ),
        "fs.tempfile": ToolSpec(
            name="fs.tempfile",
            description="Gera um nome de arquivo temporário seguro.",
            params={"prefix": "str?", "suffix": "str?"},
            func=tool_fs_tempfile,
        ),
        "fs.read": ToolSpec(
            name="fs.read",
            description="Ler arquivo sob a raiz",
            params={"path": "str", "max_bytes": "int?", "encoding": "str?"},
            func=tool_fs_read,
        ),
        "fs.write": ToolSpec(
            name="fs.write",
            description="Gravar arquivo sob a raiz",
            params={"path": "str", "content": "str", "create_dirs": "bool?"},
            func=tool_fs_write,
        ),
        "fs.append": ToolSpec(
            name="fs.append",
            description="Acrescentar conteúdo a arquivo sob a raiz",
            params={"path": "str", "content": "str"},
            func=tool_fs_append,
        ),
        "fs.list": ToolSpec(
            name="fs.list",
            description="Listar arquivos (glob opcional) sob a raiz",
            params={"directory": "str?", "glob": "str?"},
            func=tool_fs_list,
        ),
        "fs.mkdir": ToolSpec(
            name="fs.mkdir",
            description="Criar diretório (com pais)",
            params={"path": "str"},
            func=tool_fs_mkdir,
        ),
        "fs.copy": ToolSpec(
            name="fs.copy",
            description="Copiar arquivo de origem para destino",
            params={"src": "str", "dest": "str"},
            func=tool_fs_copy,
        ),
        "fs.glob": ToolSpec(
            name="fs.glob",
            description="Listar arquivos que casam com padrão glob sob caminho",
            params={"path": "str?", "pattern": "str"},
            func=tool_fs_glob,
        ),
        "fs.search": ToolSpec(
            name="fs.search",
            description="Buscar texto usando ripgrep se disponível",
            params={"query": "str", "directory": "str?"},
            func=tool_fs_search,
        ),
        "edit.replace": ToolSpec(
            name="edit.replace",
            description="Localizar/substituir dentro de um arquivo",
            params={"path": "str", "find": "str", "replace": "str", "count": "int?"},
            func=tool_edit_replace,
        ),
        "web.get": ToolSpec(
            name="web.get",
            description="Buscar e extrair texto de uma URL",
            params={"url": "str"},
            func=tool_web_get,
        ),
        "crypto.price": ToolSpec(
            name="crypto.price",
            description="Retorna preço de criptoativos via CoinGecko",
            params={"asset": "str", "vs_currencies": "list|str?"},
            func=tool_crypto_price,
        ),
        "fx.rate": ToolSpec(
            name="fx.rate",
            description="Converte moedas via exchangerate.host",
            params={"base": "str", "target": "str?", "amount": "float?"},
            func=tool_fx_rate,
        ),
        "web.get_many": ToolSpec(
            name="web.get_many",
            description="Busca e extrai texto de uma lista de URLs em paralelo",
            params={"urls": "list"},
            func=tool_web_get_many,
        ),
        "web.search": ToolSpec(
            name="web.search",
            description="Pesquisa no DuckDuckGo (raspagem HTML)",
            params={"query": "str", "limit": "int?"},
            func=tool_web_search,
        ),
        "web.open": ToolSpec(
            name="web.open",
            description="Abrir a primeira URL de uma lista e extrair texto",
            params={"urls": "list"},
            func=tool_web_open,
        ),
        "shell.exec": ToolSpec(
            name="shell.exec",
            description="Executar comando permitido (lista segura)",
            params={"cmd": "list|str"},
            func=tool_shell_exec,
        ),
        # Git tools (local repo only; no network)
        "git.status": ToolSpec(
            name="git.status",
            description="Executar 'git status' em um repositório sob a raiz (sem cor)",
            params={"path": "str?"},
            func=tool_git_status,
        ),
        "git.diff": ToolSpec(
            name="git.diff",
            description="Executar 'git diff' (opcionalmente staged=true) e/ou arquivos específicos",
            params={"path": "str?", "staged": "bool?", "files": "list?"},
            func=tool_git_diff,
        ),
        "git.commit": ToolSpec(
            name="git.commit",
            description="Criar um commit local; opcionalmente add_all ou lista de arquivos",
            params={"path": "str?", "message": "str", "add_all": "bool?", "files": "list?"},
            func=tool_git_commit,
        ),
        "git.branch": ToolSpec(
            name="git.branch",
            description="Listar/criar/trocar branches. action: list|create|switch",
            params={"path": "str?", "action": "str", "name": "str?"},
            func=tool_git_branch,
        ),
        "git.restore": ToolSpec(
            name="git.restore",
            description="Restaurar working tree ou staged para arquivos dados",
            params={"path": "str?", "files": "list", "staged": "bool?"},
            func=tool_git_restore,
        ),
        "fmt.black": ToolSpec(
            name="fmt.black",
            description="Formatar com Black os caminhos fornecidos",
            params={"paths": "list", "check": "bool?"},
            func=tool_fmt_black,
        ),
        "lint.ruff": ToolSpec(
            name="lint.ruff",
            description="Executar linter Ruff nos caminhos fornecidos",
            params={"paths": "list", "fix": "bool?"},
            func=tool_lint_ruff,
        ),
        "sys.time": ToolSpec(
            name="sys.time",
            description="Retorna data e hora (por tz ou localização); opção de verificação online",
            params={"tz": "str?", "location": "str?", "verify_online": "bool?"},
            func=tool_sys_time,
        ),
        "sys.time.bulk": ToolSpec(
            name="sys.time.bulk",
            description="Retorna data/hora para múltiplos países por região/lista",
            params={"region": "str|list", "countries": "list?", "verify_online": "bool?"},
            func=tool_sys_time_bulk,
        ),
        "sys.time.diff": ToolSpec(
            name="sys.time.diff",
            description="Comparar horários/offset entre dois locais ou fusos",
            params={"tz1": "str?", "tz2": "str?", "loc1": "str?", "loc2": "str?", "verify_online": "bool?"},
            func=tool_sys_time_diff,
        ),
        "geo.countries": ToolSpec(
            name="geo.countries",
            description="Listar países por região (América do Norte/Central/Sul; Caribe)",
            params={"region": "str|list", "verify_online": "bool?"},
            func=tool_geo_countries,
        ),
        "geo.continents": ToolSpec(
            name="geo.continents",
            description="Listar continentes e total (offline); opção de verificação online",
            params={"verify_online": "bool?"},
            func=tool_geo_continents,
        ),
        "spreadsheet.read_sheet": ToolSpec(
            name="spreadsheet.read_sheet",
            description="Lê o conteúdo de uma ou mais abas de um arquivo de planilha (Excel).",
            params={"path": "str"},
            func=tool_spreadsheet_read_sheet,
        ),
        "spreadsheet.query": ToolSpec(
            name="spreadsheet.query",
            description="Executa uma consulta SQL em um arquivo de planilha (Excel, CSV). A ferramenta lê o arquivo do 'path' fornecido; não use 'fs.read' antes. A tabela para a consulta se chama sempre 'df'.",
            params={"path": "str", "query": "str"},
            func=tool_spreadsheet_query,
        ),
    }


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize common alias names and argument shapes
    def _normalize_tool_alias(n: Any, a: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        if not isinstance(n, str):
            return "", a
        n2 = n
        a2 = dict(a or {})
        if n2 in ("fs.writeFile", "fs-extra.writeFile"):
            n2 = "fs.write"
            if "data" in a2 and "content" not in a2:
                a2["content"] = a2.pop("data")
        elif n2 in ("mkdir", "fs.mkdirp"):
            n2 = "fs.mkdir"
        elif n2 in ("cp", "filecopy"):
            n2 = "fs.copy"
        elif n2 == "edit.ini":
            content = a2.get("content")
            if isinstance(content, list) and len(content) >= 3 and str(content[0]).lower() == "replace":
                a2 = {
                    "path": a2.get("path"),
                    "find": str(content[1]).strip("'\""),
                    "replace": str(content[2]).strip("'\""),
                }
            n2 = "edit.replace"
        elif n2 == "web.openMany":
            n2 = "web.open"
        elif n2 in ("git.checkout", "git.switchBranch"):
            n2 = "git.branch"
            a2["action"] = a2.get("action", "switch")
        elif n2 in ("git.createBranch", "git.newBranch"):
            n2 = "git.branch"
            a2["action"] = a2.get("action", "create")
        elif n2 in ("format.black", "black"):
            n2 = "fmt.black"
        elif n2 in ("lint.ruff", "ruff"):
            n2 = "lint.ruff"
        return n2, a2

    tools = registry()
    n, a = _normalize_tool_alias(name, args)
    if n not in tools:
        return {"ok": False, "error": f"unknown tool: {name}"}
    return tools[n].func(a)


def tool_help_tools(args: Dict[str, Any]) -> Dict[str, Any]:
    tools = registry()
    listing = []
    for name, spec in tools.items():
        listing.append(
            {
                "name": name,
                "description": spec.description,
                "params": spec.params,
            }
        )
    return {"ok": True, "tools": listing}


# ----------------------
# Git tool implementations
# ----------------------

def _git_run(cmd: List[str], cwd: Path | None) -> Dict[str, Any]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, cwd=str(cwd) if cwd else None, timeout=TIMEOUT_SECS)
        return {"ok": True, "stdout": out.decode("utf-8", errors="replace")}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "code": e.returncode, "output": e.output.decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _opt_rooted_path(path_opt: Optional[str]) -> Path:
    if not path_opt or str(path_opt).strip() in (".", "./"):
        return ASSISTANT_ROOT
    return _resolve_safe_path(path_opt)


def tool_git_status(args: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _opt_rooted_path(args.get("path"))
    return _git_run(["git", "-c", "color.ui=never", "status", "--porcelain=v1", "-u"], cwd)


def tool_git_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _opt_rooted_path(args.get("path"))
    files = args.get("files") or []
    staged = bool(args.get("staged", False))
    cmd = ["git", "-c", "color.ui=never", "diff"]
    if staged:
        cmd.append("--staged")
    if files and isinstance(files, list):
        cmd.extend([str(f) for f in files])
    return _git_run(cmd, cwd)


def tool_git_commit(args: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _opt_rooted_path(args.get("path"))
    message = args.get("message")
    add_all = bool(args.get("add_all", False))
    files = args.get("files") or []
    if not message:
        return {"ok": False, "error": "commit message required"}
    if add_all:
        r = _git_run(["git", "add", "-A"], cwd)
        if not r.get("ok"):
            return r
    elif files:
        r = _git_run(["git", "add", *[str(f) for f in files]], cwd)
        if not r.get("ok"):
            return r
    # Create commit
    return _git_run(["git", "commit", "-m", message], cwd)


def tool_git_branch(args: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _opt_rooted_path(args.get("path"))
    action = (args.get("action") or "list").lower()
    name = args.get("name")
    if action == "list":
        return _git_run(["git", "branch", "--list"], cwd)
    if action == "create":
        if not name:
            return {"ok": False, "error": "branch name required"}
        return _git_run(["git", "branch", name], cwd)
    if action in ("switch", "checkout"):
        if not name:
            return {"ok": False, "error": "branch name required"}
        return _git_run(["git", "switch", name], cwd)
    return {"ok": False, "error": f"unknown action: {action}"}


def tool_git_restore(args: Dict[str, Any]) -> Dict[str, Any]:
    cwd = _opt_rooted_path(args.get("path"))
    files = args.get("files") or []
    staged = bool(args.get("staged", False))
    if not files or not isinstance(files, list):
        return {"ok": False, "error": "files list required"}
    cmd = ["git", "restore"]
    if staged:
        cmd.append("--staged")
    cmd.extend([str(f) for f in files])
    return _git_run(cmd, cwd)


def tool_fmt_black(args: Dict[str, Any]) -> Dict[str, Any]:
    paths = args.get("paths") or []
    check = bool(args.get("check", False))
    if not paths or not isinstance(paths, list):
        return {"ok": False, "error": "paths list required"}
    cmd = ["black"]
    if check:
        cmd.append("--check")
    cmd.extend([str(p) for p in paths])
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, cwd=str(ASSISTANT_ROOT), timeout=TIMEOUT_SECS)
        return {"ok": True, "stdout": out.decode("utf-8", errors="replace")}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "code": e.returncode, "output": e.output.decode("utf-8", errors="replace")}
    except FileNotFoundError:
        return {"ok": False, "error": "black not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_lint_ruff(args: Dict[str, Any]) -> Dict[str, Any]:
    paths = args.get("paths") or []
    fix = bool(args.get("fix", False))
    if not paths or not isinstance(paths, list):
        return {"ok": False, "error": "paths list required"}
    cmd = ["ruff", "check"]
    if fix:
        cmd.append("--fix")
    cmd.extend([str(p) for p in paths])
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, cwd=str(ASSISTANT_ROOT), timeout=TIMEOUT_SECS)
        return {"ok": True, "stdout": out.decode("utf-8", errors="replace")}
    except subprocess.CalledProcessError as e:
        # Ruff returns non-zero on issues; still return output
        return {"ok": True, "stdout": e.output.decode("utf-8", errors="replace"), "exit": e.returncode}
    except FileNotFoundError:
        return {"ok": False, "error": "ruff not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
