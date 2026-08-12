"""Static, host-safe manifest for the paper-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

from .schemas import public_input_schema

MANIFEST = ToolManifest(
    name="careflow_paper_forms_to_excel",
    description=(
        "Convert completed CareFlow volunteer-form JPG, JPEG, or PNG attachments "
        "into an Excel workbook. Start immediately with "
        "{\"operation\":\"start\",\"input\":{\"image_paths\":[\"/absolute/"
        "form.jpg\"]}}; title and other metadata are optional. Reuse the returned "
        "job_id for status and export. Extracted values are approved automatically; "
        "when export appears in next_operations, call it immediately without asking "
        "for review or confirmation. After export, give the user the verified .xlsx "
        "path in artifacts[0].path. Excludes government forms, audio, and existing "
        "spreadsheets."
    ),
    worker="careflow",
    operations=("start", "status", "export"),
    input_schema=public_input_schema(),
)
