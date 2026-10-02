from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ngopilot_mcp.workers.base import _configure_application


@pytest.mark.parametrize("worker", ["careflow", "rostercopiilot"])
def test_native_relative_writes_stay_out_of_source(tmp_path, monkeypatch, worker):
    source = tmp_path / "immutable-source"
    source.mkdir()
    data = tmp_path / "tenant-data"
    # Register cwd, sys.path and environment changes for automatic restoration.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(os, "environ", dict(os.environ))
    _configure_application(
        worker,
        {"application_source": str(source), "app_data_root": str(data)},
    )
    Path("logs").mkdir()
    Path("logs/native.log").write_text("synthetic test")
    assert (data / "logs/native.log").is_file()
    assert list(source.iterdir()) == []
