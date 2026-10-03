"""Static, host-safe manifest for the government-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

from .schemas import public_input_schema

MANIFEST = ToolManifest(
    name="careflow_government_forms",
    description=(
        "Fill a supported Hong Kong welfare form from text, one absolute image "
        "path, or an elder profile. List templates when needed, then continue "
        "the same job through complete review and export. Excludes blank PDFs, "
        "volunteer visit forms, audio, Word, and Excel files. Show the suggested "
        "field values and await explicit human confirmation/corrections before review."
    ),
    worker="careflow",
    operations=("list_templates", "start", "status", "review", "export"),
    input_schema=public_input_schema(),
    human_confirmation_operations=("review",),
)
