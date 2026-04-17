"""Regression test for issue #6359.

EpicManager uses ``logger.exception`` for transient API failures in five
locations. These are operational errors (network, rate-limit, transient
GitHub 5xx) — not code bugs — and should use ``logger.warning`` so they
do NOT fire Sentry alerts.

The test parses ``src/epic.py`` via the AST and asserts that the five
known catch-and-continue blocks log at WARNING level (not EXCEPTION /
ERROR).
"""

from __future__ import annotations

import ast
from pathlib import Path

EPIC_PY = Path(__file__).resolve().parents[2] / "src" / "epic.py"

# The five logger.exception call sites from the issue, identified by
# the unique substring in the log message so the test survives minor
# line-number drift.
EXPECTED_WARNING_MESSAGES: set[str] = {
    "Failed to get progress for epic",
    "Failed to get detail for epic",
    "Failed to refresh cache for epic",
    "Failed to post stale warning for epic",
    "Failed to publish stale alert for epic",
}


def _find_logger_calls(tree: ast.Module) -> list[tuple[str, int, str]]:
    """Return (method_name, lineno, first_string_arg) for every ``logger.*`` call."""
    results: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `logger.<method>(...)`.
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "logger"):
            continue
        method = func.attr  # e.g. "exception", "warning", "error"
        # Extract the first positional string argument (the log message).
        msg = ""
        if node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                msg = first.value
        results.append((method, node.lineno, msg))
    return results


class TestEpicTransientLoggingLevel:
    """All five catch-and-continue sites must use logger.warning, not logger.exception."""

    def test_no_logger_exception_for_transient_failures(self) -> None:
        source = EPIC_PY.read_text()
        tree = ast.parse(source, filename=str(EPIC_PY))
        calls = _find_logger_calls(tree)

        violations: list[str] = []
        matched_messages: set[str] = set()

        for method, lineno, msg in calls:
            # Check if this call matches one of the known transient-failure sites.
            for expected_prefix in EXPECTED_WARNING_MESSAGES:
                if expected_prefix in msg:
                    matched_messages.add(expected_prefix)
                    if method != "warning":
                        violations.append(
                            f"epic.py:{lineno} uses logger.{method}() "
                            f"for transient failure ({msg!r}); "
                            f"should be logger.warning(..., exc_info=True)"
                        )

        # Ensure we actually found all five sites (guard against message changes).
        missing = EXPECTED_WARNING_MESSAGES - matched_messages
        assert not missing, (
            f"Could not locate these expected log messages in epic.py "
            f"(test may need updating): {missing}"
        )

        # The actual assertion: none of the transient-failure sites should use
        # logger.exception (or logger.error).
        assert not violations, (
            "Transient API failure handlers use wrong log level "
            "(should be logger.warning, not logger.exception):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
