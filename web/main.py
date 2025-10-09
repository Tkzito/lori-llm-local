from __future__ import annotations

import json
import os
import re
import unicodedata
from uuid import uuid4
from pathlib import Path
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from assistant_cli.config import HISTORY_PATH, UPLOADS_DIR

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from assistant_cli.agent import Agent


class ChatRequest(BaseModel):
    message: str
    agent_mode: bool = False
    history: list[dict[str, str]] | None = None
    context_files: list[str] | None = None


class RemoveFilesRequest(BaseModel):
    paths: list[str]


app = FastAPI(
    title="Lori Web UI",
    description="Interface web para interagir com a assistente Lori.",
    version="1.0.0",
)

# Monta o diretório 'static' para servir os arquivos HTML, CSS e JS
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve a página principal da interface."""
    return (Path(__file__).parent / "static" / "index.html").read_text()


@app.get("/history")
async def get_history():
    """Retorna um resumo de todas as conversas do histórico."""
    history_files = sorted(
        Path(HISTORY_PATH.parent).glob("history-*.jsonl"),
        reverse=True
    )

    all_conversations = []
    for file_path in history_files:
        try:
            lines = file_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines:
                if line.strip():
                    all_conversations.append(json.loads(line))
        except Exception:
            continue

    # Ordena todas as conversas pela data, da mais recente para a mais antiga
    all_conversations.sort(key=lambda x: x.get("ts", ""), reverse=True)

    history = []
    for entry in all_conversations:
        # Pega a primeira mensagem do usuário como título
        title = "Nova Conversa"
        for msg in entry.get("messages", []):
            if msg.get("role") == "user":
                title = msg.get("content", "Nova Conversa").strip()
                break

        history.append({
            "ts": entry.get("ts"),
            "title": title,
        })

    return {"history": history}


@app.get("/history/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Busca e retorna uma conversa específica pelo seu ID (timestamp)."""
    history_files = sorted(
        Path(HISTORY_PATH.parent).glob("history-*.jsonl"),
        reverse=True
    )

    def _strip_internal_markers(text: str) -> str:
        import re
        text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text or "")
        text = re.sub(r"<tool_result>[\s\S]*?</tool_result>", "", text)
        return text.strip()

    for file_path in history_files:
        try:
            for line in file_path.read_text(encoding="utf-8").strip().splitlines():
                entry = json.loads(line)
                if entry.get("ts") == conversation_id:
                    # Filtra a mensagem de sistema e limpa marcadores internos
                    messages = [
                        {"role": msg.get("role"), "content": _strip_internal_markers(msg.get("content", ""))}
                        for msg in entry.get("messages", [])
                        if msg.get("role") != "system" and _strip_internal_markers(msg.get("content", ""))
                    ]
                    return {"ok": True, "messages": messages}
        except Exception:
            continue

    return {"ok": False, "error": "Conversa não encontrada."}


