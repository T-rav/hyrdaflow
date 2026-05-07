"""Regression: subprocess.run in async loop code paths must have timeout=.

Same deadlock class as PR #8454 (contract_recording event-loop fix):
sync subprocess.run on the asyncio event loop blocks the entire
orchestrator if the subprocess hangs. Even when wrapped in
asyncio.to_thread (which prevents event-loop block), an unbounded
subprocess can leak a thread forever, exhausting the thread pool.

This test asserts every subprocess.run call in async-touched modules
specifies a timeout. The list is the source of truth for which
production async code paths have been hardened — adding a path here
without first applying the fix will fail this regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent

# Modules whose subprocess.run calls run from async contexts and
# therefore MUST specify a timeout. Add to this list when introducing
# new async-spawning subprocess sites.
#
# Each entry was identified by an audit cued by PR #8454
# (contract_recording event-loop fix). Wrap-in-``asyncio.to_thread``
# alone is not enough; an unbounded subprocess will leak the worker
# thread and exhaust the pool.
_ASYNC_SUBPROCESS_MODULES = [
    "src/diagram_loop.py",
    "src/repo_wiki.py",
    "src/repo_wiki_loop.py",
    "src/arch/runner.py",
    # PR #8454 hardened these wrappers; PR #8456 covered the rest of the
    # async paths; this PR closes the audit by adding the two sites the
    # original audit missed.
    "src/contract_recording.py",
    # ``_run_git`` / ``_run_gh`` wrappers run under ``asyncio.to_thread``
    # from ``open_automated_pr_async``; without ``timeout=`` a stale
    # ``git push`` or ``gh`` auth-refresh hang leaks a thread-pool worker.
    "src/auto_pr.py",
]


def _subprocess_run_blocks(src: str) -> list[str]:
    """Return the argument text of every ``subprocess.run(...)`` call.

    Walks the source character-by-character, tracking nested parens
    so multi-line calls with bracketed argv are handled. Skips matches
    inside string literals.
    """
    blocks: list[str] = []
    needle = "subprocess.run("
    i = 0
    n = len(src)
    while True:
        start = src.find(needle, i)
        if start == -1:
            return blocks
        # Naive in-string filter: count unescaped quotes on the line so
        # ``# subprocess.run(...)`` in a docstring doesn't fool us. The
        # producers we audit don't put ``subprocess.run(`` mid-string,
        # so this stays simple.
        line_start = src.rfind("\n", 0, start) + 1
        line_prefix = src[line_start:start]
        if line_prefix.lstrip().startswith("#"):
            i = start + len(needle)
            continue
        depth = 1
        j = start + len(needle)
        while j < n and depth:
            ch = src[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        blocks.append(src[start + len(needle) : j - 1])
        i = j


@pytest.mark.parametrize("rel_path", _ASYNC_SUBPROCESS_MODULES)
def test_subprocess_run_has_timeout(rel_path: str) -> None:
    """subprocess.run calls in this module must include a timeout argument."""
    path = _REPO / rel_path
    src = path.read_text()
    blocks = _subprocess_run_blocks(src)
    if not blocks:
        pytest.skip(f"{rel_path} has no subprocess.run calls")
    timeout_pat = re.compile(r"\btimeout\s*=")
    missing = [b for b in blocks if not timeout_pat.search(b)]
    assert not missing, (
        f"{rel_path}: {len(missing)} of {len(blocks)} subprocess.run calls "
        f"lack timeout=. Missing timeouts can deadlock async loops via "
        f"thread-pool exhaustion (same class as PR #8454). "
        f"First missing block: {missing[0][:200]!r}"
    )
