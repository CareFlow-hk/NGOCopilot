"""Projection of this tool's native source into durable MCP job state."""

from ngopilot_mcp.shared.errors import ToolError


def projection(result: dict) -> tuple[str, list[str]]:
    if not isinstance(result.get("source"), dict) or not isinstance(
        result.get("activities"), list
    ):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR", "Scheduler returned an invalid source snapshot."
        )
    pages = result.get("pages", [])
    if any(page["status"] in {"queued", "extracting"} for page in pages):
        return "running", ["status"]
    if any(page["status"] == "failed" for page in pages):
        return "blocked", ["status"]
    records = result["activities"]
    if not records:
        return "blocked", ["status"]
    if any(item["review_status"] == "draft" for item in records):
        return "pending_review", ["status", "review"]
    return "reviewed", ["status", "review", "export"]
