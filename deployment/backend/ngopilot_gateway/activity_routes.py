"""Authenticated Activities API, isolated from the agent Automation scheduler."""

from __future__ import annotations

import base64
from datetime import date, time
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator

from .activity_scheduler import (
    ExtractedActivity,
    check_conflicts,
    extract_activities,
    is_image_document,
    source_text,
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


@router.post("/activity-import")
async def extract_activity_import(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_auth),
    app_settings: Settings = Depends(settings),
) -> dict[str, object]:
    del auth
    filename = (file.filename or "activity-notice.txt").strip()[:255]
    content = await file.read(app_settings.max_upload_bytes + 1)
    if len(content) > app_settings.max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")
    try:
        text = (
            await extract_image_text(filename, content, app_settings)
            if is_image_document(filename)
            else source_text(filename, content)
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    activities = extract_activities(text, filename)
    return {"source_filename": filename, "activities": [activity_as_dict(item) for item in activities]}


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
