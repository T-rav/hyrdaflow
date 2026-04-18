"""Regression test for issue #6622.

Bug: ``health_monitor_loop._do_work`` at lines 391-392 catches ``Exception``
on the EventBus enrichment block with a bare ``pass`` and no logging.  This
means any failure in ``enrich_patterns_with_events`` — including real bugs
like ``TypeError`` or ``KeyError`` in event dict construction — is swallowed
silently.  Operators have no signal that enrichment is failing every cycle.

Expected behaviour after fix:
  - ``logger.debug("EventBus enrichment failed", exc_info=True)`` (or
    equivalent) is emitted inside the ``except`` block so failures are
    visible in debug logs.
  - Enrichment remains best-effort (no re-raise).

This test asserts the *correct* behaviour, so it is RED against the current
buggy code.
"""

from __future__ import annotations

import logging
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(tmp_path: Path) -> Any:
    """Build a minimal HealthMonitorLoop for testing."""
    from health_monitor_loop import HealthMonitorLoop

    deps = make_bg_loop_deps(tmp_path, enabled=True, health_monitor_interval=60)
    loop = HealthMonitorLoop(
        config=deps.config,
        deps=deps.loop_deps,
        verification_window=5,
    )
    return loop


def _fake_log_ingestion_module(
    *, enrich_raises: Exception | None = None
) -> types.ModuleType:
    """Create a fake ``log_ingestion`` module with controllable behaviour.

    All functions are stubs except ``enrich_patterns_with_events`` which
    raises *enrich_raises* if provided.
    """
    mod = types.ModuleType("log_ingestion")
    mod.parse_log_files = MagicMock(return_value=[{"line": "x"}])  # type: ignore[attr-defined]
    mod.detect_log_patterns = MagicMock(return_value=[{"pattern": "p"}])  # type: ignore[attr-defined]
    mod.load_known_patterns = MagicMock(return_value={})  # type: ignore[attr-defined]
    mod.save_known_patterns = MagicMock()  # type: ignore[attr-defined]

    file_result = MagicMock()
    file_result.total_patterns = 1
    file_result.filed = 0
    file_result.escalated = 0
    mod.file_log_patterns = AsyncMock(return_value=file_result)  # type: ignore[attr-defined]

    if enrich_raises is not None:

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise enrich_raises

        mod.enrich_patterns_with_events = _boom  # type: ignore[attr-defined]
    else:
        mod.enrich_patterns_with_events = MagicMock()  # type: ignore[attr-defined]

    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnrichmentExceptionIsLogged:
    """Issue #6622 — EventBus enrichment exceptions must be logged, not swallowed."""

    @pytest.mark.asyncio
    async def test_enrichment_typeerror_emits_debug_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When ``enrich_patterns_with_events`` raises a ``TypeError``, the
        except block must log at DEBUG (or higher) with ``exc_info``.

        Currently FAILS (RED) because the except block at line 391 has only
        ``pass``.
        """
        loop = _make_loop(tmp_path)

        # Create a log directory so the log-ingestion branch is entered
        log_dir = loop._config.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "app.log").write_text("some log line\n")

        # Create a fake log_ingestion module where enrich raises TypeError
        fake_mod = _fake_log_ingestion_module(
            enrich_raises=TypeError("bad event dict"),
        )

        # Patch memory_scoring to avoid that import path
        fake_memory_scoring = types.ModuleType("memory_scoring")
        fake_memory_scoring.detect_knowledge_gaps = MagicMock(return_value=[])  # type: ignore[attr-defined]

        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def _selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "log_ingestion":
                return fake_mod
            if name == "memory_scoring":
                return fake_memory_scoring
            return original_import(name, *args, **kwargs)

        # Stub methods that run before the log-ingestion block
        with (
            patch.object(loop, "_verify_pending_adjustments"),
            patch.object(loop, "_apply_adjustments", return_value=[]),
            patch.object(loop, "_file_hitl_recommendations", new_callable=AsyncMock),
            patch("builtins.__import__", side_effect=_selective_import),
        ):
            with caplog.at_level(logging.DEBUG, logger="hydraflow.health_monitor_loop"):
                await loop._do_work()

        # Assert — a debug+ log about enrichment failure should exist
        enrichment_logs = [
            r
            for r in caplog.records
            if r.levelno >= logging.DEBUG
            and "hydraflow.health_monitor_loop" in r.name
            and "enrich" in r.message.lower()
        ]
        assert len(enrichment_logs) >= 1, (
            "Expected at least one DEBUG+ log from hydraflow.health_monitor_loop "
            "mentioning enrichment failure when enrich_patterns_with_events raises "
            "TypeError, but got none.  The except block at "
            "health_monitor_loop.py:391 swallows the error with bare 'pass'."
        )

        # The log record should include exc_info for the traceback
        logged = enrichment_logs[0]
        assert logged.exc_info is not None and logged.exc_info[1] is not None, (
            "The log record must include exc_info=True so that the exception "
            "traceback is visible to operators.  "
            f"Got exc_info={logged.exc_info!r}"
        )

    @pytest.mark.asyncio
    async def test_enrichment_failure_does_not_crash_do_work(
        self, tmp_path: Path
    ) -> None:
        """After the fix, enrichment failures must remain non-blocking —
        ``_do_work`` should complete normally.

        This is GREEN today and must stay GREEN — it guards against an
        over-correction that re-raises instead of logging.
        """
        loop = _make_loop(tmp_path)

        log_dir = loop._config.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "app.log").write_text("some log line\n")

        fake_mod = _fake_log_ingestion_module(
            enrich_raises=TypeError("bad event dict"),
        )
        fake_memory_scoring = types.ModuleType("memory_scoring")
        fake_memory_scoring.detect_knowledge_gaps = MagicMock(return_value=[])  # type: ignore[attr-defined]

        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def _selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "log_ingestion":
                return fake_mod
            if name == "memory_scoring":
                return fake_memory_scoring
            return original_import(name, *args, **kwargs)

        with (
            patch.object(loop, "_verify_pending_adjustments"),
            patch.object(loop, "_apply_adjustments", return_value=[]),
            patch.object(loop, "_file_hitl_recommendations", new_callable=AsyncMock),
            patch("builtins.__import__", side_effect=_selective_import),
        ):
            # Should not raise — enrichment is best-effort
            result = await loop._do_work()

        # _do_work returns a dict or None; it should not raise
        assert result is None or isinstance(result, dict)
