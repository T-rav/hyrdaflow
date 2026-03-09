"""Tests for log_exception_with_bug_classification() and run_with_fatal_guard()."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from phase_utils import log_exception_with_bug_classification, run_with_fatal_guard

# ---------------------------------------------------------------------------
# log_exception_with_bug_classification
# ---------------------------------------------------------------------------


class TestLogExceptionWithBugClassification:
    """Verify logging behaviour based on exception type."""

    def test_likely_bug_logs_critical(self) -> None:
        log = MagicMock(spec=logging.Logger)
        exc = TypeError("bad type")
        log_exception_with_bug_classification(log, exc, "test context")
        log.critical.assert_called_once()
        args, kwargs = log.critical.call_args
        # %s-style: first positional is the format string, then context and exc name
        assert args[1] == "test context"
        assert args[2] == "TypeError"
        assert kwargs["exc_info"] is True

    def test_transient_error_logs_warning(self) -> None:
        log = MagicMock(spec=logging.Logger)
        exc = RuntimeError("transient")
        log_exception_with_bug_classification(log, exc, "ctx")
        log.warning.assert_called_once()
        args, kwargs = log.warning.call_args
        assert args[1] == "ctx"
        assert args[2] == "RuntimeError"
        assert kwargs["exc_info"] is True
        log.critical.assert_not_called()

    @pytest.mark.parametrize(
        "exc_cls",
        [
            TypeError,
            KeyError,
            AttributeError,
            ValueError,
            IndexError,
            NotImplementedError,
        ],
    )
    def test_all_bug_exception_types(self, exc_cls: type[Exception]) -> None:
        log = MagicMock(spec=logging.Logger)
        log_exception_with_bug_classification(log, exc_cls("x"), "ctx")
        log.critical.assert_called_once()

    @pytest.mark.parametrize(
        "exc_cls",
        [RuntimeError, OSError, IOError, TimeoutError, ConnectionError],
    )
    def test_transient_exception_types(self, exc_cls: type[Exception]) -> None:
        log = MagicMock(spec=logging.Logger)
        log_exception_with_bug_classification(log, exc_cls("x"), "ctx")
        log.warning.assert_called_once()
        log.critical.assert_not_called()


# ---------------------------------------------------------------------------
# run_with_fatal_guard
# ---------------------------------------------------------------------------


class TestRunWithFatalGuard:
    """Verify the async fatal-guard wrapper."""

    @pytest.mark.asyncio
    async def test_success_returns_coroutine_result(self) -> None:
        async def ok() -> str:
            return "done"

        result = await run_with_fatal_guard(
            ok(),
            on_failure=lambda _: "fail",
            context="test",
            log=MagicMock(spec=logging.Logger),
        )
        assert result == "done"

    @pytest.mark.asyncio
    async def test_non_fatal_exception_calls_on_failure(self) -> None:
        async def boom() -> str:
            raise RuntimeError("oops")

        log = MagicMock(spec=logging.Logger)
        result = await run_with_fatal_guard(
            boom(),
            on_failure=lambda exc_name: f"failed:{exc_name}",
            context="test",
            log=log,
        )
        assert result == "failed:RuntimeError"
        log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_bug_exception_calls_on_failure_and_logs_critical(self) -> None:
        async def boom() -> str:
            raise TypeError("bad")

        log = MagicMock(spec=logging.Logger)
        result = await run_with_fatal_guard(
            boom(),
            on_failure=lambda exc_name: f"failed:{exc_name}",
            context="test",
            log=log,
        )
        assert result == "failed:TypeError"
        log.critical.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_error_propagates(self) -> None:
        async def boom() -> str:
            raise MemoryError()

        with pytest.raises(MemoryError):
            await run_with_fatal_guard(
                boom(),
                on_failure=lambda _: "fail",
                context="test",
                log=MagicMock(spec=logging.Logger),
            )

    @pytest.mark.asyncio
    async def test_authentication_error_propagates(self) -> None:
        from subprocess_util import AuthenticationError

        async def boom() -> str:
            raise AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await run_with_fatal_guard(
                boom(),
                on_failure=lambda _: "fail",
                context="test",
                log=MagicMock(spec=logging.Logger),
            )

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_propagates(self) -> None:
        from subprocess_util import CreditExhaustedError

        async def boom() -> str:
            raise CreditExhaustedError("no credits")

        with pytest.raises(CreditExhaustedError):
            await run_with_fatal_guard(
                boom(),
                on_failure=lambda _: "fail",
                context="test",
                log=MagicMock(spec=logging.Logger),
            )

    @pytest.mark.asyncio
    async def test_on_failure_receives_exception_class_name(self) -> None:
        async def boom() -> str:
            raise ConnectionResetError("reset")

        captured: list[str] = []

        def capture(name: str) -> str:
            captured.append(name)
            return "x"

        await run_with_fatal_guard(
            boom(),
            on_failure=capture,
            context="test",
            log=MagicMock(spec=logging.Logger),
        )
        assert captured == ["ConnectionResetError"]
