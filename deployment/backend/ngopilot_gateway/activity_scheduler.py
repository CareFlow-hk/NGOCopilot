"""Small, deterministic activity-document parsing and conflict helpers."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, time
from io import BytesIO
from pathlib import Path

DATE_PATTERN = re.compile(r"(?<!\d)(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?!\d)|(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日")
TIME_RANGE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2}):([0-5]\d)\s*(?:-|–|—|至|to)\s*(\d{1,2}):([0-5]\d)(?!\d)",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"(?:activity(?:\s+name)?|活動(?:名稱|名)?|課程(?:名稱)?)\s*[:：]\s*(.+)", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"(?:location|venue|地點|場地)\s*[:：]\s*(.+)", re.IGNORECASE)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class ExtractedSession:
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    raw_date_text: str | None = None


@dataclass(slots=True)
class ExtractedActivity:
    name: str
    description: str | None = None
    location: str | None = None
    activity_code: str | None = None
    sessions: list[ExtractedSession] = field(default_factory=list)


def source_text(filename: str, content: bytes) -> str:
    """Read common document inputs without treating extracted data as authoritative."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:  # pragma: no cover - deployment dependency guard
            raise ValueError("PDF extraction is not available on this server") from error
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix in {".txt", ".csv", ".md", ".html", ".htm"} or not suffix:
        return content.decode("utf-8", errors="replace")
    raise ValueError("Use a text, CSV, HTML, or text-based PDF activity notice")


def is_image_document(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_SUFFIXES


def _dates(text: str) -> list[tuple[date, str]]:
    values: list[tuple[date, str]] = []
    for match in DATE_PATTERN.finditer(text):
        year, month, day = (match.group(1), match.group(2), match.group(3))
        if year is None:
            year, month, day = match.group(4), match.group(5), match.group(6)
        try:
            values.append((date(int(year), int(month), int(day)), match.group(0)))
        except ValueError:
            continue
    return values


def _time_range(text: str) -> tuple[time | None, time | None]:
    match = TIME_RANGE_PATTERN.search(text)
    if match is None:
        return None, None
    return time(int(match.group(1)), int(match.group(2))), time(int(match.group(3)), int(match.group(4)))


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" |,;；")
    return value[:limit] or None


def extract_activities(text: str, fallback_name: str) -> list[ExtractedActivity]:
    """Extract reviewable rows from the most common activity-notice layouts.

    The parser intentionally errs toward producing incomplete sessions. Users correct
    them in review; missing times are later handled as uncertainty, never as a pass.
    """
    activities: OrderedDict[str, ExtractedActivity] = OrderedDict()
    current_name = _clean(Path(fallback_name).stem.replace("_", " "), 200) or "Untitled activity"
    current_location: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name_match = NAME_PATTERN.search(line)
        location_match = LOCATION_PATTERN.search(line)
        if name_match:
            name_value = name_match.group(1)
            name_dates = _dates(name_value)
            if name_dates:
                name_value = name_value[: name_value.find(name_dates[0][1])]
            current_name = _clean(name_value, 200) or current_name
        if location_match:
            current_location = _clean(location_match.group(1), 300)

        found_dates = _dates(line)
        if not found_dates:
            continue
        table_name = _clean(line[: found_dates[0][1] and line.find(found_dates[0][1])], 200)
        if table_name and not NAME_PATTERN.search(line) and not table_name.lower().startswith(("date", "日期")):
            current_name = table_name
        activity = activities.setdefault(
            current_name,
            ExtractedActivity(name=current_name, location=current_location),
        )
        if current_location and not activity.location:
            activity.location = current_location
        start, end = _time_range(line)
        for parsed_date, raw_date in found_dates:
            activity.sessions.append(ExtractedSession(parsed_date, start, end, raw_date))

    if not activities:
        return [ExtractedActivity(name=current_name, description=_clean(text, 4000))]
    return list(activities.values())


def sessions_conflict(
    new_session: dict[str, object], existing_session: dict[str, object]
) -> bool:
    """Whether two fully-known sessions overlap. Endpoints touching are allowed."""
    if new_session["session_date"] != existing_session["session_date"]:
        return False
    new_start, new_end = new_session.get("start_time"), new_session.get("end_time")
    old_start, old_end = existing_session.get("start_time"), existing_session.get("end_time")
    if not all((new_start, new_end, old_start, old_end)):
        return False
    return str(new_start) < str(old_end) and str(old_start) < str(new_end)


def check_conflicts(
    new_sessions: list[dict[str, object]], existing_sessions: list[dict[str, object]]
) -> dict[str, object]:
    conflicts: list[dict[str, object]] = []
    insufficient: list[dict[str, object]] = []
    for new_session in new_sessions:
        same_day = [item for item in existing_sessions if item["session_date"] == new_session["session_date"]]
        if not new_session.get("start_time") or not new_session.get("end_time"):
            insufficient.append(new_session)
            continue
        for existing in same_day:
            if not existing.get("start_time") or not existing.get("end_time"):
                insufficient.append(existing)
            elif sessions_conflict(new_session, existing):
                conflicts.append(
                    {
                        "new_session": new_session,
                        "existing_session": existing,
                        "existing_activity": existing.get("activity_name"),
                    }
                )
    return {
        "has_conflict": bool(conflicts),
        "has_time_uncertainty": bool(insufficient),
        "conflicts": conflicts,
        "insufficient_time_sessions": insufficient,
    }
