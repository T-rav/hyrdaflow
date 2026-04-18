"""Regression test for issue #6855.

Bug: ``health_monitor_loop._do_work`` iterates harness suggestions and calls
``await file_memory_suggestion(...)`` inside a bare ``except Exception: continue``
block (line 460). If the Hindsight client raises ``AuthenticationError`` or
``CreditExhaustedError`` during retain, the error is silently swallowed, then
processing continues with the next suggestion. The outer handler at line 464
also lacks a ``reraise_on_credit_or_bug`` guard.

Affected sites:
- ``src/health_monitor_loop.py:460`` — per-item ``except Exception: continue``
- ``src/health_monitor_loop.py:464`` — outer ``except Exception: pass``

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up from
    both sites so the orchestrator's credit-pause / auth-retry logic can
    handle them.

These tests assert the *correct* behaviour and are RED against the current
(buggy) code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"

REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: (file, approx_line, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[str, int, str]] = [
    (
        "health_monitor_loop.py",
        460,
        "per-item except Exception: continue in harness suggestion ingestion",
    ),
    (
        "health_monitor_loop.py",
        464,
        "outer except Exception: pass wrapping harness suggestion ingestion",
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


class TestHealthMonitorSuggestionIngestionBlocksHaveReraise:
    """AST check — the ``except Exception`` blocks surrounding harness
    suggestion ingestion in health_monitor_loop.py must call
    ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    def test_suggestion_ingestion_except_blocks_have_reraise_guard(self) -> None:
        filepath = SRC / "health_monitor_loop.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)
        # Filter to the two known sites near lines 460 and 464
        suggestion_lines = [ln for ln, _ in unguarded if 445 <= ln <= 475]

        assert not suggestion_lines, (
            f"health_monitor_loop.py has unguarded ``except Exception`` "
            f"block(s) in the suggestion ingestion region.\n"
            f"Lines: {suggestion_lines}\n"
            f"Auth/credit failures are silently swallowed — see issue #6855."
        )


class TestKnownSitesHaveReraiseGuard:
    """Parametrised check for each specific site from the issue findings."""

    @pytest.mark.parametrize(
        ("filename", "approx_line", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{ln}" for f, ln, _ in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, approx_line: int, desc: str
    ) -> None:
        filepath = SRC / filename
        assert filepath.exists()

        unguarded = _unguarded_handlers(filepath)
        nearby = [ln for ln, _ in unguarded if abs(ln - approx_line) <= 15]

        assert not nearby, (
            f"{filename}:{approx_line} ({desc}) — ``except Exception`` "
            f"near line {nearby[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6855)."
        )


# ---------------------------------------------------------------------------
# Behavioural: AuthenticationError / CreditExhaustedError must propagate
# ---------------------------------------------------------------------------


class TestHealthMonitorSuggestionIngestionPropagatesFatalErrors:
    """Behavioural tests — when ``file_memory_suggestion`` raises
    ``AuthenticationError`` or ``CreditExhaustedError``, the exception
    must NOT be swallowed by the per-item or outer except blocks.
    """

    @pytest.fixture()
    def suggestions_dir(self, tmp_path: Path) -> Path:
        """Create a harness_suggestions.jsonl with one valid suggestion."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        jsonl = memory_dir / "harness_suggestions.jsonl"
        jsonl.write_text(
            '{"suggestion":"test principle","title":"test","occurrences":1,'
            '"category":"test_cat"}\n',
            encoding="utf-8",
        )
        return tmp_path

    @pytest.mark.asyncio()
    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    async def test_authentication_error_propagates(
        self, suggestions_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AuthenticationError from file_memory_suggestion must not be
        swallowed — it should propagate so the orchestrator can handle it.
        """
        from unittest.mock import AsyncMock

        from subprocess_util import AuthenticationError

        loop = _make_health_monitor(suggestions_dir)

        # Patch file_memory_suggestion to raise AuthenticationError
        mock_fms = AsyncMock(side_effect=AuthenticationError("token expired"))
        monkeypatch.setattr("memory.file_memory_suggestion", mock_fms)

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio()
    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    async def test_credit_exhausted_error_propagates(
        self, suggestions_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CreditExhaustedError from file_memory_suggestion must not be
        swallowed — it should propagate so the orchestrator can pause.
        """
        from unittest.mock import AsyncMock

        from subprocess_util import CreditExhaustedError

        loop = _make_health_monitor(suggestions_dir)

        mock_fms = AsyncMock(side_effect=CreditExhaustedError("credits gone"))
        monkeypatch.setattr("memory.file_memory_suggestion", mock_fms)

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_health_monitor(data_dir: Path) -> object:
    """Build a HealthMonitorLoop with data_root pointing at *data_dir*.

    Uses ``make_bg_loop_deps`` to get a real LoopDeps, then overrides
    ``data_root`` so ``data_path("memory", ...)`` resolves to the tmp dir.
    """
    from health_monitor_loop import HealthMonitorLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(data_dir)
    config = bg.config
    # Bypass Pydantic __setattr__ to point data_root at our fixture dir
    object.__setattr__(config, "data_root", data_dir)

    return HealthMonitorLoop(config=config, deps=bg.loop_deps)
