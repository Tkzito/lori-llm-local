from __future__ import annotations

import json
import unicodedata
from typing import Any, Dict, List, Iterator, Iterable
from pathlib import Path
from datetime import datetime

from .config import ASSISTANT_MODEL, HISTORY_PATH, ASSISTANT_VERBOSE
from .ollama_client import OllamaClient
from .tools import call_tool, registry as tools_registry


SYSTEM_PROMPT = (
    "Você é a Lori, uma assistente de IA para o terminal, programada para ser proativa, inteligente e amigável. Sua personalidade é colaborativa e você busca sempre a melhor maneira de ajudar, respondendo em Português do Brasil.\n"
    "Para executar ações, use as ferramentas disponíveis (fs.*, web.*, edit.*, shell.*, git.*, sys.*, geo.*).\n"
    "Quando uma ferramenta for necessária, sua resposta DEVE conter um único bloco <tool_call> com o JSON da chamada.\n"
    "Exemplo de chamada: <tool_call>{\"tool\":\"fs.read\",\"args\":{\"path\":\"arquivo.txt\"}}</tool_call>\n"
    "Após o resultado da ferramenta (<tool_result>), você pode usar outra ferramenta ou fornecer a resposta final.\n"
    "Se a pergunta for uma conversa ou não precisar de ferramentas, responda diretamente.\n"
    "Pense passo a passo. Se um caminho de arquivo não for fornecido, use as ferramentas para encontrá-lo. Não invente caminhos.\n"
    "Quando o usuário apontar divergências, dados desatualizados ou pedir conferência, execute novamente as ferramentas relevantes, compare as fontes e explique as diferenças.\n"
    "Para cotações de criptoativos, priorize a ferramenta crypto.price, informe sempre horário (UTC) e variação das últimas 24 horas e cite a fonte."
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
    def __init__(self, model: str | None = None):
        self.model = model or ASSISTANT_MODEL
        self.client = OllamaClient()
        self._approved_paths: set[Path] = set()
        self._last_asset: str | None = None
        self._last_price_vs: list[str] = ["brl", "usd"]
        self._last_search_query: str | None = None
        self._last_search_base_query: str | None = None
        self._last_search_site_filters: list[str] = []
        self._last_search_urls: list[str] = []
        self._last_search_limit: int = 3
        self._last_fx_request: dict[str, Any] | None = None
        # Constrói uma ajuda de ferramentas dinâmica (PT-BR)
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

    def step(self):
        """Ask the client for a reply (non-stream)."""
        try:
            return self.client.chat(self.model, self.messages, stream=False)
        except TypeError:
            return self.client.chat(self.model, self.messages)

    def _setup_heuristic_rules(self):
        import re

        def handle_time_diff(p, m):
            return {"loc1": m.group(2).strip(), "loc2": m.group(3).strip()}

        def handle_time_loc(p, m):
            args = {"location": m.group(2), "verify_online": False}
            if any(w in p for w in ["verificar", "conferir", "checar", "online"]):
                args["verify_online"] = True
            return args

        def handle_time_bulk(p, m):
            regions = self._extract_regions_from_prompt(p)
            if not regions:
                return None
            args = {"region": regions}
            if any(w in p for w in ["verificar", "conferir", "checar", "online"]):
                args["verify_online"] = True
            return args

        def prepare_search_query(original_prompt: str, core_query: str | None, limit: int = 3, site_filters: list[str] | None = None) -> dict[str, Any]:
            filters = list(site_filters or [])
            for match in re.findall(r"(?:https?://)?([a-z0-9.-]+\.[a-z]{2,})(?:/[^\s]*)?", original_prompt):
                domain = match.lower().strip()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain not in filters:
                    filters.append(domain)

            base_query = " ".join((core_query or original_prompt or "").split())
            if not base_query:
                base_query = core_query or original_prompt or ""

            filters_clause = ""
            if filters:
                filters_clause = " " + " ".join(f"site:{d}" for d in filters)
            final_query = (base_query + filters_clause).strip() or base_query

            self._last_search_site_filters = filters
            self._last_search_base_query = base_query or None
            self._last_search_query = final_query or None
            self._last_search_urls = []
            self._last_search_limit = limit

            return {"query": final_query, "limit": limit}

        def handle_geo_countries(p, m):
            regions = self._extract_regions_from_prompt(p)
            if not regions:
                return None
            args = {"region": regions, "verify_online": any(w in p for w in ["verificar", "conferir", "checar", "online"])}
            return args

        def handle_web_search(p, m):
            q = p
            # Remove menções diretas à assistente
            for prefix in ("lori ", "lori, ", "hey lori ", "ei lori ", "ola lori "):
                if q.startswith(prefix):
                    q = q[len(prefix):]
                    break
            # Remove os gatilhos da busca do início da frase
            triggers = ["pesquisa na internet", "pesquise na internet", "pesquisar na internet", "busca na internet", "pesquise", "pesquisar", "buscar", "busque"]
            for t in sorted(triggers, key=len, reverse=True):
                if q.startswith(t + " "):
                    q = q[len(t) + 1:]
                    break
            # Remove preposições comuns que sobram
            q = re.sub(r"^(sobre|a respeito de|de|do|da|o|a)\s+", "", q).strip()

            return prepare_search_query(p, " ".join(q.split()), 3)

        currency_aliases = {
            "usd": "USD",
            "dolar": "USD",
            "dolares": "USD",
            "dolaramericano": "USD",
            "dolaresamericanos": "USD",
            "dollar": "USD",
            "dollars": "USD",
            "real": "BRL",
            "reais": "BRL",
            "realbrasileiro": "BRL",
            "realbrasil": "BRL",
            "brl": "BRL",
            "euro": "EUR",
            "eur": "EUR",
            "libra": "GBP",
            "libraesterlina": "GBP",
            "gbp": "GBP",
            "iene": "JPY",
            "yen": "JPY",
            "jpy": "JPY",
            "pesoargentino": "ARS",
            "ars": "ARS",
            "cad": "CAD",
            "dolarcanadense": "CAD",
            "aud": "AUD",
            "dolaraustraliano": "AUD",
        }

        def normalize_currency(token: str | None) -> str | None:
            if not token:
                return None
            token_norm = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode("ascii")
            token_norm = "".join(ch for ch in token_norm.lower() if ch.isalnum())
            return currency_aliases.get(token_norm)

        def handle_price_search(p, m):
            asset = m.group(1).strip()
            query = f"preço atual {asset}"
            self._last_asset = asset
            self._last_price_vs = ["brl", "usd"]
            search_args = prepare_search_query(p, query, 3)
            return [
                {"tool": "crypto.price", "args": {"asset": asset, "vs_currencies": ["brl", "usd"]}},
                {"tool": "web.search", "args": search_args},
            ]

        def handle_fx_convert(p, m):
            norm_text = unicodedata.normalize("NFKD", p or "").encode("ascii", "ignore").decode("ascii").lower()
            amount = 1.0
            amount_match = re.search(r"(\d+[\d.,]*)", norm_text)
            if amount_match:
                amount_txt = amount_match.group(1)
                try:
                    amount = float(amount_txt.replace(".", "").replace(",", "."))
                except Exception:
                    try:
                        amount = float(amount_txt)
                    except Exception:
                        amount = 1.0

            tokens = norm_text.split()
            base_code = None
            target_code = None
            for tok in tokens:
                code = normalize_currency(tok)
                if not code:
                    continue
                if base_code is None:
                    base_code = code
                elif target_code is None and code != base_code:
                    target_code = code

            if base_code is None:
                base_code = "USD"
            if target_code is None:
                target_code = "BRL" if base_code != "BRL" else "USD"

            self._last_fx_request = {"base": base_code, "target": target_code, "amount": amount}
            search_args = prepare_search_query(p, f"cotação {base_code} {target_code}", 3)
            return [
                {"tool": "fx.rate", "args": {"base": base_code, "target": target_code, "amount": amount}},
                {"tool": "web.search", "args": search_args},
            ]

        def handle_correction(p, m):
            if not any(token in p for token in [
                "verifique", "verificar", "confira", "corrija", "corrigir", "diferente", "errado", "desatual", "atualize", "atualizar", "não está certo", "nao está certo", "nao esta certo", "não esta certo"
            ]):
                return None

            calls: list[dict] = []
            if self._last_asset:
                calls.append({
                    "tool": "crypto.price",
                    "args": {"asset": self._last_asset, "vs_currencies": list(self._last_price_vs)},
                })
            if getattr(self, "_last_fx_request", None):
                calls.append({
                    "tool": "fx.rate",
                    "args": dict(self._last_fx_request),
                })

            base_query = self._last_search_base_query or self._last_search_query
            site_filters = list(getattr(self, "_last_search_site_filters", []))
            if base_query:
                query_extra = base_query
                if all(keyword not in query_extra for keyword in ["atualizado", "atualização", "atualizacao", "hoje"]):
                    query_extra = f"{query_extra} atualizado hoje"
                search_args = prepare_search_query(p, query_extra, 4, site_filters)
                calls.append({"tool": "web.search", "args": search_args})

            return calls or None

        def handle_fs_path(p, m):
            return {"directory" if "list" in m.group(0) else "path": m.group("path")}
        self.heuristic_rules = [
            {
                "pattern": re.compile(r"diferen\w+\s+de\s+(?:hor(a|ario|ário)|fuso)\s+entre\s+([^,.;!?]+?)\s+e\s+([^,.;!?]+)"),
                "handler": handle_time_diff, "tool": "sys.time.diff"
            },
            {
                "pattern": re.compile(r"\b(data|hora|horas|horario|horário|horários)\b[\s\S]*?(?:\sem|\sno|\sna|\sde|\sdo|\sda)\s+([^\n,.;!?]+?)(?:\?|$)"),
                "handler": handle_time_loc, "tool": "sys.time"
            },
            {
                "keywords": [("data", "hora"), ("países", "paises")],
                "any_keywords": ["américa", "america", "caribe", "europa", "áfrica", "africa", "ásia", "asia", "oceania", "antártica", "antartica"],
                "handler": handle_time_bulk, "tool": "sys.time.bulk"
            },
            {
                "keywords": [("países", "paises")],
                "any_keywords": ["américa", "america", "caribe", "europa", "áfrica", "africa", "ásia", "asia", "oceania", "antártica", "antartica"],
                "not_keywords": [("data", "hora")],
                "handler": handle_geo_countries, "tool": "geo.countries"
            },
            {
                "pattern": re.compile(r"(?:quanto\s+custa|qual\s+é\s+o\s+valor|valor\s+(?:do|de)|cotação\s+(?:do|de)|cotacao\s+(?:do|de)|preço\s+(?:do|de)|preco\s+(?:do|de))[\s\S]*?(d[oó]lar|usd|real|brl|euro|eur|libra|gbp|iene|yen|jpy)"),
                "handler": handle_fx_convert,
                "tool": "fx.rate"
            },
            {
                "pattern": re.compile(r"(?:qual\s+é\s+o\s+valor|valor|preço|cotação)\s+(?:do|da|de)\s+([^\n,.;!?]+?)(?:\?|$)"),
                "handler": handle_price_search, 
                "tool": "web.search"
            },
            {
                "pattern": re.compile(r"(verifi\w+|confir\w+|corrig\w+|atualiz\w+|errad\w+|diferent\w+|não\s+está\s+certo|nao\s+esta\s+certo)"),
                "handler": handle_correction,
                "tool": "web.search"
            },
            {
                "keywords": [("pesquisa", "pesquise", "pesquisar", "buscar"), ("internet", "web")],
                "handler": handle_web_search, "tool": "web.search"
            },
            {"keywords": [("ferramentas",), ("listar", "liste", "quais")], "handler": lambda p, m: {}, "tool": "help.tools"},
            {"keywords": ["continentes", ("quais", "nomes", "lista", "listar", "quantos")], "handler": lambda p, m: {"verify_online": "verificar" in p}, "tool": "geo.continents"},
            {
                "pattern": re.compile(r"(?:fs\.list|listar\s+arquivos|lista\s+arquivos|list\s+arquivos)\s+(?:em|de|do|da)\s+(?P<path>/[^\s]+)"),
                "handler": handle_fs_path, "tool": "fs.list"
            },
            {
                "pattern": re.compile(r"(?:ler|leia|abrir)\s+(?P<path>/[^\s]+)"),
                "handler": handle_fs_path, "tool": "fs.read"
            },
        ]

    def _heuristic_tool_calls(self, prompt: str) -> list[dict]:
        if not hasattr(self, "heuristic_rules"):
            self._setup_heuristic_rules()

        p = (prompt or "").lower().strip()

        for rule in self.heuristic_rules:
            m = None
            if pattern := rule.get("pattern"):
                m = pattern.search(p)
                if not m:
                    continue
            
            if keywords := rule.get("keywords"):
                if not all(any(k in p for k in (kw if isinstance(kw, tuple) else (kw,))) for kw in keywords):
                    continue
            
            if any_keywords := rule.get("any_keywords"):
                if not any(k in p for k in any_keywords):
                    continue

            if not_keywords := rule.get("not_keywords"):
                if any(all(k in p for k in (kw if isinstance(kw, tuple) else (kw,))) for kw in not_keywords):
                    continue

            args = rule["handler"](p, m)
            if args is None:
                continue
            if isinstance(args, list):
                calls: list[dict] = []
                for item in args:
                    if not isinstance(item, dict):
                        calls.append({"tool": rule["tool"], "args": item})
                        continue
                    tool_name = item.get("tool") or rule["tool"]
                    calls.append({"tool": tool_name, "args": item.get("args") or {}})
                if calls:
                    return calls
                continue
            return [{"tool": rule["tool"], "args": args}]

        return []

    def _extract_regions_from_prompt(self, p: str) -> list[str]:
        regions: list[str] = []
        region_map = {
            "América do Norte": ["américa do norte", "america do norte", "north america"],
            "América Central": ["américa central", "america central", "central america"],
            "América do Sul": ["américa do sul", "america do sul", "south america"],
            "Caribe": ["caribe", "caribbean"],
            "Europa": ["europa", "europe"],
            "África": ["áfrica", "africa"],
            "Ásia": ["ásia", "asia"],
            "Oceania": ["oceania"],
            "Antártica": ["antártica", "antartica", "antarctica"],
        }
        for region_name, aliases in region_map.items():
            for alias in aliases:
                if alias in p:
                    if region_name not in regions:
                        regions.append(region_name)
        return regions

    def _strip_internal(self, text: str) -> str:
        import re

        # Remove tool_call / tool_result blocks
        text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text)
        text = re.sub(r"<tool_result>[\s\S]*?</tool_result>", "", text)
        return text.strip()

    def _run_heuristic_shortcuts(self, prompt: str) -> str | None:
        """Executa chamadas de ferramentas heurísticas e retorna uma resposta final se um atalho for encontrado."""
        forced_calls = self._heuristic_tool_calls(prompt)
        for c in forced_calls:
            try:
                if ASSISTANT_VERBOSE:
                    print(f"[heuristic_tool_call] {c['tool']} args={json.dumps(c['args'], ensure_ascii=False)}")
                # Show the model that a tool was called
                self.add_assistant(f"<tool_call>{json.dumps(c, ensure_ascii=False)}</tool_call>")
                result = call_tool(c["tool"], c.get("args") or {})
                if ASSISTANT_VERBOSE:
                    preview = json.dumps(result, ensure_ascii=False)
                    if len(preview) > 800:
                        preview = preview[:800] + "…"
                    print(f"[tool_result] {preview}")
                self.add_user(format_tool_result(result))
                # Atalhos: formata a resposta final imediatamente para certas ferramentas.
                if c.get("tool") == "sys.time" and isinstance(result, dict) and result.get("ok"):
                    loc = (c.get("args") or {}).get("location") or (c.get("args") or {}).get("tz")
                    prefixo = f"em {loc}" if loc else "atual"
                    texto = result.get("texto") or result.get("iso")
                    tz = result.get("tz")
                    final = f"Data e hora {prefixo}: {texto} ({tz})."
                    # self.add_assistant(final) # Let the loop decide the final answer
                    return final
                if c.get("tool") == "geo.countries" and isinstance(result, dict) and result.get("ok"):
                    parts: list[str] = []
                    for reg in result.get("regions") or []:
                        if not isinstance(reg, dict) or not reg.get("ok"):
                            continue
                        nome = reg.get("region")
                        paises = reg.get("countries") or []
                        parts.append(f"{nome}: {len(paises)} países\n- " + "\n- ".join(paises))
                    final = "\n\n".join(parts) if parts else "Não encontrei países para as regiões especificadas."
                    self.add_assistant(final)
                    return final
                if c.get("tool") == "help.tools" and isinstance(result, dict) and result.get("ok"):
                    tools_list = result.get("tools") or []
                    if not tools_list:
                        return "Nenhuma ferramenta encontrada."
                    lines = ["Ferramentas disponíveis:"]
                    for tool_spec in tools_list:
                        params = ", ".join(tool_spec.get("params", {}).keys())
                        lines.append(f"- **{tool_spec['name']}**: {tool_spec['description']} `{{{params}}}`")
                    final = "\n".join(lines)
                    return final
                if c.get("tool") == "geo.continents" and isinstance(result, dict) and result.get("ok"):
                    nomes = result.get("continents") or []
                    total = result.get("count")
                    final = f"Os continentes são ({total}):\n- " + "\n- ".join(nomes)
                    self.add_assistant(final)
                    return final
                # Atalho para fs.list: formata a saída diretamente para evitar sobrecarregar o modelo
                if c.get("tool") == "fs.list" and isinstance(result, dict) and result.get("ok"):
                    items = result.get("items", [])
                    directory = result.get("directory", "o diretório solicitado")
                    if not items:
                        return f"Nenhum arquivo encontrado em {directory}."
                    
                    limit = 200
                    truncated = len(items) > limit
                    final = f"Arquivos em {directory}:\n- " + "\n- ".join(items[:limit])
                    if truncated:
                        final += f"\n\n(e mais {len(items) - limit} outros...)"
                    return final
                # Heurística de busca: após web.search bem-sucedido, tentar buscar a primeira URL
                if c.get("tool") == "web.search" and isinstance(result, dict) and result.get("ok"):
                    results = result.get("results") or []
                    if not results:
                        final = "Não encontrei resultados relevantes na busca."  # noqa
                        self.add_assistant(final)
                        return final

                    seen_urls: set[str] = set()
                    ordered_urls: list[str] = []
                    ordered_items: list[dict] = []
                    limit = int((c.get("args") or {}).get("limit", 3) or 3)
                    for item in results:
                        if not isinstance(item, dict):
                            continue
                        url = item.get("url")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        ordered_urls.append(url)
                        ordered_items.append(item)
                        if len(ordered_urls) >= limit:
                            break

                    if not ordered_urls:
                        final = "Não encontrei URLs acessíveis nos resultados da busca."
                        self.add_assistant(final)
                        return final

                    c2 = {"tool": "web.get_many", "args": {"urls": ordered_urls}}
                    if ASSISTANT_VERBOSE:
                        print(f"[heuristic_tool_call] {c2['tool']} args={json.dumps(c2['args'], ensure_ascii=False)}")
                    self.add_assistant(f"<tool_call>{json.dumps(c2, ensure_ascii=False)}</tool_call>")
                    r2 = call_tool("web.get_many", {"urls": ordered_urls})
                    if ASSISTANT_VERBOSE:
                        preview2 = json.dumps(r2, ensure_ascii=False)
                        if len(preview2) > 800:
                            preview2 = preview2[:800] + "…"
                        print(f"[tool_result] {preview2}")
                    self.add_user(format_tool_result(r2))
                    self._last_search_urls = list(ordered_urls)
                    self._last_search_limit = limit

                    fontes: list[str] = []
                    for idx, item in enumerate(ordered_items, 1):
                        url = item.get("url") or ""
                        title = (item.get("title") or url or "Fonte sem título").strip()
                        snippet = (item.get("snippet") or "").strip()
                        if len(snippet) > 280:
                            snippet = snippet[:277] + "…"
                        fontes.append(
                            f"{idx}. {title}\n   URL: {url}\n   Snippet: {snippet or '—'}"
                        )
                    if fontes:
                        resumo_busca = "Fontes pesquisadas:\n" + "\n".join(fontes)
                        self.add_user(resumo_busca)

                    guidance = (
                        "Com base nas páginas coletadas acima, produza uma resposta em Português do Brasil, "
                        "resumindo as informações principais e citando explicitamente as fontes relevantes "
                        "pelo respectivo URL. Se as páginas não tiverem dados suficientes, explique o que falta."
                    )
                    self.add_user(guidance)
                    # Deixe o modelo resumir com base nas páginas múltiplas
                    return "continue"

                if c.get("tool") == "crypto.price" and isinstance(result, dict):
                    if result.get("ok"):
                        asset = result.get("asset") or (c.get("args") or {}).get("asset") or "criptoativo"
                        prices = result.get("prices") or {}
                        changes = result.get("changes_24h") or {}
                        vs_list = result.get("vs_currencies") or self._last_price_vs
                        if isinstance(vs_list, list):
                            self._last_price_vs = [str(v).lower() for v in vs_list]
                        self._last_asset = asset
                        lines: list[str] = []
                        for fiat, price in prices.items():
                            if isinstance(price, (int, float)):
                                price_str = f"{price:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                            else:
                                price_str = str(price)
                            change = changes.get(fiat)
                            if isinstance(change, (int, float)):
                                lines.append(f"{fiat.upper()}: {price_str} ({change:+.2f}% em 24h)")
                            else:
                                lines.append(f"{fiat.upper()}: {price_str}")
                        updated = result.get("last_updated_iso")
                        hours_diff = result.get("last_updated_hours_ago")
                        summary = [f"Dados em tempo real via CoinGecko para {asset}:"]
                        if lines:
                            summary.extend(f"- {line}" for line in lines)
                        else:
                            summary.append("- Nenhum preço disponível nesta consulta.")
                        if updated:
                            line = f"Última atualização (UTC): {updated}"
                            if isinstance(hours_diff, (int, float)):
                                line += f" (~{hours_diff:.1f}h atrás)"
                                if hours_diff >= 3:
                                    line += " [verifique fontes adicionais]"
                            summary.append(line)
                        summary.append("Fonte: https://www.coingecko.com")
                        self.add_user("\n".join(summary))
                    else:
                        self.add_user("Falha ao consultar a CoinGecko; tentando fontes alternativas.")
                    continue

                if c.get("tool") == "fx.rate" and isinstance(result, dict):
                    if result.get("ok"):
                        base = result.get("base") or (c.get("args") or {}).get("base") or "USD"
                        target = result.get("target") or (c.get("args") or {}).get("target") or "BRL"
                        amount = result.get("amount") or (c.get("args") or {}).get("amount") or 1
                        rate = result.get("rate")
                        converted = result.get("converted")
                        hours_diff = result.get("last_updated_hours_ago")
                        self._last_fx_request = {"base": base, "target": target, "amount": amount}
                        summary = ["Conversão em tempo real (exchangerate.host):"]
                        if isinstance(converted, (int, float)):
                            conv_str = f"{converted:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                        else:
                            conv_str = str(converted)
                        if isinstance(amount, (int, float)):
                            amount_str = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
                        else:
                            amount_str = str(amount)
                        summary.append(f"- {amount_str} {base} = {conv_str} {target}")
                        if isinstance(rate, (int, float)):
                            summary.append(f"- 1 {base} = {rate:,.4f} {target}")
                        updated = result.get("last_updated_iso") or result.get("date")
                        if updated:
                            line = f"Dados de {updated}"
                            if isinstance(hours_diff, (int, float)):
                                line += f" (~{hours_diff:.1f}h atrás)"
                                if hours_diff >= 3:
                                    line += " [recomendo confirmar novamente]"
                            summary.append(line)
                        summary.append("Fonte: https://api.exchangerate.host/convert")
                        self.add_user("\n".join(summary))
                    else:
                        self.add_user("Não foi possível obter a cotação em tempo real; confira outras fontes.")
                    continue

                if c.get("tool") == "sys.time.bulk" and isinstance(result, dict) and result.get("ok"):
                    lines: list[str] = []  # noqa
                    items = result.get("items") or []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        if not it.get("ok"):
                            lines.append(f"- {it.get('country')}: erro ({it.get('error')})")
                        else:
                            lines.append(f"- {it.get('country')}: {it.get('texto')} ({it.get('tz')})")
                    header = "Data e hora por país:" if lines else "Nenhum país processado."
                    final = header + "\n" + "\n".join(lines)
                    self.add_assistant(final)
                    return final
            except Exception:
                # Se a chamada da ferramenta heurística falhar, o loop principal pode tentar se recuperar.
                pass
        
        # Se uma heurística foi acionada, mas não gerou um atalho de resposta,
        # o loop principal deve continuar a partir do estado atual.
        return "continue" if forced_calls else None

    def run(self, prompt: str) -> str:
        # Tenta executar atalhos heurísticos primeiro.
        self.add_user(prompt)

        shortcut_answer = self._run_heuristic_shortcuts(prompt)
        if shortcut_answer is not None and shortcut_answer != "continue":
            return shortcut_answer

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
            # Se o caminho for arquivo, guardamos o diretório pai para cobrir arquivos irmãos
            if target.is_dir():
                self._approved_paths.add(target)
            else:
                self._approved_paths.add(target.parent)

        expecting_tools = expects_tool_use(prompt)
        tool_success = shortcut_answer == "continue"

        retries = 0
        for _ in range(12):
            model_response = self.step()

            if isinstance(model_response, Iterable) and not isinstance(model_response, dict):
                parts: List[str] = []
                for chunk in model_response:
                    part = chunk.get("message", {}).get("content", "") if isinstance(chunk, dict) else ""
                    if part:
                        parts.append(part)
                full_response_content = "".join(parts)
            elif isinstance(model_response, dict):
                full_response_content = model_response.get("message", {}).get("content", "")
            else:
                full_response_content = ""

            self.add_assistant(full_response_content)

            tool_call = extract_tool_call(full_response_content)
            if not tool_call:
                if expecting_tools and not tool_success and retries < 2:
                    retries += 1
                    if ASSISTANT_VERBOSE:
                        print("[info] No tool_call detected; nudging model to use tools…")
                    nudge_msg = (
                        "Use estritamente a sintaxe <tool_call>{...}</tool_call> para executar as ações (fs.*, web.*, edit.*, shell.*, git.*). "
                        "Não forneça comandos de shell genéricos."
                    )
                    self.add_user(nudge_msg)
                    continue
                return self._strip_internal(full_response_content)

            name = tool_call.get("tool")
            args = tool_call.get("args") or {}
            if ASSISTANT_VERBOSE:
                print(f"[tool_call] {name} args={json.dumps(args, ensure_ascii=False)}")

            result = call_tool(name, args)

            if isinstance(result, dict) and result.get("confirm_required"):
                info = {
                    "action": result.get("action"),
                    "path": result.get("path"),
                    "reason": result.get("reason"),
                    "args": result.get("args"),
                }
                path_for_prompt = info.get("path")
                if is_path_approved(path_for_prompt):
                    rerun_args = dict(args)
                    rerun_args["__allow_outside_root"] = True
                    try:
                        result = call_tool(name, rerun_args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                else:
                    print(f"[confirm] Esta operação requer aprovação: {json.dumps(info, ensure_ascii=False)}")
                    try:
                        resp = input("Permitir esta ação fora da raiz? [s/N]: ").strip().lower()
                    except EOFError:
                        resp = "n"
                    if resp in ("s", "sim", "y", "yes"):
                        remember_approval(path_for_prompt)
                        rerun_args = dict(args)
                        rerun_args["__allow_outside_root"] = True
                        try:
                            result = call_tool(name, rerun_args)
                        except Exception as exc:
                            result = {"ok": False, "error": str(exc)}
                    else:
                        result = {"ok": False, "error": "user_denied"}

            if isinstance(result, dict):
                if ASSISTANT_VERBOSE:
                    preview = json.dumps(result, ensure_ascii=False)
                    if len(preview) > 800:
                        preview = preview[:800] + "…"
                    print(f"[tool_result] {preview}")

                is_ok = result.get("ok", True)
                error_code = str(result.get("error")) if not is_ok else ""

                if not is_ok and error_code != "user_denied":
                    error_feedback = (
                        f"Erro: A chamada da ferramenta falhou: {error_code}. Verifique os argumentos e as ferramentas disponíveis e tente novamente."
                    )
                    self.add_user(error_feedback)
                    if retries < 2:
                        retries += 1
                        self.add_user(format_tool_result(result))
                        continue
                user_msg = format_tool_result(result)
                self.add_user(user_msg)
                if not is_ok:
                    if error_code == "user_denied":
                        expecting_tools = False
                    continue
                tool_success = True
            else:
                user_msg = format_tool_result({"ok": True, "result": result})
                self.add_user(user_msg)

        # Save to history
        try:
            with HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "model": self.model,
                    "messages": self.messages,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # Return last assistant content, sanitized from internal tags

        content = self.messages[-1]["content"] if self.messages and self.messages[-1]["role"] == "assistant" else ""
        return self._strip_internal(content or "")