@app.delete("/history/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Encontra e deleta uma conversa específica do seu arquivo de histórico."""
    history_files = Path(HISTORY_PATH.parent).glob("history-*.jsonl")
    for file_path in history_files:
        try:
            lines = file_path.read_text(encoding="utf-8").strip().splitlines()
            updated_lines = []
            found = False
            for line in lines:
                entry = json.loads(line)
                if entry.get("ts") == conversation_id:
                    found = True
                else:
                    updated_lines.append(line)
            
            if found:
                if updated_lines:
                    file_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
                else:
                    os.remove(file_path) # Remove o arquivo se estiver vazio
                return {"ok": True}
        except Exception:
            continue
    return {"ok": False, "error": "Conversa não encontrada para exclusão."}


@app.delete("/history")
async def delete_all_history():
    """Deleta todos os arquivos de histórico."""
    history_files = Path(HISTORY_PATH.parent).glob("history-*.jsonl")
    for file_path in history_files:
        os.remove(file_path)
    return {"ok": True}


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Recebe e salva arquivos na pasta de uploads, extraindo texto de PDFs se possível."""
    saved_files = []
    for file in files:
        try:
            original_name = file.filename or "arquivo"
            normalized = unicodedata.normalize("NFKD", original_name)
            normalized = normalized.encode("ascii", "ignore").decode("ascii") or "arquivo"
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-") or "arquivo"
            unique_suffix = uuid4().hex[:10]

            # Se for PDF e a biblioteca estiver disponível, extrai o texto
            if file.filename.lower().endswith(".pdf") and PYMUPDF_AVAILABLE:
                doc = fitz.open(stream=await file.read(), filetype="pdf")
                text = "".join(page.get_text() for page in doc)
                doc.close()
                
                new_filename = f"{Path(safe_name).stem}-{unique_suffix}.txt"
                file_path = UPLOADS_DIR / new_filename
                file_path.write_text(text, encoding="utf-8")
                size_bytes = file_path.stat().st_size
                saved_files.append({
                    "display_name": original_name,
                    "path": str(file_path),
                    "size": size_bytes,
                    "stored_name": file_path.name,
                })
            else: # Para outros arquivos (ex: .txt), salva diretamente
                extension = "".join(Path(safe_name).suffixes) or ""
                stem = Path(safe_name).stem or "arquivo"
                new_filename = f"{stem}-{unique_suffix}{extension}"
                file_path = UPLOADS_DIR / new_filename
                with open(file_path, "wb") as buffer:
                    buffer.write(await file.read())
                size_bytes = file_path.stat().st_size
                saved_files.append({
                    "display_name": original_name,
                    "path": str(file_path),
                    "size": size_bytes,
                    "stored_name": file_path.name,
                })
        except Exception as e:
            return {"ok": False, "error": f"Falha ao processar {file.filename}: {e}"}
    return {"ok": True, "files": saved_files}


@app.post("/upload/remove")
async def remove_uploaded_files(request: RemoveFilesRequest):
    """Remove arquivos previamente enviados para o diretório de uploads."""
    deleted: list[str] = []
    failures: list[dict[str, str]] = []
    uploads_root = UPLOADS_DIR.resolve()

    for raw_path in request.paths:
        try:
            if not raw_path:
                continue
            raw_path_str = str(raw_path)
            if os.path.isabs(raw_path_str):
                target_path = Path(raw_path_str).resolve()
            else:
                target_path = (UPLOADS_DIR / raw_path_str).resolve()
            if uploads_root not in target_path.parents and target_path != uploads_root:
                failures.append({"path": raw_path_str, "error": "path_outside_uploads"})
                continue
            if target_path.exists():
                if target_path.is_dir():
                    failures.append({"path": raw_path_str, "error": "directories_not_supported"})
                    continue
                target_path.unlink()
                deleted.append(str(target_path))
            else:
                failures.append({"path": raw_path_str, "error": "not_found"})
        except Exception as exc:
            failures.append({"path": raw_path_str, "error": str(exc)})

    status_ok = not failures
    payload = {"ok": status_ok, "deleted": deleted, "errors": failures}
    status_code = 200 if status_ok else 207
    return JSONResponse(status_code=status_code, content=payload)


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            request = ChatRequest(**data)

            agent = Agent(interactive=False)
            # O histórico de mensagens da UI é usado para dar contexto ao agente
            if request.history:
                for msg in request.history:
                    agent.add_user(msg["content"]) if msg["role"] == "user" else agent.add_assistant(msg["content"])
            
            # Adiciona o contexto dos arquivos ao agente
            if request.context_files:
                agent.add_context_files(request.context_files)
            
            response_generator = agent.run_stream(request.message, agent_mode=request.agent_mode)

            # Itera sobre o gerador e lida com a confirmação do usuário
            while True:
                try:
                    event = next(response_generator)
                    await websocket.send_json(event)
                    if event.get("type") == "confirm_required":
                        user_response = await websocket.receive_json()
                        response_generator.send(user_response) # Envia a resposta do usuário de volta para o gerador
                except StopIteration:
                    break

    except WebSocketDisconnect:
        print("[WEBSOCKET] Cliente desconectado.")
    except Exception as e:
        print(f"[WEBSOCKET_ERROR] Erro: {e}")
        await websocket.send_json({"type": "error", "content": f"Ocorreu um erro no servidor: {e}"})
