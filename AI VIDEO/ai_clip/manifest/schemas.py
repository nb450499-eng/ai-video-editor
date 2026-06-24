from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Grade = Literal["A", "B", "C", "D"]

SHOT_ID_RE = re.compile(r"^\d{2}$")
TAKE_NAME_RE = re.compile(r"^take_\d{3}$")
ASSET_ID_RE = re.compile(r"^(?P<shot_id>\d{2})/(?P<take_name>take_\d{3})$")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Timing(StrictBaseModel):
    pre_roll_ms: int = Field(ge=0)
    post_roll_ms: int = Field(ge=0)
    min_result_hold_ms: int = Field(ge=0)
    max_speed_change: float = Field(default=1.08, ge=1.0)


class SyncPoint(StrictBaseModel):
    voice_text: str = Field(min_length=1)
    visual_event: str = Field(min_length=1)


class ShotSpec(StrictBaseModel):
    shot_id: str
    folder: str = Field(min_length=1)
    target_duration_ms: int = Field(gt=0)
    voice_text: str = Field(default="")
    role: str = Field(min_length=1)
    required_states: list[str] = Field(default_factory=list)
    required_events: list[str] = Field(min_length=1)
    forbidden: list[str] = Field(default_factory=list)
    timing: Timing
    sync_points: list[SyncPoint] = Field(default_factory=list)
    product_refs: list[str] = Field(default_factory=list)

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, value: str) -> str:
        if not SHOT_ID_RE.match(value):
            raise ValueError("shot_id must be a two digit string, for example '03'")
        return value

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, value: str) -> str:
        if PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
            raise ValueError("folder must be a relative project path")
        return value

    @field_validator("required_states", "required_events", "forbidden", "product_refs")
    @classmethod
    def strip_non_empty_items(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("list items must be unique")
        return cleaned


class ProjectManifest(StrictBaseModel):
    project_id: str = Field(min_length=1)
    product: str = Field(min_length=1)
    shots_root: str = "shots"
    truth_root: str = "truth"
    shot_ids: list[str] = Field(min_length=1)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        if not re.match(r"^[A-Za-z0-9_.-]+$", value):
            raise ValueError("project_id may contain only letters, numbers, dots, dashes, and underscores")
        return value

    @field_validator("shot_ids")
    @classmethod
    def validate_shot_ids(cls, values: list[str]) -> list[str]:
        if any(not SHOT_ID_RE.match(value) for value in values):
            raise ValueError("each shot id must be a two digit string")
        if len(values) != len(set(values)):
            raise ValueError("shot_ids must be unique")
        return values


class TruthEvents(StrictBaseModel):
    action_start_ms: int = Field(ge=0)
    result_first_visible_ms: int = Field(ge=0)
    result_hold_end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_event_order(self) -> TruthEvents:
        if self.action_start_ms >= self.result_first_visible_ms:
            raise ValueError("action_start_ms must be before result_first_visible_ms")
        if self.result_first_visible_ms > self.result_hold_end_ms:
            raise ValueError("result_first_visible_ms must be <= result_hold_end_ms")
        return self


class TruthWindow(StrictBaseModel):
    window_id: str = Field(min_length=1)
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    events: TruthEvents
    grade: Grade
    notes: str = ""

    @model_validator(mode="after")
    def validate_window_order(self) -> TruthWindow:
        if self.source_in_ms >= self.source_out_ms:
            raise ValueError("source_in_ms must be before source_out_ms")
        if not (self.source_in_ms < self.events.action_start_ms):
            raise ValueError("source_in_ms must be before action_start_ms")
        if self.events.result_hold_end_ms > self.source_out_ms:
            raise ValueError("result_hold_end_ms must be <= source_out_ms")
        return self


class TruthFile(StrictBaseModel):
    asset_id: str
    shot_id: str
    duration_ms: int = Field(gt=0)
    usable: bool
    windows: list[TruthWindow] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    annotator: str = Field(min_length=1)
    annotated_at: datetime

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not ASSET_ID_RE.match(value):
            raise ValueError("asset_id must look like '03/take_002'")
        return value

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, value: str) -> str:
        if not SHOT_ID_RE.match(value):
            raise ValueError("shot_id must be a two digit string")
        return value

    @field_validator("reject_reasons")
    @classmethod
    def validate_reject_reasons(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("reject_reasons must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_truth_consistency(self) -> TruthFile:
        match = ASSET_ID_RE.match(self.asset_id)
        assert match is not None
        if self.shot_id != match.group("shot_id"):
            raise ValueError("shot_id must match asset_id")

        window_ids = [window.window_id for window in self.windows]
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("window_id must be unique within a take")

        if self.usable and not self.windows:
            raise ValueError("usable truth files must contain at least one window")
        if not self.usable and self.windows:
            raise ValueError("unusable truth files must not contain windows")
        if not self.usable and not self.reject_reasons:
            raise ValueError("unusable truth files must include reject_reasons")

        for window in self.windows:
            if window.source_out_ms > self.duration_ms:
                raise ValueError("window source_out_ms exceeds duration_ms")
        return self


class TimelineEvents(StrictBaseModel):
    action_start_ms: int | None = Field(default=None, ge=0)
    result_first_visible_ms: int | None = Field(default=None, ge=0)
    result_hold_end_ms: int | None = Field(default=None, ge=0)


class TimelineItem(StrictBaseModel):
    shot_id: str
    asset: str
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    timeline_in_ms: int = Field(ge=0)
    timeline_out_ms: int = Field(gt=0)
    speed: float = Field(default=1.0, gt=0)
    grade: Grade
    events: TimelineEvents = Field(default_factory=TimelineEvents)

    @model_validator(mode="after")
    def validate_timeline_order(self) -> TimelineItem:
        if self.source_in_ms >= self.source_out_ms:
            raise ValueError("source_in_ms must be before source_out_ms")
        if self.timeline_in_ms >= self.timeline_out_ms:
            raise ValueError("timeline_in_ms must be before timeline_out_ms")
        return self


class CandidateWindow(StrictBaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    proposal_score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_candidate_order(self) -> CandidateWindow:
        if self.start_ms >= self.end_ms:
            raise ValueError("start_ms must be before end_ms")
        return self


class TechnicalSignalsSummary(StrictBaseModel):
    blur_ratio: float = Field(ge=0.0, le=1.0)
    severe_shake_ratio: float = Field(ge=0.0, le=1.0)
    exposure_ok_ratio: float = Field(ge=0.0, le=1.0)


class EventPoint(StrictBaseModel):
    name: str = Field(min_length=1)
    time_ms: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class TakeAnalysis(StrictBaseModel):
    asset_id: str
    duration_ms: int = Field(gt=0)
    technical: TechnicalSignalsSummary
    candidate_windows: list[CandidateWindow] = Field(default_factory=list)
    event_timeline: list[EventPoint] = Field(default_factory=list)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not ASSET_ID_RE.match(value):
            raise ValueError("asset_id must look like '03/take_002'")
        return value


class ValidWindow(StrictBaseModel):
    asset_id: str
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    grade: Grade
    score: float = Field(ge=0.0)
    event_coverage: float = Field(ge=0.0, le=1.0)
    verification_passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False
    reject_reason: str | None = None

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not ASSET_ID_RE.match(value):
            raise ValueError("asset_id must look like '03/take_002'")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> ValidWindow:
        if self.source_in_ms >= self.source_out_ms:
            raise ValueError("source_in_ms must be before source_out_ms")
        if self.rejected and not self.reject_reason:
            raise ValueError("rejected windows must include reject_reason")
        return self
