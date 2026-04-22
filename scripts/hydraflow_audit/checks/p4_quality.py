"""P4 — Quality Gates (ADR-0044).

Quality gates are about the target being *present* and composed correctly.
We don't execute `make quality` from the audit — that's CI's job; running
the whole suite as part of a conformance check would turn every audit into
a multi-minute wait. Presence of the target + config shape is the
conformance signal.
"""

from __future__ import annotations

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding
from .p3_testing import _has_make_target, _load_pyproject


def _target_check(ctx: CheckContext, check_id: str, name: str) -> Finding:
    if _has_make_target(ctx.root, name):
        return finding(check_id, Status.PASS)
    return finding(check_id, Status.FAIL, f"Makefile has no `{name}` target")


@register("P4.1")
def _lint_check(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.1", "lint-check")


@register("P4.2")
def _typecheck(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.2", "typecheck")


@register("P4.3")
def _security(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.3", "security")


@register("P4.4")
def _test_target(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.4", "test")


@register("P4.5")
def _quality_lite(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.5", "quality-lite")


@register("P4.6")
def _quality(ctx: CheckContext) -> Finding:
    return _target_check(ctx, "P4.6", "quality")


_REQUIRED_TOOL_SECTIONS = ("ruff", "pyright", "bandit", "pytest")


@register("P4.7")
def _tool_configs_in_pyproject(ctx: CheckContext) -> Finding:
    data = _load_pyproject(ctx.root)
    if data is None:
        return finding("P4.7", Status.FAIL, "pyproject.toml missing")
    tool = data.get("tool", {})
    missing = [name for name in _REQUIRED_TOOL_SECTIONS if name not in tool]
    if not missing:
        return finding("P4.7", Status.PASS)
    return finding(
        "P4.7",
        Status.FAIL,
        f"pyproject.toml missing [tool.{', '.join(missing)}] section(s)",
    )
