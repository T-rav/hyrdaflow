"""Advisor-pattern self-repairing review.

Per docs/superpowers/specs/2026-05-08-advisor-pattern-self-repairing-review-design.md.
All model invocations go through Claude Code subagent dispatch — no direct
Anthropic SDK calls in this module.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from opentelemetry import metrics
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json_block(payload: str) -> str:
    """Extract the JSON object from an agent transcript.

    The Claude subagent's response can include prose, stream events, or
    fenced code blocks around the JSON we asked for. Production transcripts
    are not bare JSON — see src/spec_match.py for the same pattern.

    Order: fenced JSON > last/greediest ``{...}`` block > bare payload.
    """
    m = _JSON_FENCE_RE.search(payload)
    if m:
        return m.group(1)
    m = _JSON_BLOCK_RE.search(payload)
    if m:
        return m.group(1)
    return payload


# OTel metric instruments — module-level so the proxy meter delegates to
# whatever MeterProvider is registered at call time. When no provider is set
# (default in production prior to T14 dashboard wiring), `.add()` / `.record()`
# are silently no-op. Tests install an InMemoryMetricReader to read values.
# Per ADR-0055, OTel is HydraFlow's telemetry layer; this is the metrics
# counterpart to the existing tracing decorators in src/telemetry/spans.py.
_meter = metrics.get_meter("hydraflow.review_advisor")
_calls_total = _meter.create_counter(
    "review_advisor_calls_total",
    description="PostVerifyAdvisor invocations, labeled by surface/role/outcome.",
)
_call_duration_seconds = _meter.create_histogram(
    "review_advisor_call_duration_seconds",
    unit="s",
    description="PostVerifyAdvisor wall-clock duration per invocation.",
)
_post_verify_verdict_total = _meter.create_counter(
    "review_advisor_post_verify_verdict_total",
    description=(
        "PostVerifyAdvisor verdict count, labeled by surface and the "
        "post-advisory-downgrade verdict (approve/veto)."
    ),
)
_post_verify_degraded_total = _meter.create_counter(
    "review_advisor_post_verify_degraded_total",
    description=(
        "PostVerifyAdvisor degraded-path count (runner error or parse error), "
        "labeled by surface."
    ),
)
_disagreement_total = _meter.create_counter(
    "review_advisor_disagreement_total",
    description=(
        "Disagreements observed in advisor verdicts, partitioned by "
        "{surface, role, severity}. Feeds the disagreement-validated KPI "
        "(spec §6.1)."
    ),
)
_disagreement_validated_total = _meter.create_counter(
    "review_advisor_disagreement_validated_total",
    description=(
        "Disagreements where post-verify confirmed the advisor was right "
        "and the executor was wrong (originally warned in pre-flight "
        "or mid-flight)"
    ),
)


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
    # Optional — threaded into the prompt so MockWorld runners can route
    # advisor calls back to FakeLLM.pop_advisor_result(issue_number, role).
    # Production callers can leave this unset; the field only changes prompt
    # text when populated.
    issue_number: int | None = None


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
    # Optional — threaded into the prompt so MockWorld runners can route
    # advisor calls back to FakeLLM.pop_advisor_result(issue_number, role).
    # Production callers can leave this unset; the field only changes prompt
    # text when populated.
    issue_number: int | None = None


# Signals shorter than this are too generic to validate against — short
# words like "test gaps" false-positive against any disagreement that
# contains those words coincidentally (T24.5 closed I5).
_MIN_SIGNAL_MATCH_LEN = 10


def _validate_disagreements_against_plan(
    disagreements: list[Disagreement],
    plan: ReviewPlan | None,
) -> int:
    """Return how many post-verify disagreements were predicted by the
    pre-flight plan's escalation_signals.

    Forward-only substring match: signal must appear within the assessment.
    Signals shorter than ``_MIN_SIGNAL_MATCH_LEN`` chars are skipped — short
    generic signals (e.g. "test gaps") would false-positive against any
    assessment containing those words. The bidirectional pre-T24.5 match
    also caused symmetric false-positives where ``assessment_lc in sig``
    matched long signals against unrelated short assessments. Returns 0 if
    there is no plan or no qualifying signals.
    """
    if plan is None or not plan.escalation_signals:
        return 0
    qualifying_signals = [
        s.lower() for s in plan.escalation_signals if len(s) >= _MIN_SIGNAL_MATCH_LEN
    ]
    if not qualifying_signals:
        return 0
    matched = 0
    for d in disagreements:
        assessment_lc = d.advisor_assessment.lower()
        if any(sig in assessment_lc for sig in qualifying_signals):
            matched += 1
    return matched


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


# T29 — self-modification guard (spec §5.8). The advisor must never approve
# changes to its own implementation silently. When a diff touches these paths,
# resolve_post_verify_authority forces "veto" regardless of the surface's
# configured authority — even on advisory surfaces (e.g., wiki_ingest).
#
# Public contract (T30.5 I3): the wiki ingest descriptor synthesizer in
# ``review_phase`` imports this set to keep a single source of truth for
# advisor's own implementation paths. Different matchers (unified-diff
# headers vs. content-substring) consume the same paths.
SELF_MODIFYING_PATHS: frozenset[str] = frozenset(
    {
        "src/review_advisor.py",
        "src/review_phase.py",
    }
)


def _diff_touches_self_modifying_paths(diff: str) -> bool:
    """Detect whether a diff modifies advisor's own implementation files."""
    for path in SELF_MODIFYING_PATHS:
        if (
            f"diff --git a/{path}" in diff
            or f"diff --git b/{path}" in diff
            or f"+++ b/{path}" in diff
            or f"--- a/{path}" in diff
        ):
            return True
    return False


