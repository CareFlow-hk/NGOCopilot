"""Strict public request schemas for the paper-forms MCP tool."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

FIELD_KEYS = (
    "elder_name",
    "elder_age",
    "elder_gender",
    "elder_phone",
    "elder_address",
    "living_alone",
    "visit_date",
    "volunteer_name",
    "duration_minutes",
    "mood",
    "health_concerns",
    "follow_up_needed",
    "follow_up_note",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class StartInput(StrictModel):
    title: StrictStr | None = Field(
        default=None,
        description="Optional batch label. The tool generates one when omitted.",
    )
    image_paths: Annotated[
        list[StrictStr],
        Field(
            min_length=1,
            description=(
                "Absolute paths from Attachments to completed JPG, JPEG, or PNG "
                "CareFlow volunteer-visit forms."
            ),
        ),
    ]
    volunteer_team: StrictStr | None = Field(
        default=None, description="Optional volunteer team name."
    )
    visit_date: StrictStr | None = Field(
        default=None, description="Optional visit date in YYYY-MM-DD format."
    )
    note: StrictStr | None = Field(default=None, description="Optional batch note.")
    auto_complete: StrictBool = Field(
        default=False,
        description="Leave false unless the user explicitly requests native auto-completion.",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_blank(value, "title")

    @field_validator("image_paths")
    @classmethod
    def validate_image_path_strings(cls, values: list[str]) -> list[str]:
        for value in values:
            _non_blank(value, "image path")
        return values

    @field_validator("visit_date")
    @classmethod
    def validate_visit_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "visit_date must be an ISO date in YYYY-MM-DD form"
            ) from exc
        if parsed.isoformat() != value:
            raise ValueError("visit_date must be an ISO date in YYYY-MM-DD form")
        return value


class EmptyInput(StrictModel):
    pass


class FinalFields(StrictModel):
    # CareFlow accepts JSON values here and owns field-level domain handling.
    # Requiring every key preserves its complete-review correction behavior.
    elder_name: Any
    elder_age: Any
    elder_gender: Any
    elder_phone: Any
    elder_address: Any
    living_alone: Any
    visit_date: Any
    volunteer_name: Any
    duration_minutes: Any
    mood: Any
    health_concerns: Any
    follow_up_needed: Any
    follow_up_note: Any


class RecordReview(StrictModel):
    record_id: Annotated[
        StrictInt,
        Field(gt=0, description="Record id returned by this job."),
    ]
    final_fields: FinalFields = Field(
        description=(
            "The complete 13-field final_fields object returned by the tool, with "
            "any user corrections applied."
        )
    )
    reviewer: StrictStr | None = Field(
        default=None, description="Optional reviewer name."
    )


class ReviewInput(StrictModel):
    confirm_all: StrictBool = Field(
        default=False,
        description=(
            "Set true only after the user confirms every returned final_fields "
            "object unchanged. The tool copies those values for review."
        ),
    )
    reviews: (
        Annotated[
            list[RecordReview],
            Field(
                min_length=1,
                description=(
                    "Use when corrections are needed: one complete review object "
                    "per record being confirmed."
                ),
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_review_mode(self) -> ReviewInput:
        if self.confirm_all == (self.reviews is not None):
            raise ValueError(
                "choose exactly one review mode: confirm_all=true or reviews"
            )
        return self

    @field_validator("reviews")
    @classmethod
    def validate_unique_records(
        cls, values: list[RecordReview] | None
    ) -> list[RecordReview] | None:
        if values is None:
            return None
        record_ids = [item.record_id for item in values]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("each record_id may appear only once per review operation")
        return values


class StartCall(StrictModel):
    operation: Literal["start"] = Field(
        description="Start extraction from the attachment image paths."
    )
    job_id: None = None
    request_id: StrictStr | None = None
    input: StartInput


class StatusCall(StrictModel):
    operation: Literal["status"] = Field(
        description="Refresh a running job or retrieve its extracted data."
    )
    job_id: StrictStr = Field(description="The job_id returned by start.")
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class ReviewCall(StrictModel):
    operation: Literal["review"] = Field(
        description="Confirm extracted records after explicit human review."
    )
    job_id: StrictStr = Field(description="The job_id returned by start.")
    request_id: StrictStr | None = None
    input: ReviewInput


class ExportCall(StrictModel):
    operation: Literal["export"] = Field(
        description="Create the Excel artifact from explicitly reviewed records."
    )
    job_id: StrictStr = Field(description="The job_id returned by start.")
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


ToolRequest: TypeAlias = Annotated[
    StartCall | StatusCall | ReviewCall | ExportCall,
    Field(discriminator="operation"),
]

REQUEST_ADAPTER = TypeAdapter(ToolRequest)


def public_input_schema() -> dict[str, Any]:
    """Return a provider-friendly schema while strict validation stays authoritative."""

    start_schema = StartInput.model_json_schema()
    input_properties = deepcopy(start_schema["properties"])
    review_schema = ReviewInput.model_json_schema()
    input_properties.update(deepcopy(review_schema["properties"]))
    return {
        "type": "object",
        "$defs": review_schema.get("$defs", {}),
        "additionalProperties": False,
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["start", "status", "review", "export"],
                "description": (
                    "start requires input.image_paths and no job_id; status requires "
                    "the returned job_id; review requires explicit user confirmation; "
                    "export requires reviewed rows and appears in next_operations."
                ),
            },
            "job_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": (
                    "Omit for start. For status, review and export, copy the exact "
                    "job_id returned by start."
                ),
            },
            "request_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Optional idempotency key for safe retries.",
            },
            "input": {
                "type": "object",
                "additionalProperties": False,
                "description": (
                    "For start, send image_paths plus optional metadata. Omit for "
                    "status and export. For review, send confirm_all=true only after human "
                    "confirmation, or reviews with complete corrected final_fields."
                ),
                "properties": input_properties,
            },
        },
        "required": ["operation"],
    }


def validate_request(data: dict[str, Any]) -> ToolRequest:
    """Validate a JSON-compatible MCP call as an operation-specific request."""

    return REQUEST_ADAPTER.validate_python(data, strict=True)
