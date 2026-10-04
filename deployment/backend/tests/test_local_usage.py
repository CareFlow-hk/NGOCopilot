from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ngopilot_gateway.config import Settings
from ngopilot_gateway.local import LOCAL_OWNER, create_local_app
from ngopilot_gateway.local_accounts import LocalAccounts
from ngopilot_gateway.local_usage import (
    LocalUsage,
    UsageLimitReached,
    prompt_images,
    week_start,
)

PASSWORD = "correct horse battery staple"
ORIGIN = "http://127.0.0.1:8310"


def prompt(*filenames: str) -> dict:
    text = " ".join(f"ngopilot-upload://{uuid4()}/{name}" for name in filenames)
    return {"method": "session/prompt", "params": {"prompt": [{"type": "text", "text": text}]}}


@pytest.fixture
def setup(tmp_path):
    clock = [datetime(2026, 10, 7, 4, tzinfo=timezone.utc).timestamp()]  # Wednesday
    accounts = LocalAccounts(tmp_path / "accounts.sqlite3", now=lambda: clock[0])
    usage = LocalUsage(accounts, message_limit=3, image_limit=2)
    sessions = {}
    for email, role in (("admin@example.org", "ADMIN"), ("staff@example.org", "MEMBER")):
        _, token = accounts.create_user(email, "Name", role)
        accounts.redeem(token, PASSWORD, "test")
        sessions[role] = accounts.login(email, PASSWORD, "test")[1]
    yield usage, sessions, clock
    accounts.close()


def test_week_starts_monday_hong_kong():
    # Sunday 16:30 UTC is Monday 00:30 in Hong Kong.
    start = week_start(datetime(2026, 10, 11, 16, 30, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-10-12T00:00:00+08:00"


def test_counts_distinct_images_and_pdfs_only():
    message = prompt("form.png", "brochure.PDF", "notes.docx", "photo.jpeg")
    assert prompt_images(message) == 3
    assert prompt_images(prompt()) == 0


def test_member_is_capped_and_admin_is_only_counted(setup):
    usage, sessions, _ = setup
    member, admin = sessions["MEMBER"], sessions["ADMIN"]
    usage.record_prompt(member, prompt("a.png", "b.pdf"))
    with pytest.raises(UsageLimitReached, match="圖片"):
        usage.record_prompt(member, prompt("c.png"))
    usage.record_prompt(member, prompt())
    usage.record_prompt(member, prompt())
    with pytest.raises(UsageLimitReached, match="對話次數"):
        usage.record_prompt(member, prompt())
    own = usage.own(member)
    assert (own["messages"], own["images"]) == (3, 2)
    assert own["limits"]["messages"] == 3

    for _ in range(5):
        usage.record_prompt(admin, prompt("x.png"))
    own = usage.own(admin)
    assert (own["messages"], own["images"]) == (5, 5)
    assert own["limits"]["messages"] is None


def test_confirmation_continuation_is_never_blocked(setup):
    usage, sessions, _ = setup
    member = sessions["MEMBER"]
    for _ in range(3):
        usage.record_prompt(member, prompt())
    usage.grant_continuation(member.user_id)
    usage.record_prompt(member, prompt())
    with pytest.raises(UsageLimitReached):
        usage.record_prompt(member, prompt())
    report = usage.report()
    row = report["usage"][str(member.user_id)][report["weeks"][0]]
    assert row == {"messages": 3, "images": 0, "continuations": 1}


def test_usage_resets_weekly_and_reports_recent_weeks(setup):
    usage, sessions, clock = setup
    member = sessions["MEMBER"]
    for _ in range(3):
        usage.record_prompt(member, prompt())
    clock[0] += 7 * 24 * 3600
    usage.record_prompt(member, prompt())
    report = usage.report()
    assert report["weeks"][:2] == ["2026-10-12", "2026-10-05"]
    history = report["usage"][str(member.user_id)]
    assert history["2026-10-12"]["messages"] == 1
    assert history["2026-10-05"]["messages"] == 3


def test_usage_endpoints(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<h1>renderer</h1>")
    settings = Settings(app_env="local", data_root=tmp_path / "data", public_api_url=ORIGIN)
    app = create_local_app(settings, frontend)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as admin:
        token = app.state.accounts.bootstrap("admin@example.org", "Admin", LOCAL_OWNER)
        admin.post("/api/auth/set-password", json={"token": token, "password": PASSWORD})
        admin.post("/api/auth/login", json={"email": "admin@example.org", "password": PASSWORD})
        own = admin.get("/api/auth/usage").json()
        assert own["messages"] == 0 and own["limits"]["messages"] is None
        report = admin.get("/api/admin/usage").json()
        assert report["limits"]["messages"] == 500 and report["limits"]["images"] == 200
        assert len(report["weeks"]) == 4

        link = admin.post(
            "/api/admin/users",
            json={"email": "staff@example.org", "name": "Staff", "role": "MEMBER"},
        ).json()["link"]
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as member:
            member.post(
                "/api/auth/set-password",
                json={"token": link.split("=", 1)[1], "password": PASSWORD},
            )
            member.post(
                "/api/auth/login", json={"email": "staff@example.org", "password": PASSWORD}
            )
            assert member.get("/api/auth/usage").json()["limits"]["messages"] == 500
            assert member.get("/api/admin/usage").status_code == 403
            # A failed confirmation grants no continuation.
            response = member.post("/api/workflows/job_missing/confirm", json={})
            assert response.status_code in {404, 422}
            credits = app.state.accounts._all("SELECT * FROM continuation_credits")
            assert credits == []