def resolve_post_verify_authority(
    *,
    surface_config: SurfaceAdvisorConfig,
    diff: str,
) -> Literal["advisory", "veto"]:
    """Resolve post-verify authority, applying spec §5.8 self-modification guard.

    When the diff modifies advisor's own implementation files (review_advisor.py
    or review_phase.py), force veto authority — the advisor must not approve
    changes to itself with anything less than its strongest mode, even on
    surfaces (wiki_ingest) that default to advisory.
    """
    if _diff_touches_self_modifying_paths(diff):
        return "veto"
    return surface_config.post_verify_authority


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


def diff_stats_from_text(diff: str) -> DiffStats:
    """Compute a coarse :class:`DiffStats` from a raw unified-diff string.

    Used by ``ReviewPhase`` to feed the composite ``should_pre_flight`` predicate
    when no structured stats source is available. Counts ``+``/``-`` body lines
    and extracts post-image paths from ``+++ b/...`` headers. Tolerant of empty
    or malformed input — returns an empty :class:`DiffStats` rather than
    raising.
    """
    paths: list[str] = []
    lines_changed = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[len("+++ b/") :].strip())
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            or line.startswith("-")
            and not line.startswith("---")
        ):
            lines_changed += 1
    return DiffStats(changed_paths=paths, lines_changed=lines_changed)


def format_pre_flight_for_prompt(plan: ReviewPlan | None) -> str:
    """Render a :class:`ReviewPlan` as a markdown section for the executor prompt.

    Returns an empty string when ``plan`` is ``None`` so callers can append
    unconditionally without branching. Production callers wire this into the
    reviewer's prompt so the executor's review uses the advisor's rubric.
    """
    if plan is None:
        return ""
    return (
        "\n\n## Pre-flight review plan (from advisor)\n\n"
        f"{plan.model_dump_json(indent=2)}\n\n"
        "Use this as your review rubric — focus on the listed focus_areas and "
        "rubric items. If you observe any of the escalation_signals, treat "
        "them as blocking unless you can show with evidence that they don't "
        "apply."
    )


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


