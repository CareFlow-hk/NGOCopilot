from __future__ import annotations
import asyncio
import json
import os
import mimetypes
import sqlite3
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from ngopilot_mcp.config import load_settings, Settings
from ngopilot_mcp.host.registry import load_tools
from ngopilot_mcp.host.router import Router
from ngopilot_mcp.shared.runtime import Runtime
from ngopilot_mcp.shared.redaction import redact_diagnostic
from ngopilot_mcp.shared.jsonutil import payload_hash

WORKFLOWS = {
    "careflow_paper_forms_to_excel": {
        "title": "紙本表格轉 Excel",
        "summary": "上載探訪表格照片，逐欄確認，再匯出 Excel。",
        "kind": "paper",
    },
    "careflow_meeting_notes": {
        "title": "會議記錄整理",
        "summary": "從錄音及 Word 範本整理記錄，核對後產生文件。",
        "kind": "meeting",
    },
    "careflow_government_forms": {
        "title": "政府表格填報",
        "summary": "選擇範本、輸入資料，逐欄核對後產生 PDF。",
        "kind": "government",
    },
    "roster_copilot": {
        "title": "排班草稿",
        "summary": "檢查家居照顧與護送工作表，查看衝突及待處理事項。",
        "kind": "roster",
    },
}
ALLOWED = {
    ".jpg",
    ".jpeg",
    ".png",
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


def model_status():
    mock = os.getenv("LLM_PROVIDER") == "mock"
    openrouter = bool(os.getenv("OPENROUTER_API_KEY"))
    vision = openrouter or bool(
        os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    text = openrouter or bool(os.getenv("DEEPSEEK_API_KEY"))
    return {
        "mock": mock,
        "vision": vision,
        "text": text,
        "audio": bool(os.getenv("DASHSCOPE_API_KEY")),
        "vision_model": os.getenv("AZURE_OPENAI_MODEL", "")
        if not openrouter
        else "OpenRouter",
        "text_model": os.getenv("DEEPSEEK_TEXT_MODEL", "deepseek-v4-flash")
        if not openrouter
        else "OpenRouter",
    }


class Call(BaseModel):
    operation: str
    job_id: str | None = None
    request_id: str = Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_-]+$")
    input: dict = Field(default_factory=dict)
    human_confirmed: bool = False
    reviewer: str = Field(default="", max_length=120)


def create_app(settings: Settings | None = None):
    if settings is None:
        os.environ.setdefault(
            "NGOPILOT_MCP_STATE_DIR",
            str(Path(__file__).resolve().parents[2] / ".local-workbench"),
        )
        settings = load_settings()
    uploads = settings.state_root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = replace(settings, allowed_input_roots=(uploads, settings.resources_root))
    runtime = Runtime(settings)
    router = Router(runtime, load_tools())
    tasks = set()
    op_db = settings.state_root / "workbench.sqlite3"

    def db():
        c = sqlite3.connect(op_db, timeout=15)
        c.row_factory = sqlite3.Row
        return c

    with db() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,tool TEXT,status TEXT,result TEXT,created_at TEXT,reviewer TEXT,operation TEXT)"
        )
        if "request_hash" not in {
            r[1] for r in c.execute("PRAGMA table_info(operations)")
        }:
            c.execute("ALTER TABLE operations ADD COLUMN request_hash TEXT")
        c.execute("UPDATE operations SET status='interrupted' WHERE status='running'")

    @asynccontextmanager
    async def lifespan(app):
        yield
        for t in list(tasks):
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="NGOPilot 本機工作台", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.router = router

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        } or (origin and urlparse(origin).netloc != request.headers.get("host")):
            return JSONResponse({"detail": "只接受本機同一網站的請求"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/health")
    def health():
        return {
            "mode": "本機試用版",
            "models": model_status(),
            "runtime_ready": settings.careflow_python.exists()
            and settings.roster_python.exists(),
            "workflows": WORKFLOWS,
        }

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File()):
        name = Path(file.filename or "file").name
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(400, "不支援此檔案格式")
        path = uploads / (uuid4().hex + suffix)
        total = 0
        try:
            with path.open("xb") as f:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise HTTPException(400, "檔案超過 100 MB")
                    f.write(chunk)
            if not total:
                raise HTTPException(400, "檔案不可為空")
            path.chmod(0o600)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {"path": str(path), "name": name, "size": total}

    def validate_paths(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                validate_paths(v, k)
        elif isinstance(value, list):
            for v in value:
                validate_paths(v, key)
        elif isinstance(value, str) and (
            key.endswith("_path") or key.endswith("_paths")
        ):
            p = Path(value).resolve()
            if not any(p.is_relative_to(root) for root in settings.allowed_input_roots):
                raise HTTPException(400, "只可使用經工作台上載的檔案")

    async def execute(id, tool, call):
        try:
            result = await router.call(
                tool_name=tool,
                operation=call.operation,
                job_id=call.job_id,
                request_id=call.request_id,
                input_payload=call.input,
            )
            if result.get("job_id"):
                job = runtime.get_job(tool_name=tool, job_id=result["job_id"])
                result["source_input"] = job.input_payload
                result["created_at"] = job.created_at
            status = "complete"
        except asyncio.CancelledError:
            with db() as c:
                c.execute(
                    "UPDATE operations SET status='interrupted' WHERE id=?", (id,)
                )
            raise
        except Exception as e:
            result = {"error": {"message": redact_diagnostic(str(e))}}
            status = "complete"
        with db() as c:
            c.execute(
                "UPDATE operations SET status=?,result=? WHERE id=?",
                (status, json.dumps(result, ensure_ascii=False), id),
            )

    @app.post("/api/tools/{tool}/call")
    async def call_tool(tool: str, call: Call):
        if tool not in WORKFLOWS:
            raise HTTPException(404, "找不到工作流程")
        if call.operation in {"burn", "publish", "get_published"}:
            raise HTTPException(400, "本機試用版不提供刪除逐字稿或發布排班")
        if call.operation == "review":
            if not call.human_confirmed or not call.reviewer.strip():
                raise HTTPException(400, "請填寫審核人並勾選已核對來源")
            if WORKFLOWS[tool]["kind"] == "paper":
                if call.input.get("confirm_all"):
                    raise HTTPException(400, "請逐筆核對欄位，不能略過審核畫面")
                for record in call.input.get("reviews", []):
                    record["reviewer"] = call.reviewer.strip()
            elif WORKFLOWS[tool]["kind"] in {"meeting", "government"}:
                call.input["reviewer"] = call.reviewer.strip()
            else:
                call.input["actor"] = call.reviewer.strip()
        if call.operation == "start":
            status = model_status()
            kind = WORKFLOWS[tool]["kind"]
            if not status["mock"]:
                needed = {
                    "paper": ["vision"],
                    "meeting": ["audio", "text"],
                    "government": (
                        ["text"]
                        if call.input.get("source", {}).get("kind") == "text"
                        or call.input.get("use_llm")
                        else []
                    )
                    + (
                        ["vision"]
                        if call.input.get("source", {}).get("kind") == "image"
                        else []
                    ),
                    "roster": [],
                }[kind]
                if any(not status[k] for k in needed):
                    raise HTTPException(
                        503,
                        "此流程的模型尚未設定；請管理員設定後重試，系統不會改用模擬結果",
                    )
        if call.job_id:
            try:
                job = runtime.get_job(tool_name=tool, job_id=call.job_id)
            except Exception:
                raise HTTPException(404, "找不到此工作") from None
            if call.operation == "export" and job.state == "blocked":
                raise HTTPException(409, "排班仍有阻塞項，不能匯出供實際使用")
        validate_paths(call.input)
        with db() as c:
            old = c.execute(
                "SELECT * FROM operations WHERE id=?", (call.request_id,)
            ).fetchone()
            digest = payload_hash({"tool": tool, **call.model_dump(mode="json")})
            if old:
                if old["request_hash"] != digest:
                    raise HTTPException(409, "重試識別碼已用於另一項操作，請重新提交")
                return {"operation_id": old["id"], "status": old["status"]}
            c.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)",
                (
                    call.request_id,
                    tool,
                    "running",
                    None,
                    datetime.now(timezone.utc).isoformat(),
                    call.reviewer,
                    call.operation,
                    digest,
                ),
            )
        task = asyncio.create_task(execute(call.request_id, tool, call))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"operation_id": call.request_id, "status": "running"}

    @app.get("/api/operations/{id}")
    def operation(id: str):
        with db() as c:
            row = c.execute("SELECT * FROM operations WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到操作")
        value = dict(row)
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    @app.get("/api/jobs")
    def jobs():
        with sqlite3.connect(settings.database_path) as c:
            c.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in c.execute(
                    "SELECT job_id,tool_name,state,created_at,updated_at,input_json FROM jobs ORDER BY updated_at DESC LIMIT 100"
                )
            ]

    @app.get("/api/jobs/{id}")
    def job_result(id: str):
        for tool in WORKFLOWS:
            try:
                job = runtime.get_job(tool_name=tool, job_id=id)
                result = runtime.job_execution(job=job, operation="status").as_dict()
                result["source_input"] = job.input_payload
                result["created_at"] = job.created_at
                return result
            except Exception:
                continue
        raise HTTPException(404, "找不到工作")

    def input_files(id):
        for tool in WORKFLOWS:
            try:
                job = runtime.get_job(tool_name=tool, job_id=id)
            except Exception:
                continue
            root = (runtime.files.job_root(job) / "inputs").resolve()
            return [
                p
                for p in sorted(root.iterdir())
                if p.is_file() and p.resolve().is_relative_to(root)
            ]
        raise HTTPException(404, "找不到來源")

    @app.get("/api/jobs/{id}/inputs")
    def inputs(id: str):
        return [
            {"index": i, "name": p.name, "type": mimetypes.guess_type(p.name)[0]}
            for i, p in enumerate(input_files(id))
        ]

    @app.get("/api/jobs/{id}/audio")
    def audio_source(id: str):
        for path in input_files(id):
            if path.suffix.lower() in {
                ".wav",
                ".mp3",
                ".m4a",
                ".ogg",
                ".flac",
                ".mp4",
                ".aac",
            }:
                return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0])
        raise HTTPException(404, "找不到原始錄音")

    @app.get("/api/jobs/{id}/inputs/{index}")
    def input_file(id: str, index: int):
        files = input_files(id)
        if index < 0 or index >= len(files):
            raise HTTPException(404, "找不到來源檔案")
        return FileResponse(
            files[index], media_type=mimetypes.guess_type(files[index].name)[0]
        )

    @app.get("/api/jobs/{id}/source/{record_id}")
    def source_image(id: str, record_id: int):
        try:
            job = runtime.get_job(tool_name="careflow_paper_forms_to_excel", job_id=id)
        except Exception:
            raise HTTPException(404, "找不到來源") from None
        path = job.native_refs.get("record_source_paths", {}).get(str(record_id))
        if not path:
            raise HTTPException(404, "找不到來源")
        p = Path(path).resolve()
        root = (runtime.files.job_root(job) / "inputs").resolve()
        if not p.is_relative_to(root) or p.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
        }:
            raise HTTPException(404, "來源路徑不符")
        return FileResponse(p)

    @app.get("/api/jobs/{id}/artifacts/{artifact_id}")
    def download(id: str, artifact_id: str):
        for tool in WORKFLOWS:
            try:
                job = runtime.get_job(tool_name=tool, job_id=id)
            except Exception:
                continue
            for artifact in runtime.jobs.list_artifacts(job_id=id):
                if artifact.artifact_id == artifact_id:
                    try:
                        runtime.artifacts.verify_registered(job=job, artifact=artifact)
                    except Exception:
                        raise HTTPException(
                            409, "檔案完整性檢查失敗，請重新匯出"
                        ) from None
                    return FileResponse(
                        artifact.path,
                        media_type=artifact.media_type,
                        filename=Path(artifact.path).name,
                    )
        raise HTTPException(404, "找不到檔案")

    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="workbench",
    )
    return app
