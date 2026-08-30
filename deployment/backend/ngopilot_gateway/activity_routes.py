"""Authenticated Activities API, isolated from the agent Automation scheduler."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import date, time
from time import monotonic
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .activity_scheduler import (
    ExtractedActivity,
    ExtractedSession,
    check_conflicts,
    extract_activities,
    is_image_document,
    source_text_parts,
)
from .auth import AuthContext, database, require_auth, settings
from .config import Settings
from .db import Database

router = APIRouter(prefix="/api", tags=["activities"])


class ActivitySessionInput(BaseModel):
    session_date: date
    start_time: time | None = None
    end_time: time | None = None
    raw_date_text: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def valid_time_range(self) -> "ActivitySessionInput":
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("end_time must be after start_time")
        return self


class ActivityInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=300)
    activity_code: str | None = Field(default=None, max_length=100)
    sessions: list[ActivitySessionInput] = Field(default_factory=list)

    @field_validator("name", "description", "location", "activity_code", mode="before")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ImportConfirmation(BaseModel):
    source_filename: str | None = Field(default=None, max_length=255)
    activities: list[ActivityInput] = Field(min_length=1, max_length=200)


class MemberInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class ScheduleRequest(BaseModel):
    activity_id: UUID
    override_conflicts: bool = False


class KimiActivityExtraction(BaseModel):
    activities: list[ActivityInput] = Field(default_factory=list, max_length=200)


@dataclass(slots=True)
class ActivityImportJob:
    user_id: UUID
    status: str = "processing"
    result: dict[str, object] | None = None
    error: str | None = None
    created_at: float = 0


activity_import_jobs: dict[UUID, ActivityImportJob] = {}
activity_import_tasks: set[asyncio.Task[None]] = set()
MAX_ACTIVITY_IMPORT_JOBS = 200


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def activity_as_dict(activity: ExtractedActivity) -> dict[str, object]:
    return {
        "name": activity.name,
        "description": activity.description,
        "location": activity.location,
        "activity_code": activity.activity_code,
        "sessions": [
            {
                "session_date": session.session_date.isoformat(),
                "start_time": session.start_time.isoformat() if session.start_time else None,
                "end_time": session.end_time.isoformat() if session.end_time else None,
                "raw_date_text": session.raw_date_text,
            }
            for session in activity.sessions
        ],
    }


async def extract_image_text(filename: str, content: bytes, app_settings: Settings) -> str:
    """Use the already-configured vision model only to transcribe a public notice."""
    if not app_settings.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image extraction is not configured",
        )
    suffix = filename.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    image = base64.b64encode(content).decode("ascii")
    payload = {
        "model": app_settings.careflow_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Transcribe this community activity notice faithfully. "
                            "Keep activity names, dates, start and end times, and locations. "
                            "Do not plan, recommend, or invent missing information."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}},
                ],
            }
        ],
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {app_settings.openrouter_api_key}"},
                json=payload,
            )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("The vision model returned no text")
        return text
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to read activity information from this image",
        ) from error


def activities_from_kimi_json(content: str) -> list[ExtractedActivity]:
    """Validate Kimi's response before allowing it into the import review."""
    parsed = json.loads(content)
    result = KimiActivityExtraction.model_validate(parsed)
    return [
        ExtractedActivity(
            name=activity.name,
            description=activity.description,
            location=activity.location,
            activity_code=activity.activity_code,
            sessions=[
                ExtractedSession(
                    session_date=session.session_date,
                    start_time=session.start_time,
                    end_time=session.end_time,
                    raw_date_text=session.raw_date_text,
                )
                for session in activity.sessions
            ],
        )
        for activity in result.activities
    ]


