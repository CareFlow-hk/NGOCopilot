"""Host-safe manifest for the CareFlow meeting-notes MCP tool."""

from ngopilot_mcp.shared.tool_api import ToolManifest

from .schemas import public_input_schema

MANIFEST = ToolManifest(
    name="careflow_meeting_notes",
    description=(
        "Create reviewed meeting or home-visit notes from one absolute audio "
        "path and one absolute CareFlow DOCX template path. Continue the same "
        "job through status, review, export, or burn. Excludes PDFs, images, and "
        "spreadsheets. Present slot suggestions and wait for the user's explicit "
        "confirmation/corrections before review. Export only reviewed content; "
        "burn requires a separate explicit request to destroy retained source material."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export", "burn"),
    input_schema=public_input_schema(),
    human_confirmation_operations=("review", "burn"),
)
