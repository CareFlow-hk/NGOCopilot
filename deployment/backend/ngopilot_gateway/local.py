"""Loopback-only transport for the original NGOPilot Chatbot and ACP runtime.

This is a loopback launcher, not the production account/GCS gateway. Staff sign
in with invitation-only local accounts (see ``local_accounts``); every account
has its own Agent tenant. Conversation, planning and tool execution stay in the
existing Rust Agent. This module only serves its renderer, accounts, uploads,
verified artifacts and ACP transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from websockets.asyncio.client import connect

from .acp_proxy import MAX_ACP_MESSAGE_BYTES, browser_message, isolate_client_request
from .config import Settings
from .local_accounts import SESSION_ABSOLUTE_SECONDS, AccountError, LocalAccounts, Session, require
from .local_usage import LocalUsage, UsageLimitReached
from .processes import TenantProcessManager
from .storage import PLACEHOLDER_PATTERN, parse_placeholder, safe_filename

# Tenant of the pre-account single-owner launcher; the first administrator inherits it.
LOCAL_OWNER = UUID("dc5aab2c-7220-4ef3-bf54-9386b9d95412")
SESSION_COOKIE = "ngopilot_session"
CONFIRM_PATH = re.compile(r"/api/workflows/[^/]+/confirm")
PUBLIC_PATHS = {"/api/runtime", "/api/auth/login", "/api/auth/set-password", "/healthz"}
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
    ".txt",
    ".md",
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
    settings.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    accounts = LocalAccounts(settings.data_root / "accounts.sqlite3")
    usage = LocalUsage(
        accounts,
        message_limit=int(os.getenv("NGOPILOT_WEEKLY_MESSAGE_LIMIT", "500")),
        image_limit=int(os.getenv("NGOPILOT_WEEKLY_IMAGE_LIMIT", "200")),
    )
    tickets: dict[str, tuple[float, Session]] = {}
    downloads: dict[str, tuple[Path, float, UUID]] = {}
    upload_events: dict[str, asyncio.Event] = {}

    def uploads_for(user_id: UUID) -> Path:
        folder = manager.tenant_root(user_id) / "uploads"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return folder

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await manager.stop_all()
        accounts.close()

    app = FastAPI(title="NGOPilot Agent · 本機", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.processes = manager
    app.state.accounts = accounts
    app.state.usage = usage
    from .workflow_routes import register_workflow_routes

    def current(request: Request) -> Session:
        return request.state.session

    def owner(request: Request) -> UUID:
        return current(request).user_id

    register_workflow_routes(app, settings, owner)

    @app.exception_handler(AccountError)
    async def account_error(_: Request, error: AccountError):
        headers = {"Retry-After": "900"} if error.status == 429 else None
        return JSONResponse({"detail": str(error)}, status_code=error.status, headers=headers)

    def set_cookie(response: Response, token: str, max_age: int = SESSION_ABSOLUTE_SECONDS):
        # Plain HTTP is accepted only because create_local_app requires loopback.
        response.set_cookie(
            SESSION_COOKIE, token, max_age=max_age, path="/", httponly=True, samesite="strict"
        )

    async def json_body(request: Request) -> dict:
        require(
            request.headers.get("content-type", "").split(";")[0] == "application/json",
            415,
            "需要 JSON 請求。",
        )
        raw = await request.body()
        require(len(raw) <= 8192, 413, "請求過大。")
        try:
            body = json.loads(raw)
        except ValueError as error:
            raise AccountError(400, "JSON 格式不正確。") from error
        require(isinstance(body, dict), 400, "無效請求。")
        return body

    def source(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if (
            request.headers.get("host") != parsed.netloc
            or not local_origin(request.headers.get("origin"), settings.public_api_url)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Local same-origin access required"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and request.headers.get("origin") is None:
            return JSONResponse({"detail": "Local same-origin access required"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_PATHS:
            session = accounts.session(request.cookies.get(SESSION_COOKIE))
            if session is None:
                return JSONResponse({"detail": "請登入後繼續。"}, status_code=401)
            request.state.session = session
        response = await call_next(request)
        if (
            request.method == "POST"
            and response.status_code == 200
            and CONFIRM_PATH.fullmatch(request.url.path)
        ):
            # The card then sends one continuation message; it must not be capped.
            usage.grant_continuation(request.state.session.user_id)
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
    async def runtime_config(request: Request):
        session = accounts.session(request.cookies.get(SESSION_COOKIE), touch=False)
        return {
            "GOOSE_DEFAULT_PROVIDER": settings.goose_provider,
            "GOOSE_DEFAULT_MODEL": settings.goose_model,
            "GOOSE_WORKING_DIR": str(manager.tenant_root(session.user_id)) if session else "",
            "NGOPILOT_LOCAL": True,
            "NGOPILOT_MODEL_CONFIGURED": bool(os.getenv("FOUNDRY_API_KEY")),
            "NGOPILOT_MODEL_NAME": os.getenv("FOUNDRY_DEPLOYMENT", "gpt-6-luna"),
            "NGOPILOT_AGENT_HOME": True,
            "NGOPILOT_SCHEDULER_ENABLED": bool(os.getenv("NGOPILOT_SCHEDULER_URL")),
        }

    def session_view(session: Session) -> dict:
        from .local_accounts import public_user

        return {
            "user": public_user(accounts.user(session.user_id)),
            "expiresAt": session.expires_at,
            "local": True,
        }

    @app.get("/api/auth/me")
    async def me(request: Request):
        return session_view(current(request))

    @app.post("/api/auth/login")
    async def login(request: Request):
        body = await json_body(request)
        token, session = await asyncio.to_thread(
            accounts.login, body.get("email"), body.get("password"), source(request)
        )
        response = JSONResponse(session_view(session))
        set_cookie(response, token)
        return response

    @app.post("/api/auth/set-password")
    async def set_password(request: Request):
        body = await json_body(request)
        await asyncio.to_thread(
            accounts.redeem, body.get("token"), body.get("password"), source(request)
        )
        response = JSONResponse({"ok": True})
        set_cookie(response, "", 0)
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        accounts.logout(current(request))
        response = JSONResponse({"ok": True})
        set_cookie(response, "", 0)
        return response

    @app.post("/api/auth/password")
    async def change_password(request: Request):
        body = await json_body(request)
        await asyncio.to_thread(
            accounts.change_password,
            current(request),
            body.get("oldPassword"),
            body.get("password"),
        )
        response = JSONResponse({"ok": True})
        set_cookie(response, "", 0)
        return response

    @app.get("/api/auth/sessions")
    async def sessions(request: Request):
        return {"sessions": accounts.sessions(current(request))}

    @app.post("/api/auth/sessions/revoke-others")
    async def revoke_others(request: Request):
        accounts.revoke_others(current(request))
        return {"ok": True}

    def password_link(token: str) -> str:
        return f"{settings.public_api_url}/#set-password={token}"

    @app.get("/api/auth/usage")
    async def own_usage(request: Request):
        return usage.own(current(request))

    @app.get("/api/admin/usage")
    async def usage_report(request: Request):
        accounts.require_admin(current(request))
        return usage.report()

    @app.put("/api/admin/users/{user_id}/limits")
    async def user_limits(user_id: str, request: Request):
        body = await json_body(request)
        return usage.set_limits(current(request), user_id, body.get("messages"), body.get("images"))

    @app.get("/api/admin/users")
    async def users(request: Request):
        accounts.require_admin(current(request))
        return {"users": accounts.users()}

    @app.get("/api/admin/audit")
    async def audit(request: Request):
        accounts.require_admin(current(request))
        return {"events": accounts.audit_events()}

    @app.post("/api/admin/users", status_code=201)
    async def invite(request: Request):
        admin = accounts.require_admin(current(request))
        body = await json_body(request)
        accounts.limit(f"admin:{admin['id']}", 30)
        user, token = accounts.create_user(
            body.get("email"), body.get("name"), body.get("role"), admin["id"]
        )
        return {"user": user, "link": password_link(token)}

    @app.patch("/api/admin/users/{user_id}")
    async def update_user(user_id: str, request: Request):
        body = await json_body(request)
        return {"user": accounts.update_user(current(request), user_id, body)}

    @app.post("/api/admin/users/{user_id}/reset")
    async def reset(user_id: str, request: Request):
        admin = accounts.require_admin(current(request))
        accounts.limit(f"admin:{admin['id']}", 30)
        return {"link": password_link(accounts.reset_link(current(request), user_id))}

    @app.post("/api/ws-tickets")
    async def ticket(request: Request):
        now = monotonic()
        for key, (expiry, _) in list(tickets.items()):
            if expiry < now:
                tickets.pop(key, None)
        value = secrets.token_urlsafe(32)
        tickets[value] = (now + 60, current(request))
        return {
            "url": settings.public_api_url.replace("http://", "ws://", 1) + "/acp?ticket=" + value
        }

    @app.post("/api/uploads", status_code=201)
    async def upload(
        request: Request,
        file: UploadFile = File(...),
        upload_id: str = Form(...),
        placeholder: str = Form(...),
    ):
        try:
            ident, filename = parse_placeholder(placeholder)
            if str(ident) != upload_id or filename != file.filename:
                raise ValueError("Upload identity mismatch")
            if os.getenv("NGOPILOT_AI_PROVIDER") == "foundry" and Path(filename).suffix.lower() in {
                ".wav",
                ".mp3",
                ".m4a",
                ".ogg",
                ".flac",
                ".mp4",
                ".aac",
            }:
                raise ValueError("Luna 不支援錄音轉寫。請上傳 TXT 或 DOCX 文字稿及 Word 範本。")
            if Path(filename).suffix.lower() not in UPLOAD_SUFFIXES:
                raise ValueError("Unsupported attachment type")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        folder = uploads_for(owner(request)) / str(ident)
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

    async def resolve(value, uploads: Path):
        if isinstance(value, dict):
            return {key: await resolve(child, uploads) for key, child in value.items()}
        if isinstance(value, list):
            return [await resolve(child, uploads) for child in value]
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

    def artifact(path_value: str, user_id: UUID) -> tuple[Path, sqlite3.Row]:
        path = Path(path_value)
        workflow = manager.tenant_root(user_id) / "workflow"
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
    async def artifact_url(path: str, request: Request):
        resolved, row = artifact(path, owner(request))
        now = monotonic()
        for key, (_, expiry, _) in list(downloads.items()):
            if expiry < now:
                downloads.pop(key, None)
        token = secrets.token_urlsafe(32)
        downloads[token] = (resolved, now + 300, owner(request))
        return {
            "url": f"/api/downloads/{token}",
            "filename": resolved.name,
            "content_type": row["media_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "expires_in": 300,
        }

    @app.get("/api/downloads/{token}")
    async def download(token: str, request: Request):
        item = downloads.get(token)
        if not item or item[1] < monotonic() or item[2] != owner(request):
            raise HTTPException(404, "Download link expired")
        path, row = artifact(str(item[0]), item[2])
        return FileResponse(path, media_type=row["media_type"], filename=path.name)

    @app.websocket("/acp")
    async def acp(websocket: WebSocket):
        token = websocket.query_params.get("ticket", "")
        expiry, session = tickets.pop(token, (0, None))
        cookie_session = accounts.session(websocket.cookies.get(SESSION_COOKIE))
        if (
            expiry < monotonic()
            or session is None
            or cookie_session is None
            or cookie_session.hash != session.hash
            or websocket.headers.get("host") != parsed.netloc
            or (websocket.headers.get("origin") != settings.public_api_url)
        ):
            await websocket.close(code=1008)
            return
        user_id = session.user_id
        root = manager.tenant_root(user_id)
        uploads = uploads_for(user_id)
        await websocket.accept()
        acquired = False
        tasks = []
        model_requests = {}
        try:
            managed = await manager.acquire(user_id)
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
                        if message.get("method") == "session/prompt" and not os.getenv(
                            "FOUNDRY_API_KEY"
                        ):
                            await websocket.send_json(
                                {
                                    "jsonrpc": "2.0",
                                    "id": message.get("id"),
                                    "error": {
                                        "code": -32000,
                                        "message": "尚未配置 Foundry Luna API Key，請由管理員完成設定後重啟。",
                                    },
                                }
                            )
                            continue
                        if not accounts.active(session):
                            return
                        if message.get("method") == "session/prompt":
                            try:
                                usage.record_prompt(session, message)
                            except UsageLimitReached as error:
                                await websocket.send_json(
                                    {
                                        "jsonrpc": "2.0",
                                        "id": message.get("id"),
                                        "error": {"code": -32000, "message": str(error)},
                                    }
                                )
                                continue
                        try:
                            message = await resolve(isolate_client_request(message, root), uploads)
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
                        if message.get("method") == "session/prompt":
                            # Historical sessions retain their messages but use
                            # the new deployment for every new model request.
                            switch_failed = False
                            for config_id, value in (
                                ("provider", "openai"),
                                ("model", settings.foundry_deployment),
                            ):
                                ident = "foundry-model-" + secrets.token_hex(12)
                                ready = asyncio.get_running_loop().create_future()
                                model_requests[ident] = ready
                                await upstream.send(
                                    json.dumps(
                                        {
                                            "jsonrpc": "2.0",
                                            "id": ident,
                                            "method": "session/set_config_option",
                                            "params": {
                                                "sessionId": message.get("params", {}).get(
                                                    "sessionId"
                                                ),
                                                "configId": config_id,
                                                "value": value,
                                            },
                                        }
                                    )
                                )
                                try:
                                    result = await asyncio.wait_for(ready, 30)
                                    switch_failed = bool(result.get("error"))
                                except TimeoutError:
                                    switch_failed = True
                                finally:
                                    model_requests.pop(ident, None)
                                if switch_failed:
                                    break
                            if switch_failed:
                                await websocket.send_json(
                                    {
                                        "jsonrpc": "2.0",
                                        "id": message.get("id"),
                                        "error": {
                                            "code": -32000,
                                            "message": "切換 Luna 未成功，請開啟新對話；沒有沿用舊模型。",
                                        },
                                    }
                                )
                                continue
                        if message.get("method") == "session/set_config_option":
                            params = message.setdefault("params", {})
                            if params.get("configId") == "model":
                                params["value"] = settings.foundry_deployment
                            elif params.get("configId") == "provider":
                                params["value"] = "openai"
                        await upstream.send(json.dumps(message))

                async def outbound():
                    async for raw in upstream:
                        decoded = json.loads(raw)
                        pending = model_requests.pop(decoded.get("id"), None)
                        if pending is not None:
                            if not pending.done():
                                pending.set_result(decoded)
                            continue
                        await websocket.send_text(browser_message(raw, decoded))

                async def watch():
                    # Sign-out, password change or deactivation ends open connections.
                    while accounts.session(websocket.cookies.get(SESSION_COOKIE), touch=False):
                        await asyncio.sleep(30)

                tasks = [
                    asyncio.create_task(inbound()),
                    asyncio.create_task(outbound()),
                    asyncio.create_task(watch()),
                ]
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
                await manager.release(user_id)
            try:
                await websocket.close()
            except RuntimeError:
                pass

    app.mount("/", StaticFiles(directory=frontend, html=True, check_dir=False), name="chatbot")
    return app
