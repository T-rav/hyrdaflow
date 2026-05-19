"""Back-compat re-exports for the ``review_phase`` package.

The original ``src/review_phase.py`` (3702 lines) was split into this
package per T36 (M2) for file-size discipline. All existing imports
continue to work:

    from review_phase import ReviewPhase            # still works
    from review_phase import PreReviewContext       # still works
    from review_phase import _is_meaningful_verdict # still works
    from review_phase import _emit_advisor_loop_metric, _veto_retries_total
    # ... etc.

External-module symbols that tests monkeypatch via ``patch("review_phase.X")``
are also re-exported here so the patches take effect — see the
``# Re-exports for unittest.mock.patch back-compat`` block below.

Layout:
  * ``_common.py``  — module-level constants, regex patterns, metric
    instruments, dataclasses (``ReviewGuardContext``, ``PreReviewContext``),
    standalone helper functions (``_is_meaningful_verdict``,
    ``_run_fallback_ingest_review``, ``_emit_advisor_loop_metric``,
    ``_detect_self_modification_context``).
  * ``_phase.py``   — the ``ReviewPhase`` class.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-exports for ``unittest.mock.patch`` back-compat.
#
# Tests historically patch ``review_phase.analyze_patterns`` and
# ``review_phase.record_harness_failure`` to intercept calls inside
# ``ReviewPhase``. Those names are imported into ``_phase`` (where the
# actual call sites live) — so ``patch("review_phase.<name>")`` would
# replace the attribute *here* but leave the local binding in ``_phase``
# unaffected, breaking the tests.
#
# We mirror those patches by also patching the same name on ``_phase``
# inside a wrapper that tests can target with the legacy
# ``review_phase.<name>`` path. The simplest version: just re-export the
# names so the attribute exists on the package, and document that
# patch sites *should* prefer ``review_phase._phase.<name>``. To keep
# strict back-compat without forcing test edits, we install lightweight
# shims that delegate to ``_phase`` so ``patch`` flowing through here
# also lands in ``_phase``.
# ---------------------------------------------------------------------------
from phase_utils import record_harness_failure  # noqa: E402
from review_insights import analyze_patterns  # noqa: E402

from . import _phase as _phase_module  # noqa: E402

# ---------------------------------------------------------------------------
# Public-surface re-exports.
# ---------------------------------------------------------------------------
from ._common import (
    _NON_VERDICT_SUMMARY_MARKERS,
    _SELF_MOD_SYNTHESIS_PATTERNS,
    PreReviewContext,
    ReviewGuardContext,
    _AdvisorRole,
    _detect_self_modification_context,
    _emit_advisor_loop_metric,
    _is_meaningful_verdict,
    _run_fallback_ingest_review,
    _veto_exhausted_total,
    _veto_recovered_total,
    _veto_retries_total,
    logger,
)
from ._phase import ReviewPhase


def __getattr__(name: str):
    """Forward attribute access to ``_phase`` for symbols that live there.

    This covers patch sites we don't know about up front while keeping
    the explicit re-exports above as the documented public surface.
    """
    if hasattr(_phase_module, name):
        return getattr(_phase_module, name)
    raise AttributeError(f"module 'review_phase' has no attribute {name!r}")


__all__ = [
    "PreReviewContext",
    "ReviewGuardContext",
    "ReviewPhase",
    "_AdvisorRole",
    "_NON_VERDICT_SUMMARY_MARKERS",
    "_SELF_MOD_SYNTHESIS_PATTERNS",
    "_detect_self_modification_context",
    "_emit_advisor_loop_metric",
    "_is_meaningful_verdict",
    "_run_fallback_ingest_review",
    "_veto_exhausted_total",
    "_veto_recovered_total",
    "_veto_retries_total",
    "analyze_patterns",
    "logger",
    "record_harness_failure",
]
