"""Regression test for issue #6983.

Bug: ``EpicManager.refresh_cache`` and ``check_stale_epics`` wrap GitHub API
calls in broad ``except Exception`` without calling ``reraise_on_credit_or_bug``.
This means ``AuthenticationError`` and ``CreditExhaustedError`` are silently
consumed and logged as ordinary epic-level errors, rather than propagating to
stop the ``EpicMonitorLoop``.

Affected sites:
- ``src/epic.py:1061`` — ``refresh_cache`` broad ``except Exception``
- ``src/epic.py:1163`` — ``check_stale_epics`` ``post_comment`` handler
- ``src/epic.py:1180`` — ``check_stale_epics`` ``bus.publish`` handler

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate out of
    ``refresh_cache`` and ``check_stale_epics`` so the orchestrator's
    credit-pause / auth-retry logic can handle them.

These tests assert the *correct* behaviour and are RED against the current
(buggy) code.
"""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))

REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: (file, approx_line, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[str, int, str]] = [
    (
        "epic.py",
        1061,
        "refresh_cache broad except Exception swallows AuthenticationError",
    ),
    (
        "epic.py",
        1163,
        "check_stale_epics post_comment broad except Exception swallows fatal errors",
    ),
    (
        "epic.py",
        1180,
        "check_stale_epics bus.publish broad except Exception swallows fatal errors",
    ),
]


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _except_exception_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    """Return all ``except Exception`` handler nodes in *tree*."""
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_reraise_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body calls ``reraise_on_credit_or_bug``."""
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == REQUIRED_GUARD:
            return True
        if isinstance(func, ast.Attribute) and func.attr == REQUIRED_GUARD:
            return True
    return False


def _unguarded_handlers(filepath: Path) -> list[tuple[int, ast.ExceptHandler]]:
    """Return ``(lineno, handler)`` pairs for every ``except Exception``
    that does **not** call ``reraise_on_credit_or_bug``.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(tree)
        if not _handler_calls_reraise_guard(h)
    ]


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


class TestEpicManagerExceptBlocksHaveReraise:
    """AST check -- the ``except Exception`` blocks in ``refresh_cache`` and
    ``check_stale_epics`` must call ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.parametrize(
        ("filename", "approx_line", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{ln}" for f, ln, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, approx_line: int, desc: str
    ) -> None:
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)
        nearby = [ln for ln, _ in unguarded if abs(ln - approx_line) <= 15]

        assert not nearby, (
            f"{filename}:{approx_line} ({desc}) -- ``except Exception`` "
            f"near line {nearby[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6983)."
        )


# ---------------------------------------------------------------------------
# Behavioural: AuthenticationError / CreditExhaustedError must propagate
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path):
    """Build an EpicManager with standard mocks for behavioural tests."""
    from epic import EpicManager
    from events import EventBus
    from state import StateTracker
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
    )
    state = StateTracker(config.state_file)
    bus = EventBus()
    prs = AsyncMock()
    fetcher = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager, state, bus, prs, fetcher


def _register_stale_epic(state, epic_number: int = 100) -> None:
    """Register an epic in state that will be detected as stale."""
    from models import EpicState

    stale_time = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    epic = EpicState(
        epic_number=epic_number,
        title="Stale Epic",
        child_issues=[1, 2],
        last_activity=stale_time,
    )
    state.upsert_epic_state(epic)


def _register_open_epic(state, epic_number: int = 100) -> None:
    """Register an open (non-closed) epic in state for refresh_cache."""
    from models import EpicState

    epic = EpicState(
        epic_number=epic_number,
        title="Open Epic",
        child_issues=[1, 2],
    )
    state.upsert_epic_state(epic)


class TestRefreshCachePropagatesFatalErrors:
    """Behavioural tests -- when ``_build_detail`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``refresh_cache``, the exception must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_refresh_cache(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, _, _, _ = _make_manager(tmp_path)
        _register_open_epic(state)

        mgr._build_detail = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.refresh_cache()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_refresh_cache(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, _, _, _ = _make_manager(tmp_path)
        _register_open_epic(state)

        mgr._build_detail = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.refresh_cache()


class TestCheckStaleEpicsPostCommentPropagatesFatalErrors:
    """Behavioural tests -- when ``post_comment`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``check_stale_epics``, the exception must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_post_comment(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, _, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.check_stale_epics()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_post_comment(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, _, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.check_stale_epics()


class TestCheckStaleEpicsBusPublishPropagatesFatalErrors:
    """Behavioural tests -- when ``bus.publish`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``check_stale_epics`` (the SYSTEM_ALERT publish), the exception
    must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_bus_publish(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, bus, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        # post_comment succeeds, but bus.publish raises on the SYSTEM_ALERT
        prs.post_comment = AsyncMock()
        bus.publish = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.check_stale_epics()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_bus_publish(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, bus, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock()
        bus.publish = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.check_stale_epics()
