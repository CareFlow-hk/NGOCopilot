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
        "job_id for status, review and export. Show extracted fields and source images "
        "to the user. Only call review after explicit human confirmation or corrections; "
        "never infer approval from upload, start or status. Export includes only reviewed "
        "records; clearly disclose any omitted unreviewed rows. After export, give the verified .xlsx "
        "path in artifacts[0].path. Excludes government forms, audio, and existing "
        "spreadsheets."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export"),
    input_schema=public_input_schema(),
)