class _AdvisorSubagentRunner(Protocol):
    """Minimal protocol the runner adapter must satisfy.

    Production wiring is provided by ReviewPhase via agent_cli (T9).

    The ``role`` parameter is required so MockWorld can route advisor calls
    to the correct scripted queue. Substring-based role detection on the
    prompt is a footgun — PR bodies discussing the advisor pattern itself
    contain marker substrings (T24.5 closed I1+I2).
    """

    async def run(
        self,
        *,
        model: str,
        subagent_type: str,
        prompt: str,
        role: Literal["pre_flight", "mid_flight", "post_verify"],
    ) -> str: ...  # pragma: no cover - protocol


class PostVerifyAdvisor:
    """Always-on second-opinion gate. Runs as a separate Claude Code subagent.

    Authority is determined by the SurfaceAdvisorConfig:
    - "veto" — verdict is final (caller honors APPROVE/VETO)
    - "advisory" — VETO is downgraded to APPROVE before return; reasoning
      and disagreements are preserved for telemetry / logging
    """

    def __init__(
        self,
        runner: _AdvisorSubagentRunner,
        surface_config: SurfaceAdvisorConfig,
        *,
        log_path: Path | None = None,
        pr_number: int | None = None,
        authority_override: Literal["advisory", "veto"] | None = None,
    ) -> None:
        self._runner = runner
        self._cfg = surface_config
        self._log_path = log_path
        # Threaded through to the jsonl session log so each entry carries
        # the PR number per spec §"Logging". Production callers wire this
        # from review_phase.py; tests may leave it unset.
        self._pr_number = pr_number
        # T29 self-modification guard: when the caller has computed an
        # authority override (e.g. via resolve_post_verify_authority because
        # the diff touches advisor's own files), use that instead of the
        # surface config's configured authority. None means "fall through
        # to surface_config.post_verify_authority".
        self._authority_override = authority_override

    async def run(self, inp: PostVerifyInput) -> PostVerifyResult:
        prompt = self._build_prompt(inp)
        start = time.monotonic()
        try:
            payload = await self._runner.run(
                model=self._cfg.advisor_model,
                subagent_type="hydraflow-review-advisor",
                prompt=prompt,
                role="post_verify",
            )
        except Exception as exc:
            # Authentication, credit, and likely-bug errors must propagate
            # per docs/wiki/dark-factory.md §2.2 — they signal infrastructure
            # state (or programming bugs) the orchestrator's higher layers
            # need to see, not transient advisor-runner failures.
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            try:
                reraise_on_credit_or_bug(exc)
            except BaseException:
                self._emit_log(
                    prompt=prompt, payload=None, start=start, error="runner-error"
                )
                self._emit_metrics(start=start, outcome="error", verdict=None)
                raise
            result = self._handle_failure(reason=f"runner-error: {exc!r}")
            self._emit_log(
                prompt=prompt, payload=None, start=start, error="runner-error"
            )
            self._emit_metrics(
                start=start, outcome="error", verdict=result.verdict.lower()
            )
            return result

        try:
            data = json.loads(_extract_json_block(payload))
            result = PostVerifyResult.model_validate(data)
        except Exception as exc:
            result = self._handle_failure(reason=f"parse-error: {exc!r}")
            self._emit_log(
                prompt=prompt, payload=payload, start=start, error="parse-error"
            )
            self._emit_metrics(
                start=start, outcome="parse_error", verdict=result.verdict.lower()
            )
            return result

        # Advisory authority: downgrade VETO to APPROVE; preserve diagnostic info.
        # T29: an explicit authority_override (computed by callers when the
        # diff modifies advisor's own files) takes precedence over the
        # surface config's configured authority.
        authority = self._authority_override or self._cfg.post_verify_authority
        if authority == "advisory" and result.verdict == "VETO":
            result = PostVerifyResult(
                verdict="APPROVE",
                reasoning=result.reasoning,
                disagreements=result.disagreements,
                suggested_fix_direction=result.suggested_fix_direction,
            )
        # Emit per-disagreement telemetry (spec §6.1 — feeds the
        # disagreement-validated KPI). Telemetry never breaks business logic.
        for d in result.disagreements:
            try:
                _disagreement_total.add(
                    1,
                    {
                        "surface": self._cfg.surface,
                        "role": "post_verify",
                        "severity": d.severity,
                    },
                )
            except Exception:  # noqa: BLE001 — telemetry never breaks business logic
                logger.debug("advisor disagreement-counter emit failed", exc_info=True)
        # T22: emit disagreement_validated_total when pre-flight predicted the issue
        matched = _validate_disagreements_against_plan(
            result.disagreements, inp.pre_flight_plan
        )
        if matched > 0:
            try:
                _disagreement_validated_total.add(
                    matched,
                    {"surface": self._cfg.surface, "role": "pre_flight"},
                )
            except Exception:  # noqa: BLE001 — telemetry never breaks business logic
                logger.debug(
                    "advisor disagreement-validated-counter emit failed",
                    exc_info=True,
                )
        self._emit_log(prompt=prompt, payload=payload, start=start, error=None)
        self._emit_metrics(
            start=start, outcome="success", verdict=result.verdict.lower()
        )
        return result

    def _emit_log(
        self,
        *,
        prompt: str,
        payload: str | None,
        start: float,
        error: str | None,
    ) -> None:
        """Best-effort per-PR jsonl session log. Never raises."""
        if self._log_path is None:
            return
        duration_ms = int((time.monotonic() - start) * 1000)
        # Token counts are placeholders: the runner adapter does not yet
        # surface them. Emitting `None` documents the field shape (per spec
        # §"Logging") so downstream consumers can light up token-aware
        # dashboards without a schema migration when the runner exposes
        # token usage.
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "pr_number": self._pr_number,
            "surface": self._cfg.surface,
            "role": "post_verify",
            "model": self._cfg.advisor_model,
            "duration_ms": duration_ms,
            "input_summary_chars": len(prompt),
            "output_summary_chars": len(payload or ""),
            "tokens_in": None,
            "tokens_out": None,
            "error": error,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            # best-effort logging; never block the pipeline
            logger.debug("advisor session log write failed", exc_info=True)

    def _emit_metrics(
        self,
        *,
        start: float,
        outcome: Literal["success", "error", "parse_error"],
        verdict: str | None,
    ) -> None:
        """Best-effort OTel metrics emission. Never raises.

        - ``calls_total`` and ``call_duration_seconds`` always emit (one
          datapoint per call).
        - ``post_verify_verdict_total`` emits when a verdict was resolved
          (i.e. not the auth/credit reraise path).
        """
        try:
            attrs_call = {
                "surface": self._cfg.surface,
                "role": "post_verify",
                "outcome": outcome,
            }
            _calls_total.add(1, attrs_call)
            _call_duration_seconds.record(
                time.monotonic() - start,
                {"surface": self._cfg.surface, "role": "post_verify"},
            )
            if verdict is not None:
                _post_verify_verdict_total.add(
                    1, {"surface": self._cfg.surface, "verdict": verdict}
                )
        except Exception:
            # Telemetry must never alter business control flow (ADR-0055).
            logger.debug("advisor metrics emit failed", exc_info=True)

    def _handle_failure(self, *, reason: str) -> PostVerifyResult:
        fail_as_veto = _env_truthy(
            os.environ.get("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO")
        )
        verdict: Literal["APPROVE", "VETO"] = "VETO" if fail_as_veto else "APPROVE"
        logger.warning(
            "post_verify advisor degraded surface=%s reason=%s -> %s",
            self._cfg.surface,
            reason,
            verdict,
        )
        try:
            _post_verify_degraded_total.add(1, {"surface": self._cfg.surface})
        except Exception:
            logger.debug("advisor degraded-counter emit failed", exc_info=True)
        return PostVerifyResult(
            verdict=verdict,
            reasoning=f"advisor-degraded: {reason}",
            disagreements=[],
        )

    def _build_prompt(self, inp: PostVerifyInput) -> str:
        sections = [
            f"Surface: {inp.surface}",
            f"Attempt #: {inp.attempt_number}",
        ]
        if inp.issue_number is not None:
            # Emitted so MockWorld's runner can extract the issue number from
            # the prompt and look up the scripted advisor response. Production
            # callers may leave issue_number unset.
            sections.append(f"Issue: {inp.issue_number}")
        sections.extend(
            [
                "",
                "## Diff",
                inp.diff[:8000],
                "",
                f"## Executor verdict summary\n{inp.executor_verdict_summary}",
            ]
        )
        if inp.executor_fix_diff:
            sections.append(f"\n## Executor fix\n{inp.executor_fix_diff[:4000]}")
        if inp.pre_flight_plan is not None:
            sections.append(
                f"\n## Pre-flight plan\n{inp.pre_flight_plan.model_dump_json(indent=2)}"
            )
        sections.append(
            "\nRespond with JSON matching the PostVerifyResult schema:\n"
            '{"verdict":"APPROVE"|"VETO","reasoning":str,'
            '"disagreements":[{"executor_claim":str,"advisor_assessment":str,'
            '"severity":"blocking"|"concern"}],'
            '"suggested_fix_direction":str|null}'
        )
        return "\n".join(sections)


