from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Iterator, Union

import requests

try:
    # Optional dependency. If present, we use the official client.
    from ollama import Client as _OllamaPyClient, ResponseError  # type: ignore
    _HAS_OLLAMA_PY = True
except ImportError:
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
                self._py_client = _OllamaPyClient(host=self.base_url, headers=self.headers)
            except Exception:
                self._py_client = None

    def _normalize(self, chunk: Any) -> Dict[str, Any]:
        """Normalizes a chunk from either the Python client or HTTP response into the agent's expected format."""
        content = ""
        if isinstance(chunk, dict):
            # Handles dict-based responses (from direct HTTP call or older client versions)
            if "message" in chunk and isinstance(chunk.get("message"), dict):
                content = chunk["message"].get("content", "")
            elif "content" in chunk:
                content = chunk.get("content", "")
        elif hasattr(chunk, "message") and hasattr(chunk.message, "content"):
            # Handles responses from the official ollama-python client (which are objects)
            content = chunk.message.content or ""
        
        return {"message": {"content": content}}

    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        """
        Performs a chat completion, supporting both streaming and non-streaming modes.
        """
        # 1. Use official Python client if available
        if self._py_client:
            try:
                response = self._py_client.chat(model=model, messages=messages, stream=stream)
                if not stream:
                    return self._normalize(response)
                
                def stream_adapter():
                    for chunk in response:
                        yield self._normalize(chunk)
                return stream_adapter()
            except ResponseError as e:
                # Handle specific client errors, like model not found
                err_msg = f"[erro] O modelo '{model}' não foi encontrado. Verifique se ele está disponível no Ollama. Detalhe: {e.error}"
                err = {"message": {"content": err_msg}}
                return err if not stream else iter([err])
            except Exception:
                # Fallback to HTTP if the python client fails for other reasons
                pass

        # 2. Fallback to direct HTTP requests
        url = f"{self.base_url}/api/chat"
        payload = {"model": model, "messages": messages, "stream": stream}
        
        try:
            r = self.session.post(url, json=payload, headers=self.headers, timeout=TIMEOUT_SECS, stream=stream)
            r.raise_for_status()

            if not stream:
                return self._normalize(r.json())

            def http_stream_generator():
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        yield self._normalize(data)
                    except json.JSONDecodeError:
                        continue
            return http_stream_generator()

        except requests.exceptions.Timeout:
            err = {"message": {"content": "[erro] Timeout ao consultar o Ollama. Tente novamente."}}
            return err if not stream else iter([err])
        except requests.exceptions.RequestException as e:
            # Check for 404, which likely means model not found
            if e.response is not None and e.response.status_code == 404:
                err_msg = f"[erro] O modelo '{model}' não foi encontrado. Verifique se ele está disponível no Ollama."
            else:
                err_msg = f"[erro] Não foi possível conectar ao Ollama: {e}"
            err = {"message": {"content": err_msg}}
            return err if not stream else iter([err])
