from __future__ import annotations

from unittest.mock import Mock

from ngopilot_gateway import __main__ as entrypoint


def test_production_entrypoint_suppresses_ticket_bearing_websocket_info_logs(
    settings, monkeypatch
) -> None:
    run = Mock()
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.uvicorn, "run", run)

    entrypoint.main()

    run.assert_called_once()
    options = run.call_args.kwargs
    assert options["access_log"] is False
    assert options["log_level"] == "warning"
