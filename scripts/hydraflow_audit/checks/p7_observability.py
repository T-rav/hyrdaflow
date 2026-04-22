"""P7 — Observability and repo wiki (ADR-0044)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding

# ---------------------------------------------------------------------------
# Sentry gatekeeper — P7.1, P7.2.
# ---------------------------------------------------------------------------


_BUG_TYPES_RE = re.compile(r"\b_BUG_TYPES\b")


def _find_sentry_module(root: Path) -> Path | None:
    for candidate in (root / "src" / "server.py", root / "src" / "sentry.py"):
        if candidate.exists():
            return candidate
    src = root / "src"
    if not src.is_dir():
        return None
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if "sentry_sdk.init" in text:
            return py
    return None


@register("P7.1")
def _bug_types_tuple(ctx: CheckContext) -> Finding:
    path = _find_sentry_module(ctx.root)
    if path is None:
        return finding("P7.1", Status.FAIL, "no Sentry init site found under src/")
    text = path.read_text(encoding="utf-8", errors="replace")
    if _BUG_TYPES_RE.search(text):
        return finding("P7.1", Status.PASS, f"_BUG_TYPES in {path.name}")
    return finding(
        "P7.1",
        Status.FAIL,
        f"{path.name} does not define a _BUG_TYPES gatekeeper tuple",
    )


@register("P7.2")
def _before_send_uses_filter(ctx: CheckContext) -> Finding:
    path = _find_sentry_module(ctx.root)
    if path is None:
        return finding("P7.2", Status.FAIL, "no Sentry init site found under src/")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "before_send" in text and _BUG_TYPES_RE.search(text):
        return finding("P7.2", Status.PASS)
    return finding(
        "P7.2",
        Status.FAIL,
        "Sentry init site has no before_send wired to _BUG_TYPES",
    )


# ---------------------------------------------------------------------------
# Repo wiki — P7.3 / P7.3a / P7.3b / P7.3c.
# ---------------------------------------------------------------------------


@register("P7.3")
def _repo_wiki_dir(ctx: CheckContext) -> Finding:
    path = ctx.root / "repo_wiki"
    if not path.is_dir():
        return finding(
            "P7.3", Status.FAIL, "repo_wiki/ missing (or project equivalent)"
        )
    return finding("P7.3", Status.PASS)


@register("P7.3a")
def _wiki_three_layer_shape(ctx: CheckContext) -> Finding:
    """Check the three layers exist without prescribing specific filenames.

    Index can be markdown (`index.md`) or JSON (`index.json` / `_manifest.json`).
    Raw sources can be an explicit `_log.jsonl` *or* per-page front-matter /
    filename convention that names the originating issue — either gives a
    traceable audit trail.
    """
    wiki = ctx.root / "repo_wiki"
    if not wiki.is_dir():
        return finding(
            "P7.3a", Status.NA, "repo_wiki/ missing — upstream check covers this"
        )
    has_index = _has_wiki_index(wiki)
    has_pages = _has_wiki_pages(wiki)
    has_raw_trail = _has_wiki_raw_trail(wiki)
    missing: list[str] = []
    if not has_pages:
        missing.append("synthesised wiki pages (per-topic *.md)")
    if not has_index:
        missing.append("index (index.md / index.json / _manifest.json)")
    if not has_raw_trail:
        missing.append("traceable raw source (operation log or page front-matter)")
    if not missing:
        return finding("P7.3a", Status.PASS)
    return finding(
        "P7.3a",
        Status.WARN,
        f"repo_wiki/ missing layers: {', '.join(missing)}",
    )


def _has_wiki_index(wiki: Path) -> bool:
    for name in ("index.md", "index.json", "_manifest.json"):
        if any(wiki.rglob(name)):
            return True
    return False


def _has_wiki_pages(wiki: Path) -> bool:
    """True when at least one topic subdirectory contains per-entry pages."""
    for md in wiki.rglob("*.md"):
        rel = md.relative_to(wiki)
        parts = rel.parts
        if parts[-1] in {"README.md", "index.md"}:
            continue
        if len(parts) >= 2:  # <owner>/<repo>/<topic>/<page>.md or <topic>/<page>.md
            return True
    return False


def _has_wiki_raw_trail(wiki: Path) -> bool:
    """Either an explicit log file, or per-page front-matter naming the source."""
    if any(wiki.rglob("_log.jsonl")) or any(wiki.rglob("_log*.json*")):
        return True
    checked = 0
    for md in wiki.rglob("*.md"):
        if md.name in {"README.md", "index.md"}:
            continue
        # HydraFlow filename convention: `0001-issue-<number>-<slug>.md`.
        if re.match(r"^\d{4}-issue-", md.name):
            return True
        try:
            head = md.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if re.search(
            r"^(issue|source|pr|origin)\s*:", head, re.MULTILINE | re.IGNORECASE
        ):
            return True
        checked += 1
        if checked >= 20:
            break
    return False


_WIKI_OPS_RE = re.compile(r"\b(ingest|query|lint)\b")


@register("P7.3b")
def _wiki_store_operations(ctx: CheckContext) -> Finding:
    store = ctx.root / "src" / "repo_wiki.py"
    if not store.exists():
        return finding("P7.3b", Status.FAIL, "src/repo_wiki.py missing")
    text = store.read_text(encoding="utf-8", errors="replace")
    hits = {op for op in ("ingest", "query", "lint") if re.search(rf"\b{op}\b", text)}
    if hits == {"ingest", "query", "lint"}:
        return finding("P7.3b", Status.PASS)
    missing = sorted({"ingest", "query", "lint"} - hits)
    return finding(
        "P7.3b",
        Status.FAIL,
        f"src/repo_wiki.py missing operations: {', '.join(missing)}",
    )


_INJECT_WIKI_RE = re.compile(r"\b(_inject_repo_wiki|inject_repo_wiki|inject_wiki)\b")


@register("P7.3c")
def _runner_injects_wiki(ctx: CheckContext) -> Finding:
    candidates = [ctx.root / "src" / "base_runner.py", ctx.root / "src" / "runner.py"]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _INJECT_WIKI_RE.search(text):
            return finding("P7.3c", Status.PASS)
    return finding(
        "P7.3c",
        Status.FAIL,
        "no _inject_repo_wiki call in runner modules — wiki not read during agent runs",
    )


# ---------------------------------------------------------------------------
# Logging discipline — P7.4 and P7.5.
# ---------------------------------------------------------------------------


@register("P7.4")
def _no_bare_except(ctx: CheckContext) -> Finding:
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P7.4", Status.NA, "no src/ directory")
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if _is_bare_except_pass(handler):
                        offenders.append(f"{py.relative_to(ctx.root)}:{handler.lineno}")
                        if len(offenders) >= 5:
                            break
            if len(offenders) >= 5:
                break
        if len(offenders) >= 5:
            break
    if not offenders:
        return finding("P7.4", Status.PASS)
    return finding(
        "P7.4",
        Status.WARN,
        f"bare except blocks found: {'; '.join(offenders)}",
    )


def _is_bare_except_pass(handler: ast.ExceptHandler) -> bool:
    if handler.type is not None:
        return False
    return len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)


@register("P7.5")
def _logger_error_has_format(ctx: CheckContext) -> Finding:
    """Use AST so matches inside string literals and comments don't count."""
    src = ctx.root / "src"
    if not src.is_dir():
        return finding("P7.5", Status.NA, "no src/ directory")
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_bare_value_logger_error(node):
                continue
            offenders.append(f"{py.relative_to(ctx.root)}:{node.lineno}")
            if len(offenders) >= 5:
                break
        if len(offenders) >= 5:
            break
    if not offenders:
        return finding("P7.5", Status.PASS)
    return finding(
        "P7.5",
        Status.WARN,
        f"logger.error(value) without format string: {'; '.join(offenders)}",
    )


