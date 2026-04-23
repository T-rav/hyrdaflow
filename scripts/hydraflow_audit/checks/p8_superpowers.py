"""P8 — Superpowers / skills integration (ADR-0044)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding


@register("P8.1")
def _claude_dir_exists(ctx: CheckContext) -> Finding:
    if (ctx.root / ".claude").is_dir():
        return finding("P8.1", Status.PASS)
    return finding("P8.1", Status.FAIL, ".claude/ missing")


def _settings_path(root: Path) -> Path | None:
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        if path.exists():
            return path
    return None


@register("P8.2")
def _claude_settings(ctx: CheckContext) -> Finding:
    path = _settings_path(ctx.root)
    if path is None:
        return finding(
            "P8.2",
            Status.FAIL,
            ".claude/settings.json or settings.local.json missing",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return finding("P8.2", Status.FAIL, f"{path.name} is not valid JSON")
    if not isinstance(data, dict):
        return finding("P8.2", Status.FAIL, f"{path.name} is not a JSON object")
    return finding("P8.2", Status.PASS, f"settings at {path.name}")


def _hook_kinds_configured(root: Path) -> set[str]:
    path = _settings_path(root)
    if path is None:
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return set()
    return {k for k, v in hooks.items() if isinstance(v, list) and v}


@register("P8.3")
def _pre_tool_use_hook(ctx: CheckContext) -> Finding:
    kinds = _hook_kinds_configured(ctx.root)
    if "PreToolUse" in kinds:
        return finding("P8.3", Status.PASS)
    return finding(
        "P8.3",
        Status.FAIL,
        "no PreToolUse hook configured in .claude/settings.json",
    )


_CORE_SKILLS = (
    "brainstorming",
    "test-driven-development",
    "systematic-debugging",
    "writing-plans",
    "verification-before-completion",
    "requesting-code-review",
)


@register("P8.4")
def _claude_md_references_skills(ctx: CheckContext) -> Finding:
    claude = ctx.root / "CLAUDE.md"
    if not claude.exists():
        return finding("P8.4", Status.FAIL, "CLAUDE.md missing")
    text = claude.read_text(encoding="utf-8", errors="replace")
    missing = [name for name in _CORE_SKILLS if name not in text]
    if not missing:
        return finding("P8.4", Status.PASS)
    return finding(
        "P8.4",
        Status.FAIL,
        f"CLAUDE.md does not name core skills: {', '.join(missing)}",
    )


_REQUIRED_HOOK_KINDS = {"PreToolUse", "PostToolUse", "Stop"}


@register("P8.5")
def _three_hook_kinds(ctx: CheckContext) -> Finding:
    kinds = _hook_kinds_configured(ctx.root)
    missing = _REQUIRED_HOOK_KINDS - kinds
    if not missing:
        return finding("P8.5", Status.PASS)
    return finding(
        "P8.5",
        Status.FAIL,
        f"missing hook kind(s): {', '.join(sorted(missing))}",
    )


_TRACE_WRITE_RE = re.compile(
    r"subprocess.*trace|trace.*subprocess|trace_collector|run-\d+", re.IGNORECASE
)


@register("P8.6")
def _trace_collector(ctx: CheckContext) -> Finding:
    candidates = [
        ctx.root / "src" / "trace_collector.py",
        ctx.root / "src" / "tracing.py",
    ]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _TRACE_WRITE_RE.search(text):
            return finding("P8.6", Status.PASS, f"trace writer: {path.name}")
    return finding(
        "P8.6",
        Status.FAIL,
        "no trace collector module found — session retros have no subprocess traces to mine",
    )
