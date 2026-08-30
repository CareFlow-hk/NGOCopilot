from __future__ import annotations

from datetime import date, time
from uuid import uuid4

from ngopilot_gateway import activity_routes
from ngopilot_gateway.activity_routes import (
    ActivityInput,
    activities_from_kimi_json,
    extract_activities_with_kimi,
)
from ngopilot_gateway.activity_scheduler import (
    check_conflicts,
    extract_activities,
    is_image_document,
    pdf_to_text,
)
from ngopilot_gateway.db import Database


def test_extract_activities_materializes_each_date_as_a_session() -> None:
    activities = extract_activities(
        """
        Activity: Tai Chi Class
        Location: Community Hall A
        2026-09-01, 2026-09-08 10:00-11:00
        """,
        "autumn-programme.txt",
    )

    assert len(activities) == 1
    assert activities[0].name == "Tai Chi Class"
    assert activities[0].location == "Community Hall A"
    assert [session.session_date.isoformat() for session in activities[0].sessions] == [
        "2026-09-01",
        "2026-09-08",
    ]
    assert activities[0].sessions[0].start_time is not None
    assert activities[0].sessions[0].end_time is not None


def test_extract_activities_keeps_inline_activity_name_separate_from_date() -> None:
    activities = extract_activities(
        "Activity: Smartphone Class | 2026-09-01 | 14:00-15:30",
        "programme.txt",
    )

    assert activities[0].name == "Smartphone Class"
    assert activities[0].sessions[0].session_date.isoformat() == "2026-09-01"


def test_check_conflicts_reports_overlaps_and_incomplete_times() -> None:
    new_sessions = [
        {
            "id": "new-1",
            "session_date": "2026-09-08",
            "start_time": "10:30:00",
            "end_time": "11:30:00",
            "activity_name": "Health Talk",
        },
        {
            "id": "new-2",
            "session_date": "2026-09-15",
            "start_time": None,
            "end_time": None,
            "activity_name": "Health Talk",
        },
    ]
    existing_sessions = [
        {
            "id": "existing-1",
            "session_date": "2026-09-08",
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "activity_name": "Smartphone Class",
        }
    ]

    result = check_conflicts(new_sessions, existing_sessions)

    assert result["has_conflict"] is True
    assert result["conflicts"][0]["existing_activity"] == "Smartphone Class"
    assert result["has_time_uncertainty"] is True


def test_back_to_back_sessions_do_not_conflict() -> None:
    result = check_conflicts(
        [{"session_date": "2026-09-08", "start_time": "11:00:00", "end_time": "12:00:00"}],
        [{"session_date": "2026-09-08", "start_time": "10:00:00", "end_time": "11:00:00"}],
    )

    assert result["has_conflict"] is False
    assert result["has_time_uncertainty"] is False


def test_supported_image_notices_use_the_vision_extraction_path() -> None:
    assert is_image_document("programme.jpg") is True
    assert is_image_document("programme.pdf") is False


def test_pdf_to_text_extracts_pages_and_bounds_model_input(monkeypatch) -> None:
    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Reader:
        is_encrypted = False
        pages = [Page("First notice"), Page("Second notice")]

        def __init__(self, _source: object) -> None:
            pass

    monkeypatch.setattr("ngopilot_gateway.activity_scheduler.PdfReader", Reader)

    assert pdf_to_text(b"%PDF", max_chars=100) == "First notice\nSecond notice"


def test_kimi_activity_json_is_validated_for_review() -> None:
    activities = activities_from_kimi_json(
        '{"activities":[{"name":"Tai Chi Class","location":"Community Hall",'
        '"sessions":[{"session_date":"2026-09-08","start_time":"10:00",'
        '"end_time":"11:00"}]}]}'
    )

    assert activities[0].name == "Tai Chi Class"
    assert activities[0].sessions[0].session_date == date(2026, 9, 8)
    assert activities[0].sessions[0].start_time == time(10, 0)


async def test_kimi_extraction_requests_json_from_the_configured_model(settings, monkeypatch) -> None:
    request: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"activities":[{"name":"Health Talk","sessions":['
                                '{"session_date":"2026-09-10","start_time":"14:00",'
                                '"end_time":"15:00"}]}]}'
                            )
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def post(self, _url: str, **kwargs: object) -> Response:
            request.update(kwargs)
            return Response()

    monkeypatch.setattr(activity_routes.httpx, "AsyncClient", lambda **_kwargs: Client())

    activities = await extract_activities_with_kimi("2026-09-10 14:00-15:00", "notice.pdf", settings)

    assert activities is not None
    assert activities[0].name == "Health Talk"
    payload = request["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == settings.goose_model
    assert payload["response_format"] == {"type": "json_object"}


def test_activity_confirmation_keeps_database_date_and_time_types() -> None:
    activity = ActivityInput.model_validate(
        {
            "name": "Smartphone Class",
            "sessions": [
                {"session_date": "2026-09-08", "start_time": "14:00", "end_time": "15:30"}
            ],
        }
    )

    session = activity.model_dump()["sessions"][0]
    assert session["session_date"] == date(2026, 9, 8)
    assert session["start_time"] == time(14, 0)


async def test_activity_date_filter_keeps_a_database_date_type() -> None:
    class Pool:
        def __init__(self) -> None:
            self.args: tuple[object, ...] | None = None

        async def fetch(self, *args: object):
            self.args = args
            return []

    pool = Pool()
    database = Database.__new__(Database)
    database.pool = pool  # type: ignore[assignment]
    filter_date = date.fromisoformat("2026-09-08")

    assert await database.list_activities(uuid4(), on_date=filter_date) == []
    assert pool.args is not None
    assert pool.args[3] == filter_date
