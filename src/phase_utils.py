"""Shared utilities for phase modules — eliminates duplicated patterns."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar

# ADR utilities — canonical home is ``adr_utils``; re-exported here for
# backward compatibility so existing consumers don't break.
from adr_utils import (  # noqa: F401
    ADR_FILE_RE,
    _assigned_adr_numbers,
    adr_validation_reasons,
    is_adr_issue_title,
    load_existing_adr_topics,
    next_adr_number,
    normalize_adr_topic,
)
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent

# Exception classification — canonical definitions live in
# ``exception_classify`` (cross-cutting); re-exported here for backward
# compatibility so existing consumers don't break.
from exception_classify import (  # noqa: F401
    LIKELY_BUG_EXCEPTIONS,
    is_likely_bug,
)
from harness_insights import FailureCategory, FailureRecord, HarnessInsightStore
from memory import file_memory_suggestion
from models import PipelineStage, PRInfo, ReviewUpdatePayload, Task
from ports import IssueStorePort, PRPort
from state import StateTracker

logger = logging.getLogger("hydraflow.phase_utils")

T = TypeVar("T")
T_Result = TypeVar("T_Result")


@contextmanager
def _sentry_transaction(op: str, name: str) -> Generator[None, None, None]:
    """Context manager that wraps a block in a Sentry transaction.

    A no-op when ``sentry_sdk`` is not installed.  The transaction uses
    ``op`` as the operation name and ``name`` as the human-readable label
    shown in the Sentry UI (e.g. ``"implement:#42"``).

    Usage::

        with _sentry_transaction("pipeline.implement", f"implement:#{issue.id}"):
            result = await self._run_worker(issue)
    """
    try:
        import sentry_sdk  # noqa: PLC0415

        with sentry_sdk.start_transaction(op=op, name=name):
            yield
    except ImportError:
        yield


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


async def run_refilling_pool(
    supply_fn: Callable[[], list[T]],
    worker_fn: Callable[[int, T], Coroutine[Any, Any, T_Result]],
    max_concurrent: int,
    stop_event: asyncio.Event,
) -> list[T_Result]:
    """Run *worker_fn* in a slot-filling pool, pulling new items as slots free.

    Unlike :func:`run_concurrent_batch` which processes a fixed list,
    this continuously pulls from *supply_fn* whenever a slot opens.
    This ensures no worker capacity sits idle while work is available
    in the queue.

    *supply_fn* should return up to N available items (non-blocking).
    It is called each time a slot frees up to refill the pool.
    """
    results: list[T_Result] = []
    pending: dict[asyncio.Task[T_Result], int] = {}  # task -> issue id placeholder
    worker_id_counter = 0

    try:
        while not stop_event.is_set():
            # Fill all empty slots — call supply repeatedly until full or dry
            while len(pending) < max_concurrent:
                new_items = supply_fn()
                if not new_items:
                    break
                free = max_concurrent - len(pending)
                for item in new_items[:free]:
                    task = asyncio.create_task(worker_fn(worker_id_counter, item))
                    pending[task] = worker_id_counter
                    worker_id_counter += 1

            if not pending:
                break

            done, _ = await asyncio.wait(
                pending.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                del pending[task]
                exc = task.exception()
                if exc is not None:
                    from subprocess_util import (  # noqa: PLC0415
                        AuthenticationError,
                        CreditExhaustedError,
                    )

                    if isinstance(
                        exc,
                        AuthenticationError | CreditExhaustedError | MemoryError,
                    ):
                        for t in pending:
                            t.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        raise exc
                    logger.warning("Pool worker failed: %s", exc, exc_info=exc)
                else:
                    results.append(task.result())
    finally:
        # Cancel stragglers on stop or external cancellation
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    return results


def release_batch_in_flight(store: IssueStorePort, issue_numbers: set[int]) -> None:
    """Release in-flight protection for a batch of issues.

    Should be called in a ``finally`` block after ``run_concurrent_batch``
    to ensure no orphaned in-flight entries survive if a worker exits
    without reaching ``mark_active`` / ``mark_complete``.
    """
    store.release_in_flight(issue_numbers)


async def escalate_to_hitl(
    state: StateTracker,
    prs: PRPort,
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
    prs: PRPort | None = None,  # deprecated, ignored
    state: StateTracker | None = None,  # deprecated, ignored
) -> None:
    """File a memory suggestion, swallowing and logging exceptions."""
    try:
        await file_memory_suggestion(
            transcript,
            source,
            reference,
            config,
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
    store: IssueStorePort,
    issue_number: int,
    stage: str,
):
    """Mark an issue active on enter and complete on exit.

    Args:
        store: The issue store that tracks active/complete status.
        issue_number: GitHub issue number to mark.
        stage: Pipeline stage name (e.g. ``"plan"``, ``"review"``).

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
            data=ReviewUpdatePayload(
                pr=pr.number,
                issue=pr.issue_number,
                worker=worker_id,
                status=status,
                role="reviewer",
            ),
        )
    )


# ---------------------------------------------------------------------------
# Exception classification helpers (use ``is_likely_bug`` and
# ``LIKELY_BUG_EXCEPTIONS`` imported from ``exception_classify`` above).
# ---------------------------------------------------------------------------


