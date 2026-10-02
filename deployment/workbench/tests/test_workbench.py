from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from ngopilot_mcp.config import Settings
from deployment.workbench.server import create_app

PAPER = "careflow_paper_forms_to_excel"
GOV = "careflow_government_forms"


@pytest.fixture
def client(tmp_path):
    s = Settings(
        tmp_path, tmp_path, tmp_path, tmp_path / "python", tmp_path / "python", (), 30
    )
    s.initialize_directories()
    with TestClient(create_app(s)) as c:
        yield c


def test_origin_host_and_file_boundaries(client):
    assert (
        client.post("/api/uploads", files={"file": ("evil.py", b"code")}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/uploads",
            headers={"Origin": "https://evil.test"},
            files={"file": ("pic.png", b"png")},
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 403
    r = client.post("/api/uploads", files={"file": ("../../sample.png", b"png")})
    assert r.status_code == 200
    assert Path(r.json()["path"]).parent.name == "uploads"
    assert ".." not in r.json()["path"]
    assert client.get("/api/jobs/no-such-job/source/1").status_code == 404


def test_human_review_is_explicit_and_no_publish(client):
    for body in [
        {"operation": "review", "request_id": "r1", "input": {}},
        {
            "operation": "review",
            "request_id": "r2",
            "human_confirmed": True,
            "reviewer": "",
            "input": {},
        },
        {
            "operation": "review",
            "request_id": "r3",
            "human_confirmed": True,
            "reviewer": "test",
            "input": {"confirm_all": True},
        },
    ]:
        assert client.post(f"/api/tools/{PAPER}/call", json=body).status_code == 400
    for operation in ["publish", "burn", "get_published"]:
        assert (
            client.post(
                "/api/tools/roster_copilot/call",
                json={"operation": operation, "request_id": "x"},
            ).status_code
            == 400
        )


def test_missing_models_no_native_mock_fallback_even_if_mapping_disabled(
    client, monkeypatch
):
    for name in [
        "LLM_PROVIDER",
        "AZURE_OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    assert (
        client.post(
            f"/api/tools/{PAPER}/call",
            json={
                "operation": "start",
                "request_id": "paper",
                "input": {"image_paths": ["/tmp/a.png"]},
            },
        ).status_code
        == 503
    )
    assert (
        client.post(
            f"/api/tools/{GOV}/call",
            json={
                "operation": "start",
                "request_id": "gov",
                "input": {"use_llm": False, "source": {"kind": "text", "text": "test"}},
            },
        ).status_code
        == 503
    )


def test_arbitrary_server_path_rejected_before_controller(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    client.app.state.router.call = AsyncMock()
    r = client.post(
        f"/api/tools/{PAPER}/call",
        json={
            "operation": "start",
            "request_id": "path",
            "input": {"image_paths": ["/etc/passwd"]},
        },
    )
    assert r.status_code == 400
    client.app.state.router.call.assert_not_called()


def test_async_operation_survives_browser_poll_and_records_reviewer(client):
    router = client.app.state.router
    router.call = AsyncMock(return_value={"state": "reviewed", "tool": PAPER})
    body = {
        "operation": "review",
        "request_id": "review-test",
        "reviewer": "Synthetic tester",
        "human_confirmed": True,
        "input": {"reviews": [{"record_id": 1, "final_fields": {}}]},
    }
    r = client.post(f"/api/tools/{PAPER}/call", json=body)
    assert r.status_code == 200
    import time

    for _ in range(50):
        op = client.get("/api/operations/review-test").json()
        if op["status"] == "complete":
            break
        time.sleep(0.01)
    assert op["result"]["state"] == "reviewed"
    assert op["reviewer"] == "Synthetic tester" and op["created_at"]
    assert (
        router.call.call_args.kwargs["input_payload"]["reviews"][0]["reviewer"]
        == "Synthetic tester"
    )
    assert (
        client.post(f"/api/tools/{PAPER}/call", json=body).json()["operation_id"]
        == "review-test"
    )
    assert router.call.call_count == 1
    body["reviewer"] = "Another tester"
    assert client.post(f"/api/tools/{PAPER}/call", json=body).status_code == 409


def test_blocked_roster_cannot_export(client):
    rt = client.app.state.runtime
    job = rt.create_job(
        tool_name="roster_copilot", request_id="start", input_payload={}
    )
    rt.jobs.update_job(
        job_id=job.job_id,
        state="blocked",
        native_status="blocked",
        result={},
        native_refs={},
        warnings=[],
        next_operations=["export"],
        error=None,
    )
    assert (
        client.post(
            "/api/tools/roster_copilot/call",
            json={"operation": "export", "request_id": "export", "job_id": job.job_id},
        ).status_code
        == 409
    )
