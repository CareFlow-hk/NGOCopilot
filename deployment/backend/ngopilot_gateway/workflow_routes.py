"""Read-only job projection and human confirmation for Agent conversation cards."""

from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings


class Confirmation(BaseModel):
    operation: str = "review"
    input: dict[str, Any]
    reviewer: str = Field(min_length=1, max_length=120)
    revision: str


def register_workflow_routes(app: FastAPI, settings: Settings, owner_dependency: Callable):
    from ngopilot_mcp.host.registry import load_tools
    from ngopilot_mcp.shared.errors import ToolError
    from ngopilot_mcp.shared.human_confirmation import HumanConfirmations
    from ngopilot_mcp.shared.jobs import JobStore
    from ngopilot_mcp.shared.jsonutil import payload_hash
    from ngopilot_mcp.shared.tool_api import ToolExecution

    registry = {tool.manifest.name: tool for tool in load_tools()}

    async def context(user_id: UUID, job_id: str):
        root = settings.data_root / "tenants" / str(user_id)
        storage = getattr(app.state, "storage", None)
        if storage is not None:
            await storage.restore_tenant_cache(user_id)
        workflow = root / "workflow"
        if not (workflow / "jobs.sqlite3").is_file():
            raise HTTPException(404, "Task is unavailable")
        store = JobStore(workflow / "jobs.sqlite3")
        for name in registry:
            try:
                return root, workflow, store, store.get_job(tool_name=name, job_id=job_id)
            except ToolError:
                continue
        raise HTTPException(404, "Task is unavailable")

    def sources(root: Path, job) -> list[dict]:
        paths = set()

        def collect(value):
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str) and value.startswith(str(root)):
                path = Path(value)
                allowed = (
                    root / "uploads",
                    root / "workflow" / "jobs" / job.tool_name / job.job_id / "inputs",
                )
                try:
                    if path.is_file() and any(
                        path.resolve().is_relative_to(p.resolve()) for p in allowed
                    ):
                        paths.add(str(path))
                except OSError:
                    pass

        collect(job.input_payload)
        if not paths:
            collect(job.result)
        return [
            {
                "id": index,
                "filename": Path(path).name,
                "path": path,
                "url": f"/api/workflows/{job.job_id}/sources/{index}",
            }
            for index, path in enumerate(sorted(paths))
        ]

    @app.get("/api/workflows/{job_id}")
    async def task(job_id: str, user_id: UUID = Depends(owner_dependency)):
        root, workflow, store, job = await context(user_id, job_id)
        result = ToolExecution(
            tool=job.tool_name,
            operation="status",
            job_id=job.job_id,
            state=job.state,
            result=job.result,
            warnings=job.warnings,
            error=job.error,
            next_operations=job.next_operations,
            artifacts=store.list_artifacts(job_id=job.job_id),
        ).as_dict()
        result.update(
            {
                "revision": payload_hash(job.result),
                "updated_at": job.updated_at,
                "proposed_input": HumanConfirmations(workflow).proposal(
                    tool=job.tool_name, job_id=job.job_id, operation="review", revision=job.result
                ),
                "confirmation_operations": registry[
                    job.tool_name
                ].manifest.human_confirmation_operations,
                "sources": [
                    {k: v for k, v in item.items() if k != "path"} for item in sources(root, job)
                ],
            }
        )
        presenter = getattr(registry[job.tool_name].controller, "presentation_warnings", None)
        if callable(presenter):
            result["warnings"] = [*result["warnings"], *presenter(job.result)]
        for operation in ("publish", "burn"):
            if (
                operation in job.next_operations
                and operation in registry[job.tool_name].manifest.human_confirmation_operations
            ):
                proposed = HumanConfirmations(workflow).proposal(
                    tool=job.tool_name, job_id=job.job_id, operation=operation, revision=job.result
                )
                if proposed is not None:
                    result["pending_action"] = {"operation": operation, "input": proposed}
                    break
        return result

    @app.get("/api/workflows/{job_id}/sources/{source_id}")
    async def source(job_id: str, source_id: int, user_id: UUID = Depends(owner_dependency)):
        root, _, _, job = await context(user_id, job_id)
        entries = sources(root, job)
        if source_id < 0 or source_id >= len(entries):
            raise HTTPException(404, "Source unavailable")
        path = Path(entries[source_id]["path"])
        media = "application/pdf" if path.suffix.lower() == ".pdf" else None
        return FileResponse(
            path, media_type=media, filename=path.name, content_disposition_type="inline"
        )

    @app.post("/api/workflows/{job_id}/confirm")
    async def confirm(job_id: str, body: Confirmation, user_id: UUID = Depends(owner_dependency)):
        if not body.reviewer.strip():
            raise HTTPException(422, "請填寫核對人。")
        _, workflow, _, job = await context(user_id, job_id)
        manifest = registry[job.tool_name].manifest
        if (
            body.operation not in manifest.human_confirmation_operations
            or body.operation not in job.next_operations
        ):
            raise HTTPException(409, "This action is not available for the current task")
        if body.revision != payload_hash(job.result):
            raise HTTPException(409, "內容已更新，請重新核對。")
        HumanConfirmations(workflow).grant(
            tool=job.tool_name,
            job_id=job.job_id,
            operation=body.operation,
            payload=body.input,
            revision=job.result,
            reviewer=body.reviewer.strip(),
        )
        return {
            "tool": job.tool_name,
            "job_id": job.job_id,
            "operation": body.operation,
            "input": body.input,
        }
