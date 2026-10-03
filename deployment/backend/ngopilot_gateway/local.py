"""Loopback-only transport for the original NGOPilot Chatbot and ACP runtime.

This is a single-owner local launcher, not the production account/GCS gateway.
Conversation, planning and tool execution stay in the existing Rust Agent. This
module only serves its renderer, uploads, verified artifacts and ACP transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from websockets.asyncio.client import connect

from .acp_proxy import MAX_ACP_MESSAGE_BYTES, browser_message, isolate_client_request
from .config import Settings
from .processes import TenantProcessManager
from .storage import PLACEHOLDER_PATTERN, parse_placeholder, safe_filename

LOCAL_OWNER = UUID("dc5aab2c-7220-4ef3-bf54-9386b9d95412")
UPLOAD_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".flac",
    ".mp4",
    ".aac",
}


def local_origin(value: str | None, public_url: str) -> bool:
    return value is None or value.rstrip("/") == public_url.rstrip("/")


def create_local_app(settings: Settings | None = None, frontend: Path | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env != "local":
        raise ValueError("The local launcher requires APP_ENV=local")
    from urllib.parse import urlsplit

    parsed = urlsplit(settings.public_api_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("The local launcher must be published on HTTP loopback only")
    frontend = frontend or Path(os.environ.get("NGOPILOT_FRONTEND_DIR", "/opt/ngopilot/frontend"))
    manager = TenantProcessManager(settings)
    root = manager.tenant_root(LOCAL_OWNER)
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
    cookie = secrets.token_urlsafe(32)
    tickets: dict[str, float] = {}
    downloads: dict[str, tuple[Path, float]] = {}
    upload_events: dict[str, asyncio.Event] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await manager.stop_all()

    app = FastAPI(title="NGOPilot Agent · 本機", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.processes = manager
    from .workflow_routes import register_workflow_routes

    register_workflow_routes(app, settings, lambda: LOCAL_OWNER)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if (
            request.headers.get("host") != parsed.netloc
            or not local_origin(request.headers.get("origin"), settings.public_api_url)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Local same-origin access required"}, status_code=403)
        public_paths = {"/api/auth/me", "/api/runtime", "/healthz"}
        if request.url.path.startswith("/api/") and request.url.path not in public_paths:
            if not secrets.compare_digest(request.cookies.get("ngopilot.local", ""), cookie):
                return JSONResponse(
                    {"detail": "Open NGOPilot in this browser first"}, status_code=401
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "mode": "local-agent"}

    @app.get("/api/runtime")
    async def runtime_config():
        return {
            "GOOSE_DEFAULT_PROVIDER": settings.goose_provider,
            "GOOSE_DEFAULT_MODEL": settings.goose_model,
            "GOOSE_WORKING_DIR": str(root),
            "NGOPILOT_LOCAL": True,
            "NGOPILOT_AGENT_HOME": True,
            "NGOPILOT_SCHEDULER_ENABLED": bool(os.getenv("NGOPILOT_SCHEDULER_URL")),
        }

    @app.get("/api/auth/me")
    async def owner():
        response = JSONResponse({"id": str(LOCAL_OWNER), "name": "本機使用者", "local": True})
        response.set_cookie("ngopilot.local", cookie, httponly=True, samesite="strict")
        return response

    @app.post("/api/auth/logout")
    async def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie("ngopilot.local")
        return response

    @app.post("/api/ws-tickets")
    async def ticket():
        now = monotonic()
        for key, expiry in list(tickets.items()):
            if expiry < now:
                tickets.pop(key, None)
        value = secrets.token_urlsafe(32)
        tickets[value] = now + 60
        return {
            "url": settings.public_api_url.replace("http://", "ws://", 1) + "/acp?ticket=" + value
        }

    @app.post("/api/uploads", status_code=201)
    async def upload(
        file: UploadFile = File(...), upload_id: str = Form(...), placeholder: str = Form(...)
    ):
        try:
            ident, filename = parse_placeholder(placeholder)
            if str(ident) != upload_id or filename != file.filename:
                raise ValueError("Upload identity mismatch")
            if Path(filename).suffix.lower() not in UPLOAD_SUFFIXES:
                raise ValueError("Unsupported attachment type")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        folder = uploads / str(ident)
        if folder.exists():
            raise HTTPException(409, "This upload already exists")
        folder.mkdir(mode=0o700)
        path = folder / safe_filename(filename)
        event = upload_events.setdefault(placeholder, asyncio.Event())
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "Attachment exceeds upload limit")
                    digest.update(chunk)
                    output.write(chunk)
            path.chmod(0o600)
            metadata = {
                "path": str(path),
                "filename": filename,
                "placeholder": placeholder,
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            }
            (folder / "upload.json").write_text(json.dumps(metadata), encoding="utf-8")
            return {key: value for key, value in metadata.items() if key != "path"}
        except Exception:
            path.unlink(missing_ok=True)
            (folder / "failed").touch()
            raise
        finally:
            await file.close()
            event.set()

    async def resolve(value):
        if isinstance(value, dict):
            return {key: await resolve(child) for key, child in value.items()}
        if isinstance(value, list):
            return [await resolve(child) for child in value]
        if not isinstance(value, str):
            return value
        for placeholder in set(PLACEHOLDER_PATTERN.findall(value)):
            ident, _ = parse_placeholder(placeholder)
            folder = uploads / str(ident)
            metadata = folder / "upload.json"
            if not metadata.is_file():
                event = upload_events.setdefault(placeholder, asyncio.Event())
                try:
                    await asyncio.wait_for(event.wait(), settings.upload_resolve_timeout_seconds)
                except TimeoutError as error:
                    raise ValueError("附件仍未上載完成，請重試。") from error
            if not metadata.is_file():
                raise ValueError("附件上載失敗，請重新加入附件。")
            data = json.loads(metadata.read_text())
            path = Path(data["path"]).resolve()
            if (
                data["placeholder"] != placeholder
                or not path.is_relative_to(uploads.resolve())
                or not path.is_file()
            ):
                raise ValueError("Attachment is unavailable")
            value = value.replace(placeholder, str(path))
        return value

    def artifact(path_value: str) -> tuple[Path, sqlite3.Row]:
        path = Path(path_value)
        workflow = root / "workflow"
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(workflow / "jobs") or path.is_symlink():
                raise ValueError
            with sqlite3.connect(workflow / "jobs.sqlite3") as db:
                db.row_factory = sqlite3.Row
                row = db.execute("SELECT * FROM artifacts WHERE path = ?", (str(path),)).fetchone()
            if (
                row is None
                or not resolved.is_file()
                or resolved.stat().st_size != row["size_bytes"]
            ):
                raise ValueError
            if hashlib.sha256(resolved.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError
            return resolved, row
        except (OSError, ValueError, sqlite3.Error) as error:
            raise HTTPException(404, "Verified artifact is unavailable") from error

    @app.get("/api/artifacts/url")
    async def artifact_url(path: str):
        resolved, row = artifact(path)
        now = monotonic()
        for key, (_, expiry) in list(downloads.items()):
            if expiry < now:
                downloads.pop(key, None)
        token = secrets.token_urlsafe(32)
        downloads[token] = (resolved, now + 300)
        return {
            "url": f"/api/downloads/{token}",
            "filename": resolved.name,
            "content_type": row["media_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "expires_in": 300,
        }

    @app.get("/api/downloads/{token}")
    async def download(token: str):
        item = downloads.get(token)
        if not item or item[1] < monotonic():
            raise HTTPException(404, "Download link expired")
        path, row = artifact(str(item[0]))
        return FileResponse(path, media_type=row["media_type"], filename=path.name)

    @app.websocket("/acp")
    async def acp(websocket: WebSocket):
        token = websocket.query_params.get("ticket", "")
        expiry = tickets.pop(token, 0)
        if (
            expiry < monotonic()
            or websocket.headers.get("host") != parsed.netloc
            or (websocket.headers.get("origin") != settings.public_api_url)
            or not secrets.compare_digest(websocket.cookies.get("ngopilot.local", ""), cookie)
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        acquired = False
        tasks = []
        try:
            managed = await manager.acquire(LOCAL_OWNER)
            acquired = True
            async with connect(
                managed.websocket_url,
                additional_headers={"X-Secret-Key": managed.secret},
                max_size=MAX_ACP_MESSAGE_BYTES,
                close_timeout=5,
            ) as upstream:

                async def inbound():
                    while True:
                        message = await websocket.receive_json()
                        if not isinstance(message, dict):
                            continue
                        try:
                            message = await resolve(isolate_client_request(message, root))
                        except ValueError as error:
                            if "id" in message:
                                await websocket.send_json(
                                    {
                                        "jsonrpc": "2.0",
                                        "id": message["id"],
                                        "error": {"code": -32602, "message": str(error)},
                                    }
                                )
                            continue
                        await upstream.send(json.dumps(message))

                async def outbound():
                    async for raw in upstream:
                        await websocket.send_text(browser_message(raw, json.loads(raw)))

                tasks = [asyncio.create_task(inbound()), asyncio.create_task(outbound())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except Exception as error:
            import logging

            logging.getLogger(__name__).warning("Local ACP disconnected: %s", type(error).__name__)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if acquired:
                await manager.release(LOCAL_OWNER)
            try:
                await websocket.close()
            except RuntimeError:
                pass

    app.mount("/", StaticFiles(directory=frontend, html=True, check_dir=False), name="chatbot")
    return app
