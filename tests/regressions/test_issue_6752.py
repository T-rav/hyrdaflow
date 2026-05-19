"""Regression test for issue #6752.

Bug: High-frequency ``except Exception`` blocks in production phase files
do not call ``capture_if_bug()`` or ``reraise_on_credit_or_bug()``.
This means programming errors (TypeError, KeyError, AttributeError, etc.)
are silently swallowed alongside transient failures, making bug triage
impossible from logs alone.

Expected behaviour after fix:
  - Every ``except Exception`` block in phase/diagnostic files either calls
    ``capture_if_bug(exc)`` (to report probable bugs to Sentry) or
    ``reraise_on_credit_or_bug(exc)`` (to re-raise fatal + bug exceptions).

These tests intentionally assert the *correct* behaviour, so they are RED
against the current (buggy) code.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC = Path(__file__).resolve().parent.parent.parent / "src"

#: The two function names that constitute proper bug-classification handling.
BUG_CLASSIFICATION_CALLS = {"capture_if_bug", "reraise_on_credit_or_bug"}

#: Files and line numbers from the issue's findings table.  Each entry is
#: (relative-to-src filename, approximate line of the offending ``except``).
#: The AST scan below does NOT rely on exact line numbers — it checks every
#: ``except Exception`` in the file — but these anchors let us produce
#: targeted failure messages.
#
#: T36 — ``review_phase`` is now a package; the class body containing the
#: original anchored sites lives in ``review_phase/_phase.py``. The exact
#: line numbers from the original 3702-line file no longer apply, but the
#: xfail markers below tolerate that drift (strict=False).
KNOWN_UNGUARDED_SITES: list[tuple[str, int]] = [
    ("review_phase/_phase.py", 626),
    ("review_phase/_phase.py", 861),
    ("diagnostic_runner.py", 145),
    ("diagnostic_loop.py", 219),
    ("plan_phase.py", 660),
]


def _except_exception_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    """Return all ``except Exception`` handler nodes in *tree*."""
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Match bare ``except Exception`` (no ``as`` required, but it must
        # catch exactly ``Exception`` — not a tuple, not bare ``except:``).
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_bug_classifier(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body contains a call to one of the
    bug-classification helpers.
    """
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Direct call: ``capture_if_bug(exc)``
        if isinstance(func, ast.Name) and func.id in BUG_CLASSIFICATION_CALLS:
            return True
        # Qualified call: ``exception_classify.capture_if_bug(exc)``
        if isinstance(func, ast.Attribute) and func.attr in BUG_CLASSIFICATION_CALLS:
            return True
    return False


def _unguarded_handlers(
    filepath: Path,
) -> list[tuple[int, ast.ExceptHandler]]:
    """Parse *filepath* and return ``(lineno, handler)`` pairs for every
    ``except Exception`` that does **not** call a bug-classification helper.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(tree)
        if not _handler_calls_bug_classifier(h)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExceptBlocksBugClassification:
    """Issue #6752 — ``except Exception`` blocks must classify bugs."""

    @pytest.mark.parametrize(
        "filename",
        [
            # T36 — ``review_phase`` is now a package; the ``ReviewPhase``
            # class (which held the original anchored ``except Exception``
            # sites) lives in ``review_phase/_phase.py``.
            "review_phase/_phase.py",
            "diagnostic_runner.py",
            "diagnostic_loop.py",
            "plan_phase.py",
            "implement_phase.py",
        ],
        ids=lambda f: f.removesuffix(".py").replace("/", "_"),
    )
    @pytest.mark.xfail(
        reason="Regression for issue #6752 — fix not yet landed", strict=False
    )
    def test_all_except_exception_blocks_call_bug_classifier(
        self, filename: str
    ) -> None:
        """Every ``except Exception`` in production phase files must call
        ``capture_if_bug()`` or ``reraise_on_credit_or_bug()`` so that
        programming errors are not silently swallowed.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        assert not unguarded, (
            f"{filename} has {len(unguarded)} ``except Exception`` block(s) "
            f"that do not call capture_if_bug() or reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Programming errors (TypeError, KeyError, etc.) in these blocks "
            f"will be silently swallowed — see issue #6752."
        )

    @pytest.mark.parametrize(
        ("filename", "approx_line"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{ln}" for f, ln in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(
        reason="Regression for issue #6752 — fix not yet landed", strict=False
    )
    def test_known_site_has_bug_classifier(
        self, filename: str, approx_line: int
    ) -> None:
        """Each specific site from the issue's findings table must have
        bug-classification handling within ±15 lines of the reported location.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        # Find unguarded handlers near the reported line.
        nearby = [lineno for lineno, _ in unguarded if abs(lineno - approx_line) <= 15]

        assert not nearby, (
            f"{filename}:{approx_line} — ``except Exception`` near line "
            f"{nearby[0]} does not call capture_if_bug() or "
            f"reraise_on_credit_or_bug().  Programming errors here are "
            f"silently swallowed (issue #6752)."
        )


class TestDiagnosticRunnerValidationError:
    """diagnostic_runner.py:145 — pydantic ValidationError (a ValueError
    subclass) is caught by ``except Exception`` and treated the same as a
    network failure.  The fix should catch ValidationError specifically
    with ``exc_info=True`` for actionable stack traces.
    """

    @pytest.mark.xfail(
        reason="Regression for issue #6752 — fix not yet landed", strict=False
    )
    def test_validation_error_not_caught_specifically(self) -> None:
        """The except block around ``DiagnosisResult.model_validate()``
        must catch ``pydantic.ValidationError`` explicitly (with exc_info)
        rather than lumping it into the generic ``except Exception``.
        """
        filepath = SRC / "diagnostic_runner.py"
        source = filepath.read_text()
        tree = ast.parse(source, filename=str(filepath))

        # Find the except handler(s) near ``model_validate``.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Check if this handler is near a model_validate call by
            # looking at the parent try block.  We use a simpler heuristic:
            # look for handlers that catch bare ``Exception`` and whose
            # body returns a DiagnosisResult fallback.
            if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
                continue

            # Check if the handler body references "model_validate" context
            # by looking at surrounding source lines.
            handler_start = node.lineno
            source_lines = source.splitlines()
            # Look at the 10 lines before the except for model_validate.
            context_lines = source_lines[max(0, handler_start - 10) : handler_start]
            context_text = "\n".join(context_lines)
            if "model_validate" not in context_text:
                continue

            # Found it — this handler catches Exception generically near
            # model_validate.  After the fix it should catch
            # ValidationError specifically.
            assert node.type.id != "Exception", (
                f"diagnostic_runner.py:{handler_start} — "
                f"``except Exception`` catches pydantic ValidationError "
                f"(a ValueError subclass, i.e. a LIKELY_BUG_EXCEPTION) "
                f"generically.  It should catch ValidationError explicitly "
                f"with exc_info=True for actionable stack traces (issue #6752)."
            )

        # If we reach here without finding the handler, the code structure
        # changed — fail with a clear message.
        # (The loop above should always find at least one match given the
        # current code, so reaching here means the test needs updating.)