class PreFlightAdvisor:
    """Conditional pre-review planner. Produces a ReviewPlan to scope the
    executor's review or returns None on degraded paths.

    Unlike PostVerifyAdvisor, pre-flight is always advisory — degraded paths
    return None ("no plan available; executor proceeds without one") rather
    than synthesizing an APPROVE/VETO verdict. There is no FAIL_AS_VETO
    counterpart for pre-flight.
    """

    def __init__(
        self,
        runner: _AdvisorSubagentRunner,
        surface_config: SurfaceAdvisorConfig,
        *,
        log_path: Path | None = None,
        pr_number: int | None = None,
    ) -> None:
        self._runner = runner
        self._cfg = surface_config
        self._log_path = log_path
        self._pr_number = pr_number

    async def run(self, inp: PreFlightInput) -> ReviewPlan | None:
        prompt = self._build_prompt(inp)
        start = time.monotonic()
        payload: str | None = None
        try:
            payload = await self._runner.run(
                model=self._cfg.advisor_model,
                subagent_type="hydraflow-review-advisor",
                prompt=prompt,
                role="pre_flight",
            )
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            self._emit_metrics(outcome="error")
            self._emit_log(
                prompt=prompt, payload=None, start=start, error="runner-error"
            )
            logger.warning(
                "pre_flight advisor degraded surface=%s reason=runner-error: %r",
                self._cfg.surface,
                exc,
            )
            return None

        try:
            data = json.loads(_extract_json_block(payload))
            plan = ReviewPlan.model_validate(data)
        except Exception as exc:
            self._emit_metrics(outcome="parse_error")
            self._emit_log(
                prompt=prompt, payload=payload, start=start, error="parse-error"
            )
            logger.warning(
                "pre_flight advisor degraded surface=%s reason=parse-error: %r",
                self._cfg.surface,
                exc,
            )
            return None

        self._emit_metrics(outcome="success")
        self._emit_log(prompt=prompt, payload=payload, start=start, error=None)
        return plan

    def _emit_metrics(self, *, outcome: str) -> None:
        try:
            _calls_total.add(
                1,
                {
                    "surface": self._cfg.surface,
                    "role": "pre_flight",
                    "outcome": outcome,
                },
            )
        except Exception:  # noqa: BLE001 — telemetry never breaks business logic
            logger.debug("pre_flight advisor metrics emit failed", exc_info=True)

    def _emit_log(
        self,
        *,
        prompt: str,
        payload: str | None,
        start: float,
        error: str | None,
    ) -> None:
        if self._log_path is None:
            return
        duration_ms = int((time.monotonic() - start) * 1000)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "pr_number": self._pr_number,
            "surface": self._cfg.surface,
            "role": "pre_flight",
            "model": self._cfg.advisor_model,
            "duration_ms": duration_ms,
            "input_summary_chars": len(prompt),
            "output_summary_chars": len(payload or ""),
            "tokens_in": None,
            "tokens_out": None,
            "error": error,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            logger.debug("pre_flight advisor session log write failed", exc_info=True)

    def _build_prompt(self, inp: PreFlightInput) -> str:
        sections = [
            f"Surface: {inp.surface}",
            f"Prior fix attempts: {inp.prior_attempts}",
        ]
        if inp.issue_number is not None:
            # Emitted so MockWorld's runner can extract the issue number from
            # the prompt and look up the scripted advisor response. Production
            # callers may leave issue_number unset.
            sections.append(f"Issue: {inp.issue_number}")
        sections.extend(
            [
                "",
                "## Diff",
                inp.diff[:8000],
            ]
        )
        if inp.spec is not None:
            sections.append(f"\n## Spec / issue body\n{inp.spec[:4000]}")
        if inp.related_paths:
            sections.append(
                "\n## Related paths\n" + "\n".join(f"- {p}" for p in inp.related_paths)
            )
        sections.append(
            "\nProduce a ReviewPlan as JSON matching this schema:\n"
            '{"risk_summary":str,'
            '"focus_areas":[{"description":str,"files":[str],"rationale":str}],'
            '"rubric":[str],'
            '"escalation_signals":[str]}'
            "\nFocus on: what could go wrong with this diff, what the reviewer "
            "should look for, and any signals that suggest mid-flight consult."
        )
        return "\n".join(sections)


