from ngopilot_mcp.shared.tool_api import ToolManifest

from .schemas import public_input_schema

MANIFEST = ToolManifest(
    name="activity_scheduler",
    worker="scheduler",
    description=(
        "活動小冊子 PDF → 可核對活動 → ICS 日曆與活動清單。不是員工排班。"
        " start requires pdf_path and year; optional pages are one-based. Poll status while running."
        " review requires the complete reviews list with id, revision, data, status and note, plus reviewer;"
        " final confirmation comes only from the human task-card button. export requires all activities"
        " reviewed or excluded, and creates real ICS and CSV files. Result calendar_url opens the same"
        " source in the existing Scheduler calendar. No booking or registration is performed."
    ),
    operations=("start", "status", "review", "export"),
    input_schema=public_input_schema(),
    human_confirmation_operations=("review",),
)
