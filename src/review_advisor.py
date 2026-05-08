"""Advisor-pattern self-repairing review.

Per docs/superpowers/specs/2026-05-08-advisor-pattern-self-repairing-review-design.md.
All model invocations go through Claude Code subagent dispatch — no direct
Anthropic SDK calls in this module.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
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


def _env_truthy(value: str | None) -> bool | None:
    """Tri-state: True/False if value is set and parses; None if unset."""
    if value is None:
        return None
    return value.strip().lower() not in {"false", "0", "no", "off", ""}


def _role_env_segment(role: str) -> str:
    """Compact role name for env vars: pre_flight -> PREFLIGHT, midflight -> MIDFLIGHT."""
    return role.replace("_", "").upper()


def is_advisor_enabled(surface: str, role: str) -> bool:
    """AND across master, per-role, per-surface kill-switches.

    Defaults to True when env unset.
    """
    if _env_truthy(os.environ.get("HYDRAFLOW_REVIEW_ADVISOR_ENABLED")) is False:
        return False
    role_env = f"HYDRAFLOW_REVIEW_{_role_env_segment(role)}_ENABLED"
    if _env_truthy(os.environ.get(role_env)) is False:
        return False
    surface_env = f"HYDRAFLOW_{surface.upper()}_ADVISOR_ENABLED"
    return _env_truthy(os.environ.get(surface_env)) is not False


def resolve_model(surface: str, role: str, default: str) -> str:
    """Per-surface > global > default."""
    role_seg = _role_env_segment(role)
    per_surface = os.environ.get(f"HYDRAFLOW_{surface.upper()}_{role_seg}_MODEL")
    if per_surface:
        return per_surface
    global_val = os.environ.get(f"HYDRAFLOW_REVIEW_{role_seg}_MODEL")
    if global_val:
        return global_val
    return default


class PreFlightTrigger:
    """Strategy for whether to run pre-flight on a given review."""

    def should_run(
        self, diff_stats: object, pr: object
    ) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class AlwaysTrigger(PreFlightTrigger):
    def should_run(self, diff_stats: object, pr: object) -> bool:
        return True


@dataclass(frozen=True)
class SurfaceAdvisorConfig:
    surface: str
    pre_flight_enabled: bool
    pre_flight_trigger: PreFlightTrigger | None
    mid_flight_enabled: bool
    post_verify_enabled: bool
    post_verify_authority: Literal["advisory", "veto"]
    executor_model: str
    advisor_model: str
    max_veto_retries: int


@dataclass(frozen=True)
class DiffStats:
    changed_paths: list[str]
    lines_changed: int


@dataclass(frozen=True)
class PRContext:
    prior_fix_attempts: int = 0


CRITICAL_PATHS_EXACT: frozenset[str] = frozenset(
    {
        "src/orchestrator.py",
        "src/service_registry.py",
        "src/coordinator.py",
        "src/review_phase.py",
        "src/review_advisor.py",
    }
)

CRITICAL_PATH_GLOBS: tuple[str, ...] = (
    "src/persistence/*",
    "src/state/*",
    "src/*_loop.py",
)


def _matches_critical(path: str) -> bool:
    if path in CRITICAL_PATHS_EXACT:
        return True
    return any(fnmatch.fnmatch(path, glob) for glob in CRITICAL_PATH_GLOBS)


# Re-exported for tests / external membership checks.
CRITICAL_PATHS = CRITICAL_PATHS_EXACT


def should_pre_flight(diff_stats: DiffStats, pr: PRContext) -> bool:
    """Composite predicate for whether to run pre-flight on a PR review."""
    if _env_truthy(os.environ.get("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON")):
        return True
    if pr.prior_fix_attempts >= 1:
        return True
    if any(_matches_critical(p) for p in diff_stats.changed_paths):
        return True
    nontrivial_src = [p for p in diff_stats.changed_paths if p.startswith("src/")]
    return bool(nontrivial_src and diff_stats.lines_changed > 20)


class CompositeTrigger(PreFlightTrigger):
    def should_run(self, diff_stats: DiffStats, pr: PRContext) -> bool:  # type: ignore[override]
        return should_pre_flight(diff_stats, pr)


_SURFACE_DEFAULTS: dict[str, dict[str, object]] = {
    "pr_review": {
        "pre_flight_enabled": True,
        "pre_flight_trigger": CompositeTrigger(),
        "mid_flight_enabled": True,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
        "max_veto_retries": 2,
    },
    "pre_merge_spec_check": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": True,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
        "max_veto_retries": 2,
    },
    "adr_review": {
        "pre_flight_enabled": True,
        "pre_flight_trigger": AlwaysTrigger(),
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
        "max_veto_retries": 2,
    },
    "visual_gate": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "veto",
        "max_veto_retries": 1,
    },
    "wiki_ingest": {
        "pre_flight_enabled": False,
        "pre_flight_trigger": None,
        "mid_flight_enabled": False,
        "post_verify_enabled": True,
        "post_verify_authority": "advisory",
        "max_veto_retries": 0,
    },
}


def build_surface_config(surface: str) -> SurfaceAdvisorConfig:
    """Build the config for a surface, resolving models against env each call.

    Called once per review to capture env state at start.
    """
    base = _SURFACE_DEFAULTS[surface]
    pre_flight_enabled = base["pre_flight_enabled"]
    pre_flight_trigger = base["pre_flight_trigger"]
    mid_flight_enabled = base["mid_flight_enabled"]
    post_verify_enabled = base["post_verify_enabled"]
    post_verify_authority = base["post_verify_authority"]
    max_veto_retries = base["max_veto_retries"]
    assert isinstance(pre_flight_enabled, bool)
    assert pre_flight_trigger is None or isinstance(
        pre_flight_trigger, PreFlightTrigger
    )
    assert isinstance(mid_flight_enabled, bool)
    assert isinstance(post_verify_enabled, bool)
    assert post_verify_authority in ("advisory", "veto")
    assert isinstance(max_veto_retries, int)
    return SurfaceAdvisorConfig(
        surface=surface,
        pre_flight_enabled=pre_flight_enabled,
        pre_flight_trigger=pre_flight_trigger,
        mid_flight_enabled=mid_flight_enabled,
        post_verify_enabled=post_verify_enabled,
        post_verify_authority=post_verify_authority,
        executor_model=resolve_model(surface, "executor", default="sonnet"),
        advisor_model=resolve_model(surface, "advisor", default="opus"),
        max_veto_retries=max_veto_retries,
    )


# Snapshot — production code paths should call build_surface_config(surface)
# so env overrides are picked up at runtime. Tests / static inspection use this.
SURFACE_ADVISOR_CONFIGS: dict[str, SurfaceAdvisorConfig] = {
    surface: build_surface_config(surface) for surface in _SURFACE_DEFAULTS
}
