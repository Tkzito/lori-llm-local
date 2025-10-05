from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Iterator

import requests

try:
    # Optional dependency. If present, we use the official client.
    from ollama import Client as _OllamaPyClient  # type: ignore
    _HAS_OLLAMA_PY = True
except Exception:
    _HAS_OLLAMA_PY = False

# Defaults and timeouts
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
TIMEOUT_SECS = float(os.getenv("ASSISTANT_TIMEOUT_SECS", "30"))

class OllamaClient:
    def __init__(self, base_url: str | None = None, headers: Dict[str, str] | None = None):
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        self.headers = headers or {}
        self.session = requests.Session()

        # If python package available, prepare a client instance
        self._py_client = None
        if _HAS_OLLAMA_PY:
            try:
                self._py_client = _OllamaPyClient(host=self.base_url + "/", headers=self.headers)
            except Exception:
                self._py_client = None

    def _normalize(self, resp: Dict[str, Any]) -> Dict[str, Any]:
        # Ensure the Agent expects {"message": {"content": "..."}}
        if isinstance(resp, dict) and "message" in resp and isinstance(resp["message"], dict):
            return resp
        # Some clients may return {"content": "..."}
        content = resp.get("content") if isinstance(resp, dict) else str(resp)
        return {"message": {"content": content or ""}}

    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Dict[str, Any]:
        """Synchronous, non-streaming chat by default.

        Streaming is disabled for CLI responsiveness. Always return a single
        normalized dict {"message": {"content": str}}.
        """
        # Prefer python client if available and working
        if self._py_client is not None:
            try:
                resp = self._py_client.chat(model=model, messages=messages, stream=False)
                return self._normalize(resp)
            except Exception:
                # Fall back to HTTP
                pass

        # HTTP fallback to Ollama REST API (non-streaming)
        url = f"{self.base_url}/api/chat"
        payload = {"model": model, "messages": messages, "stream": False}
        try:
            r = self.session.post(url, json=payload, headers=self.headers, timeout=TIMEOUT_SECS)
            r.raise_for_status()
            return self._normalize(r.json())
        except requests.exceptions.Timeout:
            return {"message": {"content": "[erro] Timeout ao consultar o Ollama. Tente novamente."}}
        except requests.exceptions.RequestException as e:
            return {"message": {"content": f"[erro] Não foi possível conectar ao Ollama: {e}"}}