class MidFlightAdvisor:
    """Build the Task-tool invocation the executor uses to consult the advisor.

    This class is a descriptor + template builder — it does NOT invoke the
    Task tool. The executor session itself calls Task(**invocation) with the
    dict returned by build_task_invocation. This keeps the Task dispatch
    inside the executor's session boundary (which the advisor pattern
    requires for "shared context" — the advisor sees the executor's
    summary, not the literal conversation history).

    T21 wires the TOOL_DESCRIPTION into the executor's review prompt and
    instructs the executor to call Task(...) with the build_task_invocation
    output when it needs a judgment call.
    """

    TOOL_DESCRIPTION = (
        "Consult an Opus advisor when uncertain about a review decision, "
        "fix strategy, or whether an issue is real. The advisor is dispatched "
        "via the Task tool with subagent_type='hydraflow-review-advisor'. "
        "The advisor does NOT see your full conversation history — include "
        "enough context in your question. Do NOT use this tool for things "
        "you can verify yourself (running tests, reading files, grepping "
        "code) — only judgment calls where the right answer requires more "
        "than mechanical verification."
    )

    def __init__(self, surface_config: SurfaceAdvisorConfig) -> None:
        self._cfg = surface_config

    def build_task_invocation(
        self,
        *,
        question: str,
        context_summary: str,
        options: list[str] | None = None,
    ) -> dict[str, str] | None:
        """Build the Task-tool invocation dict, or None if mid-flight is disabled.

        Returns a dict with keys ``model``, ``subagent_type``, ``prompt``,
        suitable for ``Task(**invocation)``. Returns None if the surface's
        ``mid_flight_enabled`` flag is False or the kill-switch chain
        disables mid-flight on this surface.
        """
        if not self._cfg.mid_flight_enabled:
            return None
        if not is_advisor_enabled(self._cfg.surface, "midflight"):
            return None
        prompt = self._render_prompt(question, context_summary, options or [])
        return {
            "model": self._cfg.advisor_model,
            "subagent_type": "hydraflow-review-advisor",
            "prompt": prompt,
        }

    # Sentinel marker prepended to every mid-flight consult prompt.
    # Mid-flight calls are dispatched from inside the executor's session via
    # the Task tool, which does NOT thread through ``_AdvisorSubagentRunner``
    # and therefore cannot pass an explicit ``role=`` parameter. The runner
    # adapter (``_PostVerifyRunner.run`` in src/review_phase.py) detects
    # this sentinel as the only signal that a prompt is a mid-flight
    # consult. Format: HTML comment so it never renders in any markdown
    # view, versioned so future format changes can be detected, and
    # specific enough that PR bodies discussing the advisor pattern won't
    # naturally contain it (T24.5 closed I1+I2).
    SENTINEL = "<!-- HYDRAFLOW_MIDFLIGHT_CONSULT_PROMPT_v1 -->"

    @staticmethod
    def _render_prompt(question: str, context: str, options: list[str]) -> str:
        sections = [
            MidFlightAdvisor.SENTINEL,
            "## Mid-flight consult",
            f"### Question\n{question}",
            f"\n### Context (summary from executor)\n{context}",
        ]
        if options:
            sections.append(
                "\n### Options under consideration\n"
                + "\n".join(f"- {o}" for o in options)
            )
        sections.append(
            '\nRespond with JSON: {"reasoning":str,"recommendation":str,'
            '"confidence":float}'
        )
        return "\n".join(sections)


