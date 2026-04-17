"""Regression test for issue #6808.

The ``except Exception: pass`` block wrapping Sentry tag-setting in
``base_runner._execute()`` (lines 149-162) is over-broad.  It silently
swallows programming errors (``AttributeError``, ``TypeError``) in the
Sentry block that should propagate so developers can diagnose them.

The comment says "Sentry not installed or not initialized", but any
exception — including genuine programming bugs — is silently discarded.

The fix should narrow to ``except ImportError`` so that only the expected
failure (sentry_sdk not installed) is silently handled.

These tests are RED until the fix is applied.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from base_runner import BaseRunner
from events import EventBus


class _TestRunner(BaseRunner):
    """Minimal concrete subclass for testing."""

    _log = logging.getLogger("hydraflow.test_runner_6808")


# ---------------------------------------------------------------------------
# base_runner._execute — inner except Exception: pass is over-broad
# ---------------------------------------------------------------------------


class TestSentryBlockSwallowsProgrammingErrors:
    """The inner ``except Exception: pass`` in _execute() silently eats
    non-ImportError exceptions from the Sentry tag-setting block.

    After the fix (``except ImportError``), these errors will propagate.
    """

    @pytest.mark.asyncio
    async def test_attribute_error_in_set_tag_is_not_silently_swallowed(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """An AttributeError from sentry_sdk.set_tag must propagate.

        Scenario: sentry_sdk is installed but set_tag raises AttributeError
        due to a programming mistake (e.g. wrong arg type, uninitialised hub).
        The current ``except Exception: pass`` silently discards it.
        """
        runner = _TestRunner(config, event_bus)

        fake_sentry = types.ModuleType("sentry_sdk")

        def _bad_set_tag(*_args, **_kwargs):
            raise AttributeError("set_tag called on uninitialised hub")

        fake_sentry.set_tag = _bad_set_tag
        fake_sentry.set_context = lambda *a, **kw: None

        with (
            patch.dict(sys.modules, {"sentry_sdk": fake_sentry}),
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="transcript",
            ),
        ):
            # BUG: the current code catches this with ``except Exception: pass``
            # and returns "transcript" as though nothing went wrong.
            # EXPECTED: the AttributeError should propagate.
            with pytest.raises(AttributeError, match="uninitialised hub"):
                await runner._execute(
                    ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
                )

    @pytest.mark.asyncio
    async def test_type_error_in_set_context_is_not_silently_swallowed(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """A TypeError from sentry_sdk.set_context must propagate.

        Scenario: sentry_sdk.set_context receives an unexpected type due to
        a programming error (e.g. config.model is None where str is expected).
        The current ``except Exception: pass`` silently discards it.
        """
        runner = _TestRunner(config, event_bus)

        fake_sentry = types.ModuleType("sentry_sdk")
        fake_sentry.set_tag = lambda *a, **kw: None

        def _bad_set_context(*_args, **_kwargs):
            raise TypeError("set_context expects dict, got NoneType")

        fake_sentry.set_context = _bad_set_context

        with (
            patch.dict(sys.modules, {"sentry_sdk": fake_sentry}),
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="transcript",
            ),
            pytest.raises(TypeError, match="set_context expects dict"),
        ):
            await runner._execute(["claude", "-p"], "prompt", tmp_path, {"issue": 42})

    @pytest.mark.asyncio
    async def test_import_error_is_still_silently_handled(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """ImportError from ``import sentry_sdk`` should remain silent.

        This test verifies the DESIRED behavior — when sentry_sdk is genuinely
        not installed, the block should catch the ImportError and continue.
        This test should be GREEN both before and after the fix.
        """
        runner = _TestRunner(config, event_bus)

        # Remove sentry_sdk from sys.modules so the import fails
        with (
            patch.dict(sys.modules, {"sentry_sdk": None}),
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="transcript",
            ),
        ):
            # Should NOT raise — ImportError is the expected failure mode
            result = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
            )
            assert result == "transcript"
