import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ngopilot_mcp.config import load_settings
from ngopilot_mcp.host.registry import RegisteredTool, load_tools
from ngopilot_mcp.host.router import Router
from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.shared.human_confirmation import HumanConfirmations
from ngopilot_mcp.shared.runtime import Runtime
from ngopilot_mcp.shared.tool_api import ToolCall
from ngopilot_mcp.tools.activity_scheduler import CONTROLLER, MANIFEST, native_adapter
from ngopilot_mcp.tools.activity_scheduler.artifacts import validate_export
from ngopilot_mcp.tools.activity_scheduler.schemas import StartInput
from ngopilot_mcp.tools.activity_scheduler.state import projection
from ngopilot_mcp.tools.activity_scheduler.validation import (
    validate_pdf,
    validate_reviews,
)

SNAPSHOT = {
    "source": {"id": "a" * 32, "pages": 1},
    "pages": [{"page": 1, "status": "extracted"}],
    "activities": [
        {
            "id": "b" * 32,
            "revision": 1,
            "review_status": "draft",
            "data": {"title": "Synthetic", "dates": ["2026-10-12"]},
        }
    ],
}


def test_independent_optional_contract(monkeypatch):
    monkeypatch.delenv("NGOPILOT_SCHEDULER_URL", raising=False)
    original = [item.manifest.name for item in load_tools()]
    monkeypatch.setenv("NGOPILOT_SCHEDULER_URL", "http://127.0.0.1:8311")
    assert [item.manifest.name for item in load_tools()] == [
        *original,
        "activity_scheduler",
    ]
    assert (
        MANIFEST.worker == "scheduler"
        and MANIFEST.human_confirmation_operations == ("review",)
    )
    assert "pdf_path" in MANIFEST.input_schema["properties"]["input"]["properties"]
    with pytest.raises(ValidationError):
        StartInput(pdf_path="file.pdf", year=1900)


def test_review_scope_and_revision():
    record = SNAPSHOT["activities"][0]
    validate_reviews([record], [{"id": record["id"], "revision": 1}])
    for bad in (
        [{"id": "c" * 32, "revision": 1}],
        [{"id": record["id"], "revision": 2}],
        [],
    ):
        with pytest.raises(ToolError):
            validate_reviews([record], bad)


