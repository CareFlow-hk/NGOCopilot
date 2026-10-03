"""Source-scoped calendar/list export contracts."""

from pathlib import Path

from ngopilot_mcp.shared.errors import ToolError

FORMATS = {
    "ics": ("activity_calendar", "text/calendar"),
    "csv": ("activity_list", "text/csv"),
}


def validate_export(path: Path, kind: str) -> Path:
    if kind not in FORMATS or path.suffix != "." + kind or not path.is_file():
        raise ToolError("OUTPUT_VALIDATION_FAILED", "Scheduler export is missing.")
    data = path.read_bytes()
    if not data or (
        kind == "ics"
        and (not data.startswith(b"BEGIN:VCALENDAR") or b"END:VCALENDAR" not in data)
    ):
        raise ToolError("OUTPUT_VALIDATION_FAILED", "Scheduler export is incomplete.")
    return path
