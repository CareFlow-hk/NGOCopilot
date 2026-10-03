"""Tool-owned input contracts; Scheduler validates the full activity domain."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ngopilot_mcp.shared.public_schema import operation_schema


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartInput(Input):
    pdf_path: str = Field(
        min_length=1, description="Exact uploaded activity brochure PDF path"
    )
    year: int = Field(
        ge=2020,
        le=2100,
        description="Activity year supplied by user or unambiguous source",
    )
    pages: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="One-based pages; omitted means all pages",
    )


class ActivityReview(Input):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: int = Field(ge=1)
    data: dict[str, Any]
    status: Literal["confirmed", "excluded"] = "confirmed"
    note: str = Field(default="", max_length=2000)


class ReviewInput(Input):
    reviews: list[ActivityReview] = Field(min_length=1, max_length=500)
    reviewer: str = Field(min_length=1, max_length=120)


INPUTS = {"start": StartInput, "status": Input, "review": ReviewInput, "export": Input}


def public_input_schema():
    return operation_schema(INPUTS)
