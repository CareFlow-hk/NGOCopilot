from __future__ import annotations

import io
import json
from urllib.parse import quote

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.shared.redaction import redact_text
from ngopilot_mcp.workers.base import _append_log


def test_error_projection_redacts_nested_provider_credentials(monkeypatch):
    secret = "example-provider-secret/123"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    original = {
        "provider": [{"url": f"https://example.test?key={quote(secret, safe='')}"}]
    }
    error = ToolError(
        "PROVIDER_ERROR",
        f"Request failed: {secret}",
        details=original,
        native_message=f"Authorization: Bearer {secret}",
    )
    serialized = json.dumps(error.as_dict())
    assert secret not in serialized
    assert quote(secret, safe="") not in serialized
    assert "[REDACTED]" in serialized
    assert original["provider"][0]["url"].endswith(quote(secret, safe=""))


def test_bearer_not_in_environment_is_still_redacted():
    assert redact_text("Authorization: Bearer unknown.oauth.token") == (
        "Authorization: Bearer [REDACTED]"
    )


def test_worker_log_redacts_before_truncation(tmp_path, monkeypatch):
    secret = "test-private-key-12345"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    request = {"job_root": str(tmp_path), "operation": "start"}
    _append_log(request, secret + "x" * 999_999)
    content = (tmp_path / "logs/start.native.log").read_text()
    assert "private-key-12345" not in content


def test_diagnostics_preserve_nonsecret_error_information():
    assert redact_text("Invalid template_id; retry in 30 seconds") == (
        "Invalid template_id; retry in 30 seconds"
    )


def test_worker_failure_redacts_protocol_and_log(tmp_path, monkeypatch, capsys):
    from ngopilot_mcp.workers import base

    secret = "example-private-token-987"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    request = {"job_root": str(tmp_path), "operation": "start"}
    monkeypatch.setattr(base.sys, "stdin", io.StringIO(json.dumps(request)))
    monkeypatch.setattr(base, "_validate_request", lambda *args: None)
    monkeypatch.setattr(base, "_configure_application", lambda *args: None)

    def failing_provider(*args):
        raise RuntimeError(f"Upstream rejected credential {secret}")

    monkeypatch.setattr(base, "_invoke", failing_provider)
    with pytest.raises(SystemExit):
        base.run_worker("careflow", set())
    response = capsys.readouterr().out
    assert json.loads(response)["ok"] is False
    assert secret not in response
    assert secret not in (tmp_path / "logs/start.native.log").read_text()
