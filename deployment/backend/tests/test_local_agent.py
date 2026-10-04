import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ngopilot_gateway.config import Settings
from ngopilot_gateway.local import LOCAL_OWNER, create_local_app

PASSWORD = "correct horse battery staple"


@pytest.fixture
def local(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<h1>Original Agent renderer</h1>")
    settings = Settings(
        app_env="local",
        data_root=tmp_path / "data",
        public_api_url="http://127.0.0.1:8310",
        max_upload_bytes=20,
    )
    app = create_local_app(settings, frontend)
    with TestClient(
        app, base_url=settings.public_api_url, headers={"Origin": settings.public_api_url}
    ) as client:
        token = app.state.accounts.bootstrap("admin@example.org", "Admin", LOCAL_OWNER)
        client.post("/api/auth/set-password", json={"token": token, "password": PASSWORD})
        login = client.post(
            "/api/auth/login", json={"email": "admin@example.org", "password": PASSWORD}
        )
        assert login.status_code == 200
        yield client, settings


def test_local_boundary_and_session_cookie(local):
    client, _ = local
    assert client.get("/api/auth/me", headers={"Origin": "https://other.test"}).status_code == 403
    assert client.get("/api/auth/me", headers={"Host": "evil.test"}).status_code == 403
    assert client.post("/api/ws-tickets", headers={"Origin": ""}).status_code == 403
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(LOCAL_OWNER)
    assert response.json()["user"]["role"] == "ADMIN"
    assert (
        client.post("/api/ws-tickets").json()["url"].startswith("ws://127.0.0.1:8310/acp?ticket=")
    )
    config = client.get("/api/runtime").json()
    assert config["NGOPILOT_AGENT_HOME"] is True
    assert not any("KEY" in key or "TOKEN" in key for key in config)


def test_upload_identity_size_and_persistence(local):
    client, settings = local
    ident = str(uuid4())
    data = {"upload_id": ident, "placeholder": f"ngopilot-upload://{ident}/form.png"}
    assert (
        client.post("/api/uploads", data=data, files={"file": ("other.png", b"abc")}).status_code
        == 422
    )
    response = client.post("/api/uploads", data=data, files={"file": ("form.png", b"abc")})
    assert response.status_code == 201
    assert "path" not in response.json()
    assert response.json()["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert (
        client.post("/api/uploads", data=data, files={"file": ("form.png", b"abc")}).status_code
        == 409
    )
    ident = str(uuid4())
    data = {"upload_id": ident, "placeholder": f"ngopilot-upload://{ident}/form.png"}
    assert (
        client.post("/api/uploads", data=data, files={"file": ("form.png", b"a" * 21)}).status_code
        == 413
    )
    folder = settings.data_root / "tenants" / str(LOCAL_OWNER) / "uploads" / ident
    assert not (folder / "form.png").exists()
    assert (folder / "failed").is_file()


def test_only_registered_unchanged_artifacts_download(local):
    client, settings = local
    workflow = settings.data_root / "tenants" / str(LOCAL_OWNER) / "workflow"
    output = workflow / "jobs" / "paper" / "job_1" / "outputs" / "result.xlsx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"verified result")
    with sqlite3.connect(workflow / "jobs.sqlite3") as db:
        db.execute(
            "CREATE TABLE artifacts(path TEXT, size_bytes INTEGER, sha256 TEXT, media_type TEXT)"
        )
        db.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?)",
            (
                str(output),
                output.stat().st_size,
                hashlib.sha256(output.read_bytes()).hexdigest(),
                "application/octet-stream",
            ),
        )
    link = client.get("/api/artifacts/url", params={"path": str(output)}).json()["url"]
    assert client.get(link).content == b"verified result"
    assert client.get("/api/artifacts/url", params={"path": "/etc/passwd"}).status_code == 404
    output.write_bytes(b"tampered result")
    assert client.get(link).status_code == 404


def test_production_cannot_enable_local_transport(tmp_path):
    with pytest.raises(ValueError, match="APP_ENV=local"):
        create_local_app(Settings(app_env="test", data_root=tmp_path), Path("/unused"))
    with pytest.raises(ValueError, match="loopback"):
        create_local_app(
            Settings(app_env="local", data_root=tmp_path, public_api_url="http://0.0.0.0:8310"),
            Path("/unused"),
        )


def test_confirmation_is_bound_to_current_task_revision(local, monkeypatch):
    from ngopilot_mcp.config import load_settings
    from ngopilot_mcp.shared.human_confirmation import HumanConfirmations
    from ngopilot_mcp.shared.runtime import Runtime
    from ngopilot_mcp.shared.errors import ToolError

    client, settings = local
    workflow = settings.data_root / "tenants" / str(LOCAL_OWNER) / "workflow"
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(workflow))
    runtime = Runtime(load_settings())
    tool = "careflow_paper_forms_to_excel"
    job = runtime.create_job(tool_name=tool, request_id=None, input_payload={})
    runtime.jobs.update_job(
        job_id=job.job_id,
        state="pending_review",
        native_status="pending_review",
        result={"records": []},
        native_refs={},
        warnings=[],
        next_operations=["review"],
        error=None,
    )
    current = client.get(f"/api/workflows/{job.job_id}").json()
    payload = {"confirm_all": True}
    confirmations = HumanConfirmations(workflow)
    with pytest.raises(ToolError):
        confirmations.require(
            tool=tool,
            job_id=job.job_id,
            operation="review",
            payload=payload,
            revision=current["result"],
        )
    body = {
        "operation": "review",
        "input": payload,
        "reviewer": "Test reviewer",
        "revision": "stale",
    }
    assert client.post(f"/api/workflows/{job.job_id}/confirm", json=body).status_code == 409
    body["revision"] = current["revision"]
    assert client.post(f"/api/workflows/{job.job_id}/confirm", json=body).status_code == 200
    confirmations.require(
        tool=tool,
        job_id=job.job_id,
        operation="review",
        payload=payload,
        revision=current["result"],
    )
    with pytest.raises(ToolError):
        confirmations.require(
            tool=tool,
            job_id=job.job_id,
            operation="review",
            payload={"confirm_all": False},
            revision=current["result"],
        )
