from pathlib import Path

from ngopilot_mcp.shared.errors import InvalidRequestError, ToolError


def validate_pdf(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or path.suffix.lower() != ".pdf" or not path.is_file():
        raise InvalidRequestError("請提供已上傳的活動小冊子 PDF。")
    if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise InvalidRequestError("活動小冊子須小於 64 MB。")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise InvalidRequestError("檔案不是有效的 PDF。")
    return path


def validate_reviews(records: list[dict], reviews: list[dict]) -> None:
    expected = {record["id"]: record for record in records}
    ids = [item["id"] for item in reviews]
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise InvalidRequestError(
            "核對必須包含此批全部活動，不能包含其他小冊子的活動。"
        )
    if any(item["revision"] != expected[item["id"]]["revision"] for item in reviews):
        raise ToolError("STALE_REVIEW", "活動已更新，請重新讀取及核對。")
