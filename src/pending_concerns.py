from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
Phase = Literal["discover", "shape", "plan", "implement", "post_merge"]
ResolutionKind = Literal[
    "trivial", "deferred", "addressed-in-code", "addressed-in-test", "ignored"
]


class Concern(BaseModel):
    id: str
    raised_in_phase: Phase
    raised_in_stage: str
    severity: Severity
    concern: str
    raised_at: datetime
    must_address_by: str
    human_required: bool = False


class ConcernResolution(BaseModel):
    concern_id: str
    addressed_in_stage: str
    resolution: str
    addressed_at: datetime
    resolution_kind: ResolutionKind


class StageRun(BaseModel):
    stage: str
    phase: Phase
    retries: int
    converged: bool
    concerns_raised: int
    concerns_forwarded: int
    oscillation_detected: bool
    duration_ms: int


class AdversarialState(BaseModel):
    phase: Phase
    current_stage: str | None = None
    pending_concerns: list[Concern] = Field(default_factory=list)
    addressed_concerns: list[ConcernResolution] = Field(default_factory=list)
    stage_history: list[StageRun] = Field(default_factory=list)
