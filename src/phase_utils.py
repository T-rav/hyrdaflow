"""Shared utilities for phase modules — eliminates duplicated patterns."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from harness_insights import FailureCategory, FailureRecord, HarnessInsightStore
from issue_store import IssueStore
from memory import file_memory_suggestion
from models import PipelineStage, PRInfo
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.phase_utils")

T = TypeVar("T")
T_Result = TypeVar("T_Result")

_ADR_TITLE_RE = re.compile(r"^\s*\[ADR\]\s+", re.IGNORECASE)
_ADR_REQUIRED_HEADINGS = ("## Context", "## Decision", "## Consequences")


async def run_concurrent_batch(
    items: list[T],
    worker_fn: Callable[[int, T], Coroutine[Any, Any, T_Result]],
    stop_event: asyncio.Event,
) -> list[T_Result]:
    """Run *worker_fn* on each item concurrently, cancelling on stop.

    Creates one task per item, collects results via ``as_completed``,
    and cancels remaining tasks if *stop_event* is set or if this
    coroutine itself is cancelled externally.
    """
    results: list[T_Result] = []
    all_tasks = [
        asyncio.create_task(worker_fn(i, item)) for i, item in enumerate(items)
    ]
    try:
        for task in asyncio.as_completed(all_tasks):
            results.append(await task)
            if stop_event.is_set():
                for t in all_tasks:
                    t.cancel()
                break
    finally:
        for t in all_tasks:
            if not t.done():
                t.cancel()
    return results


def release_batch_in_flight(store: IssueStore, task_ids: set[int]) -> None:
    """Release in-flight protection for a batch of issues.

    Should be called in a ``finally`` block after ``run_concurrent_batch``
    to ensure no orphaned in-flight entries survive if a worker exits
    without reaching ``mark_active`` / ``mark_complete``.
    """
    store.release_in_flight(task_ids)


async def escalate_to_hitl(
    state: StateTracker,
    prs: PRManager,
    issue_number: int,
    *,
    cause: str,
    origin_label: str,
    hitl_label: str,
) -> None:
    """Record HITL escalation state and swap labels.

    This is the simple escalation path used by plan, implement, and
    triage phases.  The review phase has a richer variant with event
    publishing and PR comment routing.
    """
    state.set_hitl_origin(issue_number, origin_label)
    state.set_hitl_cause(issue_number, cause)
    state.record_hitl_escalation()
    await prs.swap_pipeline_labels(issue_number, hitl_label)


async def safe_file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
    prs: PRManager,
    state: StateTracker,
) -> None:
    """File a memory suggestion, swallowing and logging exceptions."""
    try:
        await file_memory_suggestion(
            transcript,
            source,
            reference,
            config,
            prs,
            state,
        )
    except Exception:
        logger.exception(
            "Failed to file memory suggestion for %s",
            reference,
        )


def record_harness_failure(
    harness_insights: HarnessInsightStore | None,
    issue_number: int,
    category: FailureCategory,
    details: str,
    *,
    stage: PipelineStage,
    pr_number: int = 0,
) -> None:
    """Record a failure to the harness insight store (non-blocking).

    Shared across plan, implement, and review phases.  Silently skips
    when *harness_insights* is ``None`` and suppresses exceptions so
    insight recording never interrupts the pipeline.
    """
    if harness_insights is None:
        return
    try:
        from harness_insights import extract_subcategories  # noqa: PLC0415

        record = FailureRecord(
            issue_number=issue_number,
            pr_number=pr_number,
            category=category,
            subcategories=extract_subcategories(details),
            details=details,
            stage=stage,
        )
        harness_insights.append_failure(record)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to record harness failure for issue #%d",
            issue_number,
            exc_info=True,
        )


@asynccontextmanager
async def store_lifecycle(
    store: IssueStore,
    issue_number: int,
    stage: str,
):
    """Mark an issue active on enter and complete on exit.

    Usage::

        async with store_lifecycle(store, issue.number, "plan"):
            ...  # do work
    """
    store.mark_active(issue_number, stage)
    try:
        yield
    finally:
        store.mark_complete(issue_number)


async def publish_review_status(
    bus: EventBus, pr: PRInfo, worker_id: int, status: str
) -> None:
    """Emit a REVIEW_UPDATE event with the given status."""
    await bus.publish(
        HydraFlowEvent(
            type=EventType.REVIEW_UPDATE,
            data={
                "pr": pr.number,
                "issue": pr.issue_number,
                "worker": worker_id,
                "status": status,
                "role": "reviewer",
            },
        )
    )


def is_adr_issue_title(title: str) -> bool:
    """Return ``True`` when *title* starts with ``[ADR]`` (case-insensitive)."""
    return bool(_ADR_TITLE_RE.match(title))


def adr_validation_reasons(body: str) -> list[str]:
    """Return shape-validation failures for ADR markdown content."""
    reasons: list[str] = []
    text = body.strip()
    if len(text) < 120:
        reasons.append("ADR body is too short (minimum 120 characters)")
    lower = text.lower()
    missing = [h for h in _ADR_REQUIRED_HEADINGS if h.lower() not in lower]
    if missing:
        reasons.append("Missing required ADR sections: " + ", ".join(missing))
    return reasons


_ADR_FILE_RE = re.compile(r"^(\d{4})-.*\.md$")


def next_adr_number(adr_dir: Path) -> int:
    """Return the next available ADR number by scanning *adr_dir*.

    Avoids number collisions when multiple ADR PRs are in flight
    concurrently — each should call this against the worktree's
    ``docs/adr/`` after merging main to pick a unique number.
    """
    highest = 0
    if adr_dir.is_dir():
        for f in adr_dir.iterdir():
            m = _ADR_FILE_RE.match(f.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1
