"""Native local Scheduler HTTP adapter; no imports from another MCP tool."""

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from ngopilot_mcp.shared.errors import ToolError


def _request(path: str, payload=None, *, content_type="application/json", binary=False):
    base = os.getenv("NGOPILOT_SCHEDULER_URL", "")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "host.docker.internal"}
        or parsed.username
        or parsed.password
    ):
        raise ToolError(
            "SCHEDULER_UNAVAILABLE", "請由管理員連接本機 CareFlow Scheduler。"
        )
    body = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload, ensure_ascii=False).encode()
        if payload is not None
        else None
    )
    request = Request(
        base.rstrip("/") + path,
        data=body,
        headers={
            "Content-Type": content_type,
            "Host": f"127.0.0.1:{parsed.port or 80}",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            data = response.read(64 * 1024 * 1024)
        return data if binary else json.loads(data)
    except HTTPError as exc:
        try:
            message = json.loads(exc.read(8192)).get(
                "detail", "Scheduler request failed"
            )
        except (ValueError, AttributeError):
            message = "Scheduler request failed"
        raise ToolError(
            "SCHEDULER_REQUEST_FAILED", str(message), retryable=exc.code >= 500
        ) from None
    except URLError:
        raise ToolError(
            "SCHEDULER_UNAVAILABLE",
            "Scheduler 未連線；請啟動服務後重試。",
            retryable=True,
        ) from None


def _source_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ToolError("NATIVE_PROTOCOL_ERROR", "Invalid Scheduler source identifier.")
    return value


def _snapshot(source):
    source_id = _source_id(source["id"])
    pages = _request(f"/api/sources/{source_id}/pages")
    records = _request(f"/api/activities?source_id={source_id}")
    browser_url = os.getenv("NGOPILOT_SCHEDULER_BROWSER_URL", "http://127.0.0.1:8311")
    parsed = urlsplit(browser_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ToolError("INVALID_CONFIGURATION", "Scheduler browser URL must be local.")
    return {
        "source": source,
        "pages": pages,
        "activities": records,
        "calendar_url": f"{browser_url.rstrip('/')}?source={source_id}&view=calendar",
        "review_url": f"{browser_url.rstrip('/')}?source={source_id}&view=review",
        "warnings": [p["reason"] for p in pages if p["status"] == "failed"],
    }


def handle(operation, payload):
    if operation == "start":
        path = Path(payload["pdf_path"])
        boundary = "ngopilot" + uuid4().hex
        # A fixed safe multipart filename prevents filename/header injection.
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="activity-brochure.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        source = _request(
            "/api/sources",
            body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        source_id = _source_id(source["id"])
        pages = payload.get("pages") or list(range(1, source["pages"] + 1))
        if any(not 1 <= page <= source["pages"] for page in pages):
            raise ToolError("INVALID_REQUEST", "選擇的頁數超出小冊子範圍。")
        snapshot = _snapshot(source)
        # Deduplicated sources with reviewed records retain human work.
        existing = {
            record["page"]
            for record in snapshot["activities"]
            if record["revision"] > 1 or record["review_status"] != "draft"
        }
        selected = [page for page in pages if page not in existing]
        if selected:
            _request(
                f"/api/sources/{source_id}/extract",
                {"pages": selected, "year": payload["year"]},
            )
        return _snapshot(source)
    source = payload["source"]
    source_id = _source_id(source["id"])
    if operation == "review":
        _request(
            f"/api/sources/{source_id}/review-batch",
            {"reviews": payload["reviews"], "reviewer": payload["reviewer"]},
        )
    result = _snapshot(source)
    if operation == "export":
        paths = {}
        for kind in ("ics", "csv"):
            data = _request(f"/api/sources/{source_id}/calendar.{kind}", binary=True)
            path = Path.cwd() / f"{source_id}-{uuid4().hex[:8]}.{kind}"
            path.write_bytes(data)
            paths[kind] = str(path)
        result["exports"] = paths
    return result