def _max_midflight_consults() -> int:
    """Per-review cap on consult_advisor invocations.

    Read at call time (not import time) so monkeypatch in tests works.
    Falls back to the default (5) on any parse failure.
    """
    raw = os.environ.get("HYDRAFLOW_REVIEW_MIDFLIGHT_MAX_CONSULTS", "5")
    try:
        return int(raw)
    except ValueError:
        return 5


def format_mid_flight_for_prompt(
    surface_config: SurfaceAdvisorConfig,
) -> str | None:
    """Build the executor-prompt section that documents the consult_advisor
    Task tool. Returns None when mid-flight is disabled for the surface.

    The executor uses this to know when and how to call the Task tool with
    ``subagent_type="hydraflow-review-advisor"`` mid-review. This is purely
    instruction text — the actual Task dispatch happens inside the executor's
    session. Returning None keeps callers' prompt-builder branch-free: they
    inject ``section or ""``.
    """
    advisor = MidFlightAdvisor(surface_config=surface_config)
    # Probe — pass placeholder args; we only care whether the gate is open.
    if advisor.build_task_invocation(question="probe", context_summary="probe") is None:
        return None
    cap = _max_midflight_consults()
    return (
        "\n## Mid-flight advisor (Opus consult tool)\n\n"
        f"{MidFlightAdvisor.TOOL_DESCRIPTION}\n\n"
        "Invoke via:\n"
        "  Task(\n"
        '    subagent_type="hydraflow-review-advisor",\n'
        '    model="opus",\n'
        "    prompt=<see template below>\n"
        "  )\n\n"
        "Prompt template (the FIRST line MUST be the sentinel exactly as shown\n"
        "— it is how the runner adapter detects this is a mid-flight consult\n"
        "and routes it to the correct advisor queue):\n"
        f"  {MidFlightAdvisor.SENTINEL}\n"
        "  ## Mid-flight consult\n"
        "  Issue: <number>          # required so MockWorld can route\n"
        "  ### Question\n"
        "  <your judgment question>\n"
        "  ### Context (summary from executor)\n"
        "  <what you've already established>\n"
        "  [### Options under consideration\n"
        "   - option A\n"
        "   - option B]                # optional\n\n"
        "  Respond with JSON: "
        '{"reasoning":str,"recommendation":str,"confidence":float}\n\n'
        f"Cap: at most {cap} consult calls per review. "
        "Past the cap, the tool will return advisor-unavailable; decide on your own."
    )
