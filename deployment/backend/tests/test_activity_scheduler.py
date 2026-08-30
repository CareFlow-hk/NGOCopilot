from __future__ import annotations

import asyncio
import threading
from datetime import date, time
from uuid import uuid4

from ngopilot_gateway import activity_routes
from ngopilot_gateway.activity_routes import (
    ActivityImportJob,
    ActivityInput,
    activities_from_kimi_json,
    activity_import_jobs,
    extract_activities_from_text_parts,
    extract_activities_with_kimi,
    extract_activity_document,
    merge_extracted_activities,
    run_activity_import_job,
)
from ngopilot_gateway.activity_scheduler import (
    ExtractedActivity,
    ExtractedSession,
    check_conflicts,
    extract_activities,
    is_image_document,
    pdf_to_text,
    pdf_to_text_parts,
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


def test_pdf_to_text_splits_an_oversized_notice_into_two_parts(monkeypatch) -> None:
    class Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class Reader:
        is_encrypted = False
        pages = [Page("A" * 60), Page("B" * 60)]

        def __init__(self, _source: object) -> None:
            pass

    monkeypatch.setattr("ngopilot_gateway.activity_scheduler.PdfReader", Reader)

    parts = pdf_to_text_parts(b"%PDF", max_chars=70)

    assert len(parts) == 2
    assert all(len(part) <= 70 for part in parts)
    assert "".join(parts) == "A" * 60 + "B" * 60


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


async def test_pdf_halves_are_processed_and_merged(settings, monkeypatch) -> None:
    calls: list[str] = []

    async def extract_part(text: str, _filename: str, _settings: object) -> list[ExtractedActivity]:
        calls.append(text)
        return [
            ExtractedActivity(
                name="Tai Chi Class",
                location="Community Hall",
                sessions=[
                    ExtractedSession(
                        session_date=date.fromisoformat("2026-09-01" if text == "first" else "2026-09-08"),
                        start_time=time(10, 0),
                        end_time=time(11, 0),
                    )
                ],
            )
        ]

    monkeypatch.setattr(activity_routes, "extract_activities_with_kimi", extract_part)

    activities, method = await extract_activities_from_text_parts(
        ["first", "second"], "large-notice.pdf", settings
    )

    assert calls == ["first", "second"]
    assert method == "kimi"
    assert len(activities) == 1
    assert len(activities[0].sessions) == 2


def test_merge_extracted_activities_deduplicates_repeated_sessions() -> None:
    session = ExtractedSession(date(2026, 9, 1), time(10, 0), time(11, 0))
    activities = merge_extracted_activities(
        [[ExtractedActivity(name="Tai Chi", sessions=[session])], [ExtractedActivity(name="tai chi", sessions=[session])]]
    )

    assert len(activities) == 1
    assert len(activities[0].sessions) == 1


async def test_background_import_job_reaches_review_ready(settings, monkeypatch) -> None:
    job_id = uuid4()
    user_id = uuid4()
    activity_import_jobs[job_id] = ActivityImportJob(user_id=user_id)

    async def extract_document(
        _content: bytes, filename: str, _settings: object
    ) -> dict[str, object]:
        return {
            "source_filename": filename,
            "extraction_method": "kimi",
            "activities": [{"name": "Tai Chi Class", "sessions": []}],
        }

    monkeypatch.setattr(activity_routes, "extract_activity_document", extract_document)

    await run_activity_import_job(job_id, b"%PDF", "programme.pdf", settings)

    job = activity_import_jobs.pop(job_id)
    assert job.status == "ready"
    assert job.result is not None
    assert job.result["source_filename"] == "programme.pdf"


async def test_background_import_job_yields_before_extraction(settings, monkeypatch) -> None:
    job_id = uuid4()
    activity_import_jobs[job_id] = ActivityImportJob(user_id=uuid4())
    extraction_started = asyncio.Event()

    async def extract_document(
        _content: bytes, _filename: str, _settings: object
    ) -> dict[str, object]:
        extraction_started.set()
        return {"activities": []}

    monkeypatch.setattr(activity_routes, "extract_activity_document", extract_document)
    task = asyncio.create_task(
        run_activity_import_job(job_id, b"%PDF", "programme.pdf", settings)
    )

    await asyncio.sleep(0)

    assert not extraction_started.is_set()
    await task
    activity_import_jobs.pop(job_id)


async def test_pdf_parsing_runs_outside_event_loop(settings, monkeypatch) -> None:
    parser_thread_id: int | None = None

    def parse_document(
        _filename: str, _content: bytes, *, max_chars: int
    ) -> list[str]:
        nonlocal parser_thread_id
        del max_chars
        parser_thread_id = threading.get_ident()
        return ["Activity: Tai Chi\n2026-09-01 10:00-11:00"]

    async def extract_parts(
        _parts: list[str], _filename: str, _settings: object
    ) -> tuple[list[ExtractedActivity], str]:
        return [], "rules"

    monkeypatch.setattr(activity_routes, "source_text_parts", parse_document)
    monkeypatch.setattr(activity_routes, "extract_activities_from_text_parts", extract_parts)
    event_loop_thread_id = threading.get_ident()

    await extract_activity_document(b"%PDF", "programme.pdf", settings)

    assert parser_thread_id is not None
    assert parser_thread_id != event_loop_thread_id


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
