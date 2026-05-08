"""Advisor-pattern self-repairing review.

Per docs/superpowers/specs/2026-05-08-advisor-pattern-self-repairing-review-design.md.
All model invocations go through Claude Code subagent dispatch — no direct
Anthropic SDK calls in this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FocusArea(BaseModel):
    description: str
    files: list[str]
    rationale: str


class ReviewPlan(BaseModel):
    risk_summary: str
    focus_areas: list[FocusArea] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)
    escalation_signals: list[str] = Field(default_factory=list)


class PreFlightInput(BaseModel):
    surface: str
    diff: str
    spec: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    prior_attempts: int = 0


class Disagreement(BaseModel):
    executor_claim: str
    advisor_assessment: str
    severity: Literal["blocking", "concern"]


class PostVerifyResult(BaseModel):
    verdict: Literal["APPROVE", "VETO"]
    reasoning: str
    disagreements: list[Disagreement] = Field(default_factory=list)
    suggested_fix_direction: str | None = None


class PostVerifyInput(BaseModel):
    surface: str
    diff: str
    spec: str | None = None
    executor_verdict_summary: str
    executor_fix_diff: str | None = None
    pre_flight_plan: ReviewPlan | None = None
    attempt_number: int = 0