def test_state_and_artifact_validation(tmp_path):
    assert projection(SNAPSHOT) == ("pending_review", ["status", "review"])
    current = deepcopy(SNAPSHOT)
    current["pages"][0]["status"] = "failed"
    assert projection(current)[0] == "blocked"
    path = tmp_path / "bad.ics"
    path.write_text("BEGIN:VCALENDAR")
    with pytest.raises(ToolError):
        validate_export(path, "ics")
    path.write_text("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    assert validate_export(path, "ics") == path
    with pytest.raises(ToolError):
        validate_pdf(str(path))


def test_adapter_export_is_scoped_and_preserves_review(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def request(path, payload=None, **kwargs):
        calls.append((path, payload))
        if path.endswith("/pages"):
            return deepcopy(SNAPSHOT["pages"])
        if path.startswith("/api/activities?"):
            return deepcopy(SNAPSHOT["activities"])
        if path.endswith(".ics"):
            return b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        if path.endswith(".csv"):
            return b"title,date\r\nSynthetic,2026-10-12\r\n"
        raise AssertionError(path)

    monkeypatch.setattr(native_adapter, "_request", request)
    result = native_adapter.handle("export", {"source": SNAPSHOT["source"]})
    assert set(result["exports"]) == {"ics", "csv"}
    assert all("/selection" not in path for path, _ in calls)
    assert all("a" * 32 in path for path, _ in calls)
    assert "source=" + "a" * 32 in result["calendar_url"]


def test_adapter_rejects_nonlocal_endpoint(monkeypatch):
    monkeypatch.setenv("NGOPILOT_SCHEDULER_URL", "https://external.invalid")
    with pytest.raises(ToolError, match="本機"):
        native_adapter._request("/api/sources")


@pytest.mark.asyncio
async def test_lifecycle_human_gate_artifact_and_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(tmp_path / "state"))
    fixtures = Path(__file__).resolve().parents[4] / "deployment" / "agent-samples"
    monkeypatch.setenv("NGOPILOT_MCP_ALLOWED_INPUT_ROOTS", str(fixtures))
    monkeypatch.setenv("NGOPILOT_MCP_REQUIRE_HUMAN_CONFIRMATION", "true")
    settings = load_settings()
    runtime = Runtime(settings)
    current = deepcopy(SNAPSHOT)

    async def worker(**kw):
        if kw["operation"] == "review":
            current["activities"][0].update(review_status="confirmed", revision=2)
        result = deepcopy(current)
        if kw["operation"] == "export":
            result["exports"] = {}
            for kind, value in {
                "ics": "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
                "csv": "title,date\r\nSynthetic,2026-10-12",
            }.items():
                path = tmp_path / ("output." + kind)
                path.write_text(value)
                result["exports"][kind] = str(path)
        return result

    monkeypatch.setattr(runtime, "call_worker", worker)
    router = Router(runtime, (RegisteredTool(MANIFEST, CONTROLLER),))

    async def call(op, job_id=None, data=None):
        return await router.call(
            tool_name=MANIFEST.name,
            operation=op,
            job_id=job_id,
            input_payload=data,
            request_id=None,
        )

    started = await call(
        "start",
        data={
            "pdf_path": str(fixtures / "activity-brochure-synthetic.pdf"),
            "year": 2026,
        },
    )
    assert started["state"] == "pending_review", started
    job_id = started["job_id"]
    assert (await call("export", job_id))["error"]["code"] == "INVALID_JOB_STATE"
    review = {
        "reviews": [
            {
                "id": "b" * 32,
                "revision": 1,
                "data": current["activities"][0]["data"],
                "status": "confirmed",
                "note": "",
            }
        ],
        "reviewer": "Test human",
    }
    denied = await call("review", job_id, review)
    assert denied["error"]["code"] == "HUMAN_CONFIRMATION_REQUIRED"
    assert (
        runtime.get_job(tool_name=MANIFEST.name, job_id=job_id).state
        == "pending_review"
    )
    HumanConfirmations(settings.state_root).grant(
        tool=MANIFEST.name,
        job_id=job_id,
        operation="review",
        payload=review,
        revision=started["result"],
        reviewer="Test human",
    )
    assert (await call("review", job_id, review))["state"] == "reviewed"
    exported = await call("export", job_id)
    assert exported["state"] == "exported" and len(exported["artifacts"]) == 2
    reopened = Runtime(settings)
    refreshed = await CONTROLLER.execute(
        ToolCall(operation="status", job_id=job_id), reopened
    )
    assert len(refreshed.artifacts) == 2
    assert (
        json.loads(json.dumps(refreshed.as_dict()))["result"]["source"]["id"]
        == "a" * 32
    )


@pytest.mark.asyncio
async def test_worker_failure_is_visible_and_retryable(monkeypatch, tmp_path):
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(tmp_path))
    runtime = Runtime(load_settings())
    job = runtime.create_job(tool_name=MANIFEST.name, request_id=None, input_payload={})
    runtime.jobs.update_job(
        job_id=job.job_id,
        state="running",
        native_status="running",
        result=deepcopy(SNAPSHOT),
        native_refs={},
        warnings=[],
        next_operations=["status"],
        error=None,
    )

    async def broken(**kwargs):
        raise ToolError("SCHEDULER_UNAVAILABLE", "Test outage", retryable=True)

    monkeypatch.setattr(runtime, "call_worker", broken)
    result = await CONTROLLER.execute(
        ToolCall(operation="status", job_id=job.job_id), runtime
    )
    assert result.error["code"] == "SCHEDULER_UNAVAILABLE" and not result.artifacts
