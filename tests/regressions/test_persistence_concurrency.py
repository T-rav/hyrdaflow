"""Regression tests for the file-only persistence layer.

Two invariants are enforced here:

1. ``DedupStore`` writes go through ``file_util.atomic_write``, never
   ``Path.write_text``.  A non-atomic write that crashes mid-flush
   leaves a truncated/empty dedup JSON, and the next read silently
   returns ``set()`` — re-firing whatever was deduped (Sentry issues,
   ADR sources, HITL escalations).

2. State and dedup mutators are never dispatched via
   ``asyncio.to_thread``.  ``StateTracker.save`` and ``DedupStore.add``
   are sync read-modify-write blocks that rely on the asyncio
   single-threaded invariant for safety; threading them exposes
   lost-update.  ``docs/wiki/gotchas.md`` documents the rule but
   nothing else enforces it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"


# ---------------------------------------------------------------------------
# 1. DedupStore must use atomic_write
# ---------------------------------------------------------------------------


class TestDedupStoreUsesAtomicWrite:
    """``DedupStore.add`` and ``set_all`` must persist via atomic_write."""

    def _dedup_store_source(self) -> str:
        return (SRC_ROOT / "dedup_store.py").read_text()

    def test_dedup_store_does_not_call_write_text(self) -> None:
        """No ``write_text`` call may appear in dedup_store.py.

        ``Path.write_text`` is non-atomic — a crash mid-flush leaves the
        file truncated.  Use ``file_util.atomic_write`` instead.
        """
        tree = ast.parse(self._dedup_store_source(), filename="dedup_store.py")
        offending: list[int] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"
            ):
                offending.append(node.lineno)
        assert offending == [], (
            f"dedup_store.py calls write_text at lines {offending} — "
            f"use file_util.atomic_write for crash-safe writes."
        )

    def test_dedup_store_imports_atomic_write(self) -> None:
        """The atomic_write import must be present (proxy for usage)."""
        source = self._dedup_store_source()
        assert re.search(r"\bfrom\s+file_util\s+import\b.*\batomic_write\b", source), (
            "dedup_store.py must import atomic_write from file_util."
        )


# ---------------------------------------------------------------------------
# 2. State and dedup mutators must not be wrapped in asyncio.to_thread
# ---------------------------------------------------------------------------


# Attribute names that, when called via asyncio.to_thread, would expose a
# lost-update race on file-backed persistence.
#
# - StateTracker exposes ``save`` (and many mixin mutators that internally
#   call ``self.save()``).  Wrapping any of them in to_thread can interleave
#   with another in-loop save.
# - DedupStore exposes ``add`` / ``set_all`` (read-modify-write) and ``get``
#   (read).  Threading the writers loses updates; threading the reader is
#   merely wasted overhead.
_FORBIDDEN_TO_THREAD_ATTRS = {
    # StateTracker
    "save",
    # DedupStore
    "add",
    "set_all",
}

# Attribute owners that are state/dedup-shaped enough that a to_thread call
# on them is the bug we're guarding against.  Matched as the rightmost
# attribute of the to_thread arg's value chain (e.g.
# ``self._state.save`` → owner ``_state``).
_FORBIDDEN_OWNERS = {
    "_state",
    "state",
    "_state_tracker",
    "state_tracker",
    "_dedup",
    "_filed",
    "_proposed",
    "_processed_dedup",
    "_zero_diff_memory_filed",
    "_escalation_dedup",
    "sentry_dedup",
}


def _to_thread_first_arg(call: ast.Call) -> ast.expr | None:
    """Return the first positional arg of an ``asyncio.to_thread(...)`` call."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "to_thread":
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != "asyncio":
        return None
    return call.args[0] if call.args else None


def _attribute_owner_and_attr(node: ast.expr) -> tuple[str, str] | None:
    """For ``a.b.c``, return (``b``, ``c``).  None if not an Attribute chain."""
    if not isinstance(node, ast.Attribute):
        return None
    owner = node.value
    if isinstance(owner, ast.Attribute):
        return owner.attr, node.attr
    if isinstance(owner, ast.Name):
        return owner.id, node.attr
    return None


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, expr)`` for forbidden ``to_thread`` calls in *path*."""
    try:
        source = path.read_text()
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        first = _to_thread_first_arg(node)
        if first is None:
            continue
        owner_attr = _attribute_owner_and_attr(first)
        if owner_attr is None:
            continue
        owner, attr = owner_attr
        if attr in _FORBIDDEN_TO_THREAD_ATTRS and owner in _FORBIDDEN_OWNERS:
            violations.append((node.lineno, f"{owner}.{attr}"))
    return violations


class TestNoThreadedStateOrDedupMutations:
    """No ``asyncio.to_thread`` may dispatch state.save or DedupStore mutators."""

    def test_no_forbidden_to_thread_calls_in_src(self) -> None:
        """Scan every src/*.py file for the forbidden pattern."""
        all_violations: dict[str, list[tuple[int, str]]] = {}
        for py_file in sorted(SRC_ROOT.rglob("*.py")):
            violations = _scan_file(py_file)
            if violations:
                all_violations[py_file.relative_to(SRC_ROOT).as_posix()] = violations
        assert all_violations == {}, (
            "asyncio.to_thread() must not wrap StateTracker.save or DedupStore "
            "mutators — they rely on the asyncio single-thread invariant for "
            "lost-update safety. See docs/wiki/gotchas.md.\n\n"
            f"Violations: {all_violations}"
        )


# ---------------------------------------------------------------------------
# Sanity check: the AST scanner itself catches the forbidden pattern
# ---------------------------------------------------------------------------


class TestThreadGuardSelfCheck:
    """The scanner must flag a synthetic offender — guards against scanner rot."""

    @pytest.mark.parametrize(
        "snippet",
        [
            "import asyncio\nasync def f(self):\n    await asyncio.to_thread(self._state.save)\n",
            "import asyncio\nasync def f(self):\n    await asyncio.to_thread(self._dedup.add, 'x')\n",
            "import asyncio\nasync def f(self):\n    await asyncio.to_thread(self._proposed.set_all, set())\n",
        ],
        ids=["state.save", "dedup.add", "proposed.set_all"],
    )
    def test_scanner_flags_offender(self, snippet: str, tmp_path: Path) -> None:
        bad = tmp_path / "offender.py"
        bad.write_text(snippet)
        assert _scan_file(bad), (
            f"scanner failed to flag offender:\n{snippet}\n"
            "If this fails, _FORBIDDEN_OWNERS or the AST walker has drifted."
        )

    def test_scanner_ignores_safe_to_thread_calls(self, tmp_path: Path) -> None:
        ok = tmp_path / "ok.py"
        ok.write_text(
            "import asyncio\n"
            "async def f(self):\n"
            "    await asyncio.to_thread(self._wiki_store.commit_entries)\n"
            "    await asyncio.to_thread(some_module_level_helper, arg)\n"
        )
        assert _scan_file(ok) == []
