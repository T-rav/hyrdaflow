"""Visual validation with bounded retry strategy and flake mitigation.

Performs visual screen checks with:
- Bounded retries for transient failures (infra, timeout, capture errors).
- No retries for genuine visual diffs.
- Deterministic pass/warn/fail thresholds.
- Separate classification for infrastructure vs visual failures.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from config import HydraFlowConfig
from models import (
    VisualFailureClass,
    VisualScreenResult,
    VisualScreenVerdict,
    VisualValidationReport,
)

logger = logging.getLogger("hydraflow.visual_validator")

# Failure classes that are transient and eligible for retry.
_TRANSIENT_FAILURE_CLASSES: frozenset[VisualFailureClass] = frozenset(
    {
        VisualFailureClass.INFRA_FAILURE,
        VisualFailureClass.TIMEOUT,
        VisualFailureClass.CAPTURE_ERROR,
    }
)

# Type alias for the visual check callable that callers must provide.
# Signature: (screen_name) -> VisualScreenResult
VisualCheckFn = Callable[[str], Coroutine[Any, Any, VisualScreenResult]]


def classify_failure(error: Exception) -> VisualFailureClass:
    """Classify an exception into a visual failure class."""
    if isinstance(error, TimeoutError):
        return VisualFailureClass.TIMEOUT
    if isinstance(error, ConnectionError | OSError):
        return VisualFailureClass.INFRA_FAILURE
    return VisualFailureClass.CAPTURE_ERROR


def apply_thresholds(
    diff_ratio: float,
    warn_threshold: float,
    fail_threshold: float,
) -> VisualScreenVerdict:
    """Determine verdict based on diff ratio and thresholds."""
    if diff_ratio >= fail_threshold:
        return VisualScreenVerdict.FAIL
    if diff_ratio >= warn_threshold:
        return VisualScreenVerdict.WARN
    return VisualScreenVerdict.PASS


def is_transient(result: VisualScreenResult) -> bool:
    """Return True if the failure is transient and eligible for retry."""
    return (
        result.failure_class is not None
        and result.failure_class in _TRANSIENT_FAILURE_CLASSES
    )


class VisualValidator:
    """Orchestrates visual validation with retry and threshold logic.

    The validator does NOT perform actual screenshot capture or diffing.
    Instead, callers supply a ``check_fn`` that does the work; this class
    handles retry policy, threshold classification, and report aggregation.
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config

    async def validate_screens(
        self,
        screen_names: list[str],
        check_fn: VisualCheckFn,
    ) -> VisualValidationReport:
        """Run visual checks for all screens with retry logic.

        Args:
            screen_names: List of screen identifiers to validate.
            check_fn: Async callable that performs the actual visual check.
                       Must return a :class:`VisualScreenResult`.

        Returns:
            Aggregated :class:`VisualValidationReport`.
        """
        if not screen_names:
            return VisualValidationReport()

        results: list[VisualScreenResult] = []
        total_retries = 0
        infra_failures = 0
        visual_diffs = 0

        for name in screen_names:
            result, retries = await self._check_with_retry(name, check_fn)
            # Apply threshold classification if no failure class
            if result.failure_class is None:
                result.verdict = apply_thresholds(
                    result.diff_ratio,
                    self._config.visual_warn_threshold,
                    self._config.visual_fail_threshold,
                )
            result.retries_used = retries
            total_retries += retries

            if result.failure_class == VisualFailureClass.VISUAL_DIFF:
                visual_diffs += 1
            elif result.failure_class in _TRANSIENT_FAILURE_CLASSES:
                infra_failures += 1

            results.append(result)

        overall = self._compute_overall_verdict(results)

        return VisualValidationReport(
            screens=results,
            overall_verdict=overall,
            total_retries=total_retries,
            infra_failures=infra_failures,
            visual_diffs=visual_diffs,
        )

    async def _check_with_retry(
        self,
        screen_name: str,
        check_fn: VisualCheckFn,
    ) -> tuple[VisualScreenResult, int]:
        """Run a single screen check with bounded retries for transient failures.

        Returns ``(result, retries_used)``.
        """
        max_retries = max(0, self._config.visual_max_retries)
        delay = self._config.visual_retry_delay

        last_result: VisualScreenResult | None = None
        retries_used = 0

        for attempt in range(max_retries + 1):
            try:
                result = await check_fn(screen_name)
            except Exception as exc:
                failure_class = classify_failure(exc)
                result = VisualScreenResult(
                    screen_name=screen_name,
                    failure_class=failure_class,
                    verdict=VisualScreenVerdict.FAIL,
                    error=str(exc),
                )

            last_result = result

            # If it's a genuine visual diff, don't retry
            if result.failure_class == VisualFailureClass.VISUAL_DIFF:
                break

            # If no failure class (clean result), we're done
            if result.failure_class is None:
                break

            # If it's a transient failure and we have retries left, retry
            if is_transient(result) and attempt < max_retries:
                retries_used += 1
                logger.info(
                    "Visual check '%s' transient failure (%s), retry %d/%d",
                    screen_name,
                    result.failure_class.value,
                    retries_used,
                    max_retries,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                continue

            # Non-transient or retries exhausted
            break

        if last_result is None:
            raise RuntimeError(
                f"Visual check '{screen_name}' produced no result after {max_retries + 1} attempt(s)"
            )
        return last_result, retries_used

    @staticmethod
    def _compute_overall_verdict(
        results: list[VisualScreenResult],
    ) -> VisualScreenVerdict:
        """Compute the worst-case overall verdict from all screen results."""
        if not results:
            return VisualScreenVerdict.PASS

        has_fail = any(r.verdict == VisualScreenVerdict.FAIL for r in results)
        if has_fail:
            return VisualScreenVerdict.FAIL

        has_warn = any(r.verdict == VisualScreenVerdict.WARN for r in results)
        if has_warn:
            return VisualScreenVerdict.WARN

        return VisualScreenVerdict.PASS