def _is_bare_value_logger_error(node: ast.Call) -> bool:
    """True for `logger.error(some_variable)` — no format string, no args."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "error":
        return False
    if not isinstance(func.value, ast.Name) or func.value.id != "logger":
        return False
    if len(node.args) != 1 or node.keywords:
        return False
    return isinstance(node.args[0], ast.Name)


# ---------------------------------------------------------------------------
# Self-instrumentation — P7.6, P7.7.
# ---------------------------------------------------------------------------


@register("P7.6")
def _audit_self_instrumented(ctx: CheckContext) -> Finding:
    """The audit/init tooling must follow P7.1/P7.2 on itself."""
    obs = ctx.root / "scripts" / "hydraflow_audit" / "observability.py"
    if not obs.exists():
        return finding(
            "P7.6",
            Status.FAIL,
            "scripts/hydraflow_audit/observability.py missing — tooling not self-instrumented",
        )
    text = obs.read_text(encoding="utf-8", errors="replace")
    if "_BUG_TYPES" in text and "before_send" in text:
        return finding("P7.6", Status.PASS)
    return finding(
        "P7.6",
        Status.FAIL,
        "audit observability.py does not wire _BUG_TYPES through before_send",
    )


@register("P7.7")
def _observability_behind_port(ctx: CheckContext) -> Finding:
    ports = ctx.root / "src" / "ports.py"
    if not ports.exists():
        return finding("P7.7", Status.FAIL, "src/ports.py missing")
    text = ports.read_text(encoding="utf-8", errors="replace")
    if re.search(r"class\s+(ObservabilityPort|TracingPort|MetricsPort)\b", text):
        return finding("P7.7", Status.PASS)
    return finding(
        "P7.7",
        Status.WARN,
        "no ObservabilityPort/TracingPort/MetricsPort in ports.py — backend swap requires call-site edits",
    )
