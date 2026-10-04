import hashlib
import sqlite3
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ngopilot_gateway.config import Settings
from ngopilot_gateway.local import LOCAL_OWNER, create_local_app
from ngopilot_gateway.local_accounts import (
    GRANT_SECONDS,
    SESSION_IDLE_SECONDS,
    AccountError,
    LocalAccounts,
)

PASSWORD = "correct horse battery staple"
ORIGIN = "http://127.0.0.1:8310"


@pytest.fixture
def app(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<h1>renderer</h1>")
    settings = Settings(app_env="local", data_root=tmp_path / "data", public_api_url=ORIGIN)
    return create_local_app(settings, frontend)


def client_for(app) -> TestClient:
    return TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def token_from(link: str) -> str:
    return link.split("#set-password=", 1)[1]


def sign_in(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture
def admin(app):
    with client_for(app) as client:
        token = app.state.accounts.bootstrap("admin@example.org", "Admin", LOCAL_OWNER)
        client.post("/api/auth/set-password", json={"token": token, "password": PASSWORD})
        assert sign_in(client, "admin@example.org").status_code == 200
        yield client


def invite(admin: TestClient, email: str, role: str = "MEMBER") -> dict:
    response = admin.post("/api/admin/users", json={"email": email, "name": "Staff", "role": role})
    assert response.status_code == 201
    return response.json()


def member_client(app, admin: TestClient, email: str = "staff@example.org") -> TestClient:
    created = invite(admin, email)
    client = client_for(app)
    assert (
        client.post(
            "/api/auth/set-password",
            json={"token": token_from(created["link"]), "password": PASSWORD},
        ).status_code
        == 200
    )
    assert sign_in(client, email).status_code == 200
    return client


def test_no_anonymous_access_or_public_registration(app):
    with client_for(app) as client:
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/ws-tickets").status_code == 401
        assert client.get("/api/admin/users").status_code == 401
        assert client.get("/api/runtime").json()["GOOSE_WORKING_DIR"] == ""
        assert client.get("/healthz").status_code == 200
        response = client.post(
            "/api/auth/register", json={"email": "a@example.org", "password": PASSWORD}
        )
        assert response.status_code == 401


def test_invitation_link_is_single_use_and_cookie_is_strict(app, admin):
    created = invite(admin, "staff@example.org")
    assert created["user"]["pending"] is True
    assert created["link"].startswith(f"{ORIGIN}/#set-password=")
    with client_for(app) as client:
        body = {"token": token_from(created["link"]), "password": "too short"}
        assert client.post("/api/auth/set-password", json=body).status_code == 400
        body["password"] = PASSWORD
        assert client.post("/api/auth/set-password", json=body).status_code == 200
        assert client.post("/api/auth/set-password", json=body).status_code == 400
        response = sign_in(client, "staff@example.org")
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
        assert response.json()["user"]["role"] == "MEMBER"
        assert sign_in(client, "staff@example.org", "wrong password value").status_code == 401


def test_writes_require_same_origin_json(admin):
    assert admin.post("/api/auth/logout", headers={"Origin": ""}).status_code == 403
    response = admin.post(
        "/api/admin/users",
        content='{"email":"x@example.org","name":"X","role":"MEMBER"}',
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415


def test_members_cannot_administer(app, admin):
    with member_client(app, admin) as member:
        assert member.get("/api/admin/users").status_code == 403
        assert member.get("/api/admin/audit").status_code == 403
        assert (
            member.post(
                "/api/admin/users", json={"email": "x@example.org", "name": "X", "role": "ADMIN"}
            ).status_code
            == 403
        )
        assert member.get("/api/auth/sessions").json()["sessions"][0]["current"] is True


def test_each_account_has_an_isolated_workspace(app, admin):
    settings = app.state.processes.settings
    with member_client(app, admin) as member:
        member_id = UUID(member.get("/api/auth/me").json()["user"]["id"])
        assert member_id != LOCAL_OWNER
        assert member.get("/api/runtime").json()["GOOSE_WORKING_DIR"].endswith(str(member_id))
        ident = str(uuid4())
        data = {"upload_id": ident, "placeholder": f"ngopilot-upload://{ident}/form.png"}
        response = member.post("/api/uploads", data=data, files={"file": ("form.png", b"abc")})
        assert response.status_code == 201
        tenants = settings.data_root / "tenants"
        assert (tenants / str(member_id) / "uploads" / ident / "form.png").is_file()
        assert not (tenants / str(LOCAL_OWNER) / "uploads" / ident).exists()

        workflow = tenants / str(member_id) / "workflow"
        output = workflow / "jobs" / "paper" / "job_1" / "outputs" / "result.xlsx"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"member result")
        with sqlite3.connect(workflow / "jobs.sqlite3") as db:
            db.execute(
                "CREATE TABLE artifacts(path TEXT, size_bytes INTEGER, sha256 TEXT, media_type TEXT)"
            )
            db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (str(output), 13, hashlib.sha256(b"member result").hexdigest(), "text/plain"),
            )
        link = member.get("/api/artifacts/url", params={"path": str(output)}).json()["url"]
        assert admin.get("/api/artifacts/url", params={"path": str(output)}).status_code == 404
        assert admin.get(link).status_code == 404
        assert member.get(link).content == b"member result"


def test_password_change_and_deactivation_revoke_sessions(app, admin):
    with member_client(app, admin) as member, client_for(app) as other:
        assert sign_in(other, "staff@example.org").status_code == 200
        body = {"oldPassword": "wrong password value", "password": "another long passphrase"}
        assert member.post("/api/auth/password", json=body).status_code == 400
        body["oldPassword"] = PASSWORD
        assert member.post("/api/auth/password", json=body).status_code == 200
        assert member.get("/api/auth/me").status_code == 401
        assert other.get("/api/auth/me").status_code == 401
        assert sign_in(member, "staff@example.org", "another long passphrase").status_code == 200

        user = member.get("/api/auth/me").json()["user"]
        change = {"name": user["name"], "role": "MEMBER", "disabled": True}
        assert admin.patch(f"/api/admin/users/{user['id']}", json=change).status_code == 200
        assert member.get("/api/auth/me").status_code == 401
        assert sign_in(member, "staff@example.org", "another long passphrase").status_code == 401
        assert admin.post(f"/api/admin/users/{user['id']}/reset").status_code == 400


def test_revoke_other_sessions_keeps_current(app, admin):
    with client_for(app) as other:
        assert sign_in(other, "admin@example.org").status_code == 200
        assert len(admin.get("/api/auth/sessions").json()["sessions"]) == 2
        assert admin.post("/api/auth/sessions/revoke-others").status_code == 200
        assert admin.get("/api/auth/me").status_code == 200
        assert other.get("/api/auth/me").status_code == 401


def test_last_active_admin_is_protected(admin):
    me = admin.get("/api/auth/me").json()["user"]
    change = {"name": me["name"], "role": "MEMBER", "disabled": False}
    response = admin.patch(f"/api/admin/users/{me['id']}", json=change)
    assert response.status_code == 409


def test_reset_link_replaces_previous_link(app, admin):
    created = invite(admin, "staff@example.org")
    first = token_from(created["link"])
    second = token_from(
        admin.post(f"/api/admin/users/{created['user']['id']}/reset").json()["link"]
    )
    with client_for(app) as client:
        body = {"token": first, "password": PASSWORD}
        assert client.post("/api/auth/set-password", json=body).status_code == 400
        body["token"] = second
        assert client.post("/api/auth/set-password", json=body).status_code == 200


def test_audit_records_actions_without_secrets(admin):
    invite(admin, "staff@example.org")
    events = admin.get("/api/admin/audit").json()["events"]
    actions = {event["action"] for event in events}
    assert {"user_created", "password_link_created", "password_set", "login"} <= actions
    assert PASSWORD not in str(events)


def test_login_rate_limit(app, admin):
    with client_for(app) as client:
        # Every attempt counts, including the fixture's successful sign-in.
        for _ in range(9):
            assert sign_in(client, "admin@example.org", "wrong password value").status_code == 401
        response = sign_in(client, "admin@example.org")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "900"


def test_sessions_and_links_expire(tmp_path):
    clock = [1_000_000.0]
    accounts = LocalAccounts(tmp_path / "accounts.sqlite3", now=lambda: clock[0])
    token = accounts.bootstrap("admin@example.org", "Admin", LOCAL_OWNER)
    clock[0] += GRANT_SECONDS + 1
    with pytest.raises(AccountError):
        accounts.redeem(token, PASSWORD, "test")
    accounts.redeem(accounts.recover_admin("admin@example.org"), PASSWORD, "test")
    session_token, _ = accounts.login("admin@example.org", PASSWORD, "test")
    clock[0] += SESSION_IDLE_SECONDS - 10
    assert accounts.session(session_token) is not None
    clock[0] += SESSION_IDLE_SECONDS + 1
    assert accounts.session(session_token) is None
    with pytest.raises(AccountError, match="已有使用者"):
        accounts.bootstrap("other@example.org", "Other", uuid4())
    accounts.close()


def test_newer_database_version_is_refused(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(RuntimeError):
        LocalAccounts(path)