async def extract_activities_with_kimi(
    text: str, filename: str, app_settings: Settings
) -> list[ExtractedActivity] | None:
    """Ask the production Kimi model for reviewable, structured activity data."""
    if not app_settings.openrouter_api_key:
        return None

    payload = {
        "model": app_settings.goose_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract community activity notices into JSON. Return only a JSON object with "
                    "an activities array. Each activity has name, description, location, activity_code, "
                    "and sessions. Each session has session_date (YYYY-MM-DD), start_time (HH:MM or null), "
                    "end_time (HH:MM or null), and raw_date_text. Split every listed date into its own "
                    "session. Preserve missing information as null. Never invent dates, times, locations, "
                    "or activity names."
                ),
            },
            {
                "role": "user",
                "content": f"Source filename: {filename}\n\nNotice text:\n{text}",
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {app_settings.openrouter_api_key}"},
                json=payload,
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Kimi returned no structured activity data")
        activities = activities_from_kimi_json(content)
        return activities or None
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        # The review flow remains usable during a model outage. Its deterministic
        # parser produces incomplete fields rather than inventing them.
        return None


def merge_extracted_activities(
    activity_sets: list[list[ExtractedActivity]],
) -> list[ExtractedActivity]:
    """Merge Kimi results from PDF halves without duplicating an activity or session."""
    merged: dict[str, ExtractedActivity] = {}
    seen_sessions: dict[str, set[tuple[object, object, object]]] = {}
    for activities in activity_sets:
        for activity in activities:
            key = (activity.activity_code or activity.name).strip().casefold()
            current = merged.get(key)
            if current is None:
                current = ExtractedActivity(
                    name=activity.name,
                    description=activity.description,
                    location=activity.location,
                    activity_code=activity.activity_code,
                )
                merged[key] = current
                seen_sessions[key] = set()
            elif not current.description:
                current.description = activity.description
            if not current.location:
                current.location = activity.location
            if not current.activity_code:
                current.activity_code = activity.activity_code

            for session in activity.sessions:
                session_key = (session.session_date, session.start_time, session.end_time)
                if session_key not in seen_sessions[key]:
                    current.sessions.append(session)
                    seen_sessions[key].add(session_key)
    return list(merged.values())


async def extract_activities_from_text_parts(
    text_parts: list[str], filename: str, app_settings: Settings
) -> tuple[list[ExtractedActivity], str]:
    """Process one normal notice or two oversized PDF halves, then merge the review rows."""
    kimi_results = await asyncio.gather(
        *(extract_activities_with_kimi(text, filename, app_settings) for text in text_parts)
    )
    activity_sets: list[list[ExtractedActivity]] = []
    extraction_methods: list[str] = []
    for text, kimi_activities in zip(text_parts, kimi_results, strict=True):
        if kimi_activities is None:
            activity_sets.append(extract_activities(text, filename))
            extraction_methods.append("rules")
        else:
            activity_sets.append(kimi_activities)
            extraction_methods.append("kimi")
    return merge_extracted_activities(activity_sets), "+".join(sorted(set(extraction_methods)))


async def extract_activity_document(
    content: bytes, filename: str, app_settings: Settings
) -> dict[str, object]:
    """Produce the editable Review payload without persisting any activity."""
    try:
        text_parts = (
            [await extract_image_text(filename, content, app_settings)]
            if is_image_document(filename)
            else await asyncio.to_thread(
                source_text_parts,
                filename,
                content,
                max_chars=app_settings.max_activity_text_chars,
            )
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    activities, extraction_method = await extract_activities_from_text_parts(
        text_parts, filename, app_settings
    )
    return {
        "source_filename": filename,
        "extraction_method": extraction_method,
        "activities": [activity_as_dict(item) for item in activities],
    }


def trim_activity_import_jobs() -> None:
    if len(activity_import_jobs) < MAX_ACTIVITY_IMPORT_JOBS:
        return
    finished = sorted(
        (
            (job_id, job)
            for job_id, job in activity_import_jobs.items()
            if job.status != "processing"
        ),
        key=lambda item: item[1].created_at,
    )
    for job_id, _job in finished[: max(1, len(activity_import_jobs) // 4)]:
        activity_import_jobs.pop(job_id, None)


async def run_activity_import_job(
    job_id: UUID, content: bytes, filename: str, app_settings: Settings
) -> None:
    job = activity_import_jobs[job_id]
    # Let the endpoint flush its 202 response before extraction work begins.
    await asyncio.sleep(0)
    try:
        job.result = await extract_activity_document(content, filename, app_settings)
        job.status = "ready"
    except HTTPException as error:
        job.error = str(error.detail)
        job.status = "failed"
    except Exception:
        job.error = "Unable to extract activities from this document"
        job.status = "failed"


def start_activity_import_job(
    user_id: UUID, content: bytes, filename: str, app_settings: Settings
) -> UUID:
    trim_activity_import_jobs()
    job_id = uuid4()
    activity_import_jobs[job_id] = ActivityImportJob(
        user_id=user_id,
        created_at=monotonic(),
    )
    task = asyncio.create_task(run_activity_import_job(job_id, content, filename, app_settings))
    activity_import_tasks.add(task)
    task.add_done_callback(activity_import_tasks.discard)
    return job_id


async def read_activity_upload(
    file: UploadFile, app_settings: Settings
) -> tuple[str, bytes]:
    filename = (file.filename or "activity-notice.txt").strip()[:255]
    content = await file.read(app_settings.max_activity_import_bytes + 1)
    if len(content) > app_settings.max_activity_import_bytes:
        limit_mb = app_settings.max_activity_import_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Activity documents must be {limit_mb} MB or smaller",
        )
    return filename, content


@router.post("/activity-import")
async def extract_activity_import(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_auth),
    app_settings: Settings = Depends(settings),
) -> dict[str, object]:
    del auth
    filename, content = await read_activity_upload(file, app_settings)
    return await extract_activity_document(content, filename, app_settings)


@router.post("/activity-import/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_activity_import_job(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_auth),
    app_settings: Settings = Depends(settings),
) -> dict[str, str]:
    filename, content = await read_activity_upload(file, app_settings)
    job_id = start_activity_import_job(auth.user_id, content, filename, app_settings)
    return {"job_id": str(job_id), "status": "processing"}


@router.get("/activity-import/jobs/{job_id}")
async def get_activity_import_job(
    job_id: UUID,
    auth: AuthContext = Depends(require_auth),
) -> dict[str, object]:
    job = activity_import_jobs.get(job_id)
    if job is None or job.user_id != auth.user_id:
        raise not_found("Activity import job not found")
    if job.status == "ready" and job.result is not None:
        return {"status": "ready", **job.result}
    if job.status == "failed":
        return {"status": "failed", "detail": job.error or "Activity extraction failed"}
    return {"status": "processing"}


@router.post("/activity-import/confirm", status_code=status.HTTP_201_CREATED)
async def confirm_activity_import(
    payload: ImportConfirmation,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    activities = await db.create_activities(
        auth.user_id,
        [item.model_dump() for item in payload.activities],
        payload.source_filename,
    )
    return {"imported": len(activities), "activities": activities}


@router.get("/activities")
async def list_activities(
    search: str | None = Query(default=None, max_length=200),
    date: date | None = Query(default=None),
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    activities = await db.list_activities(
        auth.user_id,
        search=search,
        on_date=date,
    )
    return {"activities": activities}


@router.get("/activities/{activity_id}")
async def get_activity(
    activity_id: UUID,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    activity = await db.activity(auth.user_id, activity_id)
    if activity is None:
        raise not_found("Activity not found")
    return activity


@router.get("/members")
async def list_members(
    auth: AuthContext = Depends(require_auth), db: Database = Depends(database)
) -> dict[str, object]:
    return {"members": await db.list_members(auth.user_id)}


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: MemberInput,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, str]:
    return await db.create_member(auth.user_id, payload.name)


@router.get("/members/{member_id}/schedule")
async def get_member_schedule(
    member_id: UUID,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    if not await db.member_exists(auth.user_id, member_id):
        raise not_found("Member not found")
    return {"items": await db.member_schedule(auth.user_id, member_id)}


async def conflict_result(
    db: Database, user_id: UUID, member_id: UUID, activity_id: UUID
) -> dict[str, object]:
    new_sessions = await db.activity_sessions(user_id, activity_id)
    existing_sessions = await db.member_scheduled_sessions(user_id, member_id, exclude_activity_id=activity_id)
    result = check_conflicts(new_sessions, existing_sessions)
    if not new_sessions:
        result["has_time_uncertainty"] = True
        result["insufficient_time_sessions"] = [
            {"activity_name": "Selected activity", "reason": "The activity has no sessions"}
        ]
    return result


@router.post("/members/{member_id}/check-conflict")
async def check_member_conflict(
    member_id: UUID,
    payload: ScheduleRequest,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    if not await db.member_exists(auth.user_id, member_id):
        raise not_found("Member not found")
    if await db.activity(auth.user_id, payload.activity_id) is None:
        raise not_found("Activity not found")
    return await conflict_result(db, auth.user_id, member_id, payload.activity_id)


@router.post("/members/{member_id}/schedule")
async def add_member_schedule(
    member_id: UUID,
    payload: ScheduleRequest,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> dict[str, object]:
    if not await db.member_exists(auth.user_id, member_id):
        raise not_found("Member not found")
    if await db.activity(auth.user_id, payload.activity_id) is None:
        raise not_found("Activity not found")
    result = await conflict_result(db, auth.user_id, member_id, payload.activity_id)
    if (result["has_conflict"] or result["has_time_uncertainty"]) and not payload.override_conflicts:
        return {"status": "needs_confirmation", **result}
    await db.add_member_schedule_item(auth.user_id, member_id, payload.activity_id)
    return {"status": "added", **result}


@router.delete("/members/{member_id}/schedule/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member_schedule(
    member_id: UUID,
    activity_id: UUID,
    auth: AuthContext = Depends(require_auth),
    db: Database = Depends(database),
) -> None:
    if not await db.remove_member_schedule_item(auth.user_id, member_id, activity_id):
        raise not_found("Scheduled activity not found")