def capture_if_bug(exc: Exception, **context: object) -> None:
    """Send to Sentry only if the exception looks like a real bug."""
    try:
        import sentry_sdk  # noqa: PLC0415

        if is_likely_bug(exc):
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.add_breadcrumb(
                category="transient_error",
                message=str(exc)[:500],
                level="warning",
                data=context,
            )
    except Exception:
        pass  # Sentry not installed


def reraise_on_credit_or_bug(exc: BaseException) -> None:
    """Re-raise *exc* if it is a fatal infrastructure error or a likely bug.

    Call this at the top of an ``except Exception`` handler to replace the
    duplicated pattern::

        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception as exc:
            if is_likely_bug(exc):
                raise

    with the shorter::

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
    """
    from subprocess_util import AuthenticationError, CreditExhaustedError

    if isinstance(exc, AuthenticationError | CreditExhaustedError):
        raise exc
    if is_likely_bug(exc):
        raise exc


def log_exception_with_bug_classification(
    log: logging.Logger,
    exc: BaseException,
    context: str,
) -> None:
    """Log *exc* at the appropriate severity based on :func:`is_likely_bug`.

    If the exception is likely a code bug, log at ``CRITICAL`` with a
    "needs code fix" hint; otherwise log at ``WARNING`` with ``exc_info``.
    """
    exc_type_name = type(exc).__name__
    if is_likely_bug(exc):
        log.critical(
            "%s — likely bug (%s), needs code fix",
            context,
            exc_type_name,
            exc_info=True,
        )
    else:
        log.warning("%s — %s", context, exc_type_name, exc_info=True)


async def run_with_fatal_guard(
    coro: Coroutine[Any, Any, T],
    *,
    on_failure: Callable[[str], T],
    context: str,
    log: logging.Logger,
) -> T:
    """Await *coro*, re-raising fatal errors and classifying the rest.

    Fatal errors (``AuthenticationError``, ``CreditExhaustedError``,
    ``MemoryError``) propagate immediately.  All other exceptions are
    logged via :func:`log_exception_with_bug_classification` and
    ``on_failure(exc_type_name)`` is returned as the result.
    """
    from subprocess_util import (  # noqa: PLC0415 — deferred to avoid circular import
        AuthenticationError,
        CreditExhaustedError,
    )

    try:
        return await coro
    except (AuthenticationError, CreditExhaustedError, MemoryError):
        raise
    except Exception as exc:
        log_exception_with_bug_classification(log, exc, context)
        return on_failure(type(exc).__name__)


class MemorySuggester:
    """Pre-bound callable for :func:`safe_file_memory_suggestion`.

    Stores the config so call sites only need to pass
    ``(transcript, source, reference)``.  The ``prs`` and ``state``
    parameters are accepted for backward compatibility but ignored.

    Usage::

        suggest = MemorySuggester(config, prs, state)
        await suggest(transcript, "planner", f"issue #{issue.id}")
    """

    __slots__ = ("_config", "_prs", "_state")

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRPort | None = None,
        state: StateTracker | None = None,
    ) -> None:
        self._config = config
        self._prs = prs
        self._state = state

    async def __call__(self, transcript: str, source: str, reference: str) -> None:
        await safe_file_memory_suggestion(transcript, source, reference, self._config)


class PipelineEscalator:
    """Bundles ``escalate_to_hitl`` + ``enqueue_transition`` + ``record_harness_failure``.

    The plan and implement phases repeat this trio at every escalation
    site.  This helper encapsulates the three calls so each call site
    collapses to a single ``await escalator(...)`` invocation.

    Usage::

        escalator = PipelineEscalator(
            state, prs, store, harness_insights,
            origin_label=config.planner_label[0],
            hitl_label=config.hitl_label[0],
            stage=PipelineStage.PLAN,
        )
        await escalator(issue, cause="...", details="...", category=FailureCategory.PLAN_VALIDATION)
    """

    __slots__ = (
        "_state",
        "_prs",
        "_store",
        "_harness_insights",
        "_origin_label",
        "_hitl_label",
        "_stage",
    )

    def __init__(
        self,
        state: StateTracker,
        prs: PRPort,
        store: IssueStorePort,
        harness_insights: HarnessInsightStore | None,
        *,
        origin_label: str,
        hitl_label: str,
        stage: PipelineStage,
    ) -> None:
        self._state = state
        self._prs = prs
        self._store = store
        self._harness_insights = harness_insights
        self._origin_label = origin_label
        self._hitl_label = hitl_label
        self._stage = stage

    async def __call__(
        self,
        issue: Task,
        *,
        cause: str,
        details: str,
        category: FailureCategory,
    ) -> None:
        """Escalate *issue* to HITL, enqueue transition, and record failure."""
        issue_number = issue.id
        try:
            await escalate_to_hitl(
                self._state,
                self._prs,
                issue_number,
                cause=cause,
                origin_label=self._origin_label,
                hitl_label=self._hitl_label,
            )
        except Exception:
            logger.error(
                "Escalation to HITL failed for issue #%d — attempting direct label swap",
                issue_number,
                exc_info=True,
            )
            # Best-effort fallback: try label swap directly so the issue
            # doesn't get stuck in its current pipeline stage forever.
            try:
                await self._prs.swap_pipeline_labels(issue_number, self._hitl_label)
            except Exception:
                logger.error(
                    "Fallback label swap also failed for issue #%d — issue may be stuck",
                    issue_number,
                    exc_info=True,
                )
        self._store.enqueue_transition(issue, "hitl")
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            details,
            stage=self._stage,
        )
