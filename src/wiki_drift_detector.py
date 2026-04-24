"""Wiki-vs-code drift detection.

Two layers:

* **Deterministic (P4 + B3).** ``detect_drift`` walks active tracked
  entries and flags citations whose ``src/...`` files or symbols no
  longer exist. Cheap, no LLM.
* **Semantic (E2).** ``scan_semantic_drift`` takes aged entries whose
  citations still resolve and asks an LLM "does this entry's claim
  still hold given the cited files' current content?". Catches
  "wiki says haiku / code now uses gemini" cases that grep cannot.

The RepoWikiLoop wires both. B2's ``apply_drift_markers`` flips
deterministic findings to ``status: stale``; the semantic layer
returns its own finding type so operators can review before acting.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.wiki_drift_detector")

# Matches `src/some/path.py:Symbol` citations inside backticks and
# captures (file, symbol). Shares shape with
# src/adr_index.py:_SOURCE_FILE_CITATION_RE.
_SOURCE_PAIR_CITATION_RE = re.compile(r"`(src/[^`:\s]+\.py):([A-Za-z_]\w*)`")


@dataclass(frozen=True)
class DriftFinding:
    """One drifted wiki entry.

    ``missing_files`` lists cited ``src/...py`` files that no longer
    exist under ``repo_root``.  ``missing_symbols`` lists
    ``src/path.py:Symbol`` citations where the file exists but the
    symbol (``class Symbol`` / ``def Symbol`` / ``async def Symbol``)
    is not defined in it.
    """

    entry_path: Path
    entry_id: str
    topic: str
    missing_files: frozenset[str]
    missing_symbols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SemanticDriftFinding:
    """One entry the LLM flagged as contradicted by current code.

    Distinct from ``DriftFinding`` so operators can treat the two
    signals differently — deterministic findings auto-mark stale
    (no false-positive risk), semantic findings may warrant review
    first.
    """

    entry_path: Path
    entry_id: str
    topic: str
    verdict: str  # "contradicted" (valid / unknown omitted from the findings list)
    reason: str


# ``ask_llm`` parameter contract (kept typed as Any to avoid import
# churn under `from __future__ import annotations`):
#
#   async def ask_llm(prompt: str) -> str | None
#
# Must be awaitable; returning None signals an LLM failure that the
# scanner should treat as "unknown" — no finding, no stale-mark.
# Production wires WikiCompiler._call_model; tests inject a coroutine.


@dataclass
class DriftResult:
    findings: list[DriftFinding] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal parser of the leading ``---`` YAML-ish block.

    Mirrors ``src/repo_wiki.py:_split_tracked_entry`` — kept separate
    to avoid importing a heavy module.
    """
    if not text.startswith("---\n"):
        return {}
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _entry_body(text: str) -> str:
    """Return the body after the leading frontmatter (or the whole
    text when no frontmatter is present)."""
    if not text.startswith("---\n"):
        return text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return text
    return text[end + len("\n---\n") :]


def _file_defines_symbol(file_path: Path, symbol: str) -> bool:
    """Grep *file_path* for a top-level or indented definition of *symbol*.

    Matches ``class Symbol`` / ``def Symbol`` / ``async def Symbol``
    with optional leading whitespace (so methods inside classes count)
    followed by ``(``, ``:``, ``[``, or whitespace — whatever Python
    syntax permits. Module-level assignments (constants / aliases) are
    caught by the trailing ``=`` / ``:`` alternative.

    False positives on comments/strings would be rare and one-directional
    (under-flagging drift rather than over-flagging), so we keep it
    regex-simple rather than AST-parsing.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    pattern = re.compile(
        rf"^\s*(?:class|def|async\s+def)\s+{re.escape(symbol)}\b",
        re.MULTILINE,
    )
    if pattern.search(text):
        return True
    # Module-level constants/aliases: `FOO = ...` or `FOO: Type = ...`.
    assign_pattern = re.compile(
        rf"^{re.escape(symbol)}\s*(?::\s*[^=\n]+)?\s*=",
        re.MULTILINE,
    )
    return bool(assign_pattern.search(text))


def detect_drift(
    *,
    tracked_root: Path,
    repo_root: Path,
    repo_slug: str,
) -> DriftResult:
    """Scan tracked-layout active entries and flag those citing missing files.

    Parameters
    ----------
    tracked_root:
        Root where the per-entry layout lives (typically
        ``{repo_root}/repo_wiki``).
    repo_root:
        Working tree root used to resolve ``src/...`` citations.
    repo_slug:
        ``owner/repo`` slug scoping the lookup.
    """
    result = DriftResult()
    repo_dir = tracked_root / repo_slug
    if not repo_dir.is_dir():
        return result

    for topic_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        for entry_path in sorted(topic_dir.glob("*.md")):
            try:
                text = entry_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            fields = _parse_frontmatter(text)
            if fields.get("status", "active") != "active":
                continue

            body = _entry_body(text)
            pairs = set(_SOURCE_PAIR_CITATION_RE.findall(body))
            if not pairs:
                continue

            missing_files: set[str] = set()
            missing_symbols: set[str] = set()
            for file_ref, symbol in pairs:
                file_path = repo_root / file_ref
                if not file_path.is_file():
                    missing_files.add(file_ref)
                    continue
                if not _file_defines_symbol(file_path, symbol):
                    missing_symbols.add(f"{file_ref}:{symbol}")

            if not missing_files and not missing_symbols:
                continue

            result.findings.append(
                DriftFinding(
                    entry_path=entry_path,
                    entry_id=fields.get("id", ""),
                    topic=topic_dir.name,
                    missing_files=frozenset(missing_files),
                    missing_symbols=frozenset(missing_symbols),
                )
            )

    return result


def apply_drift_markers(findings: list[DriftFinding]) -> int:
    """Flip each flagged entry's ``status: active`` → ``stale`` with a
    ``stale_reason: drift_detected: <files>`` annotation.

    Only mutates files whose frontmatter still says ``status: active`` —
    idempotent on second call, safe against entries that a prior lint
    pass already marked stale.

    Returns the count of entries actually updated. Never raises on
    per-file read / write failures; logs and continues.
    """
    updated = 0
    for finding in findings:
        try:
            text = finding.entry_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning(
                "drift automark: cannot read %s; skipping", finding.entry_path
            )
            continue
        fields = _parse_frontmatter(text)
        if not fields or fields.get("status", "active") != "active":
            continue
        body = _entry_body(text)
        parts = sorted(finding.missing_files) + sorted(finding.missing_symbols)
        reason = "drift_detected: " + ",".join(parts)
        fields["status"] = "stale"
        fields["stale_reason"] = reason
        rebuilt = (
            "---\n"
            + "\n".join(f"{k}: {v}" for k, v in fields.items())
            + "\n---\n"
            + body
        )
        try:
            finding.entry_path.write_text(rebuilt, encoding="utf-8")
        except OSError:
            logger.warning(
                "drift automark: cannot write %s; skipping", finding.entry_path
            )
            continue
        updated += 1
    return updated


# ---------------------------------------------------------------------------
# E2 — semantic drift layer
# ---------------------------------------------------------------------------

_SEMANTIC_PROMPT = """You are auditing a wiki entry for staleness.

The entry was written when the code looked a certain way. Below you
have the entry body and the current content of each file it cites.
Decide whether the entry's CLAIM still holds given the current code.

Reply with EXACTLY two lines in this shape:

VERDICT: valid | contradicted | unknown
REASON: <one sentence explaining the verdict>

Use "contradicted" ONLY when the current code clearly refutes the
entry's specific claim (e.g. entry says default is X, code shows
default is Y). Use "unknown" when the citation is ambiguous or you
can't tell. Default to "valid" when the entry's advice still reads
as consistent with the cited code.

## Entry body

{body}

## Cited files (current content)

{sources}
"""

_VERDICT_RE = re.compile(
    r"^VERDICT:\s*(valid|contradicted|unknown)\b", re.MULTILINE | re.IGNORECASE
)
_REASON_RE = re.compile(r"^REASON:\s*(.+?)\s*$", re.MULTILINE)
_SOURCE_SNIPPET_MAX_BYTES = 4_000


def _entry_created_at(fields: dict[str, str]) -> datetime | None:
    raw = fields.get("created_at") or ""
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _build_sources_block(repo_root: Path, pairs: set[tuple[str, str]]) -> str | None:
    """Render the cited files' current content for the LLM prompt.

    Returns ``None`` when every citation's file is missing — in that
    case the deterministic detector already flagged the entry, so we
    skip the semantic pass.
    """
    chunks: list[str] = []
    for file_ref, symbol in sorted(pairs):
        path = repo_root / file_ref
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > _SOURCE_SNIPPET_MAX_BYTES:
            text = text[:_SOURCE_SNIPPET_MAX_BYTES] + "\n... [truncated]"
        chunks.append(f"### {file_ref}:{symbol}\n\n```\n{text}\n```\n")
    if not chunks:
        return None
    return "\n".join(chunks)


def _parse_semantic_response(raw: str | None) -> tuple[str, str]:
    """Extract (verdict, reason) from the LLM reply. Garbage → ("unknown", "")."""
    if not raw:
        return "unknown", ""
    verdict_match = _VERDICT_RE.search(raw)
    reason_match = _REASON_RE.search(raw)
    verdict = verdict_match.group(1).lower() if verdict_match else "unknown"
    reason = reason_match.group(1).strip() if reason_match else ""
    return verdict, reason


async def detect_semantic_drift_for_entry(  # noqa: PLR0911
    *,
    entry_path: Path,
    repo_root: Path,
    ask_llm: Any,
) -> SemanticDriftFinding | None:
    """Ask the LLM whether an entry's claim still matches the cited code.

    Returns a finding only when the verdict is ``contradicted``. Valid
    and unknown verdicts return ``None`` so callers treat them as
    no-action signals.
    """
    try:
        text = entry_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    fields = _parse_frontmatter(text)
    if not fields or fields.get("status", "active") != "active":
        return None

    body = _entry_body(text)
    pairs = set(_SOURCE_PAIR_CITATION_RE.findall(body))
    if not pairs:
        return None

    sources = _build_sources_block(repo_root, pairs)
    if sources is None:
        return None

    prompt = _SEMANTIC_PROMPT.format(body=body.strip(), sources=sources)
    try:
        raw = await ask_llm(prompt)
    except Exception:  # noqa: BLE001
        logger.warning(
            "semantic drift: ask_llm raised on %s; skipping", entry_path, exc_info=True
        )
        return None

    verdict, reason = _parse_semantic_response(raw)
    if verdict != "contradicted":
        return None
    return SemanticDriftFinding(
        entry_path=entry_path,
        entry_id=fields.get("id", ""),
        topic=entry_path.parent.name,
        verdict=verdict,
        reason=reason or "(no reason given)",
    )


async def scan_semantic_drift(
    *,
    tracked_root: Path,
    repo_root: Path,
    repo_slug: str,
    ask_llm: Any,
    min_age_days: int = 30,
    max_entries_per_tick: int = 10,
) -> list[SemanticDriftFinding]:
    """Sweep a repo's tracked entries for semantic drift.

    ``min_age_days`` gates which entries are re-checked — newer ones
    are likely still accurate and aren't worth an LLM call.
    ``max_entries_per_tick`` caps cost by limiting how many entries
    are checked per invocation; the next tick will cover the rest.
    """
    findings: list[SemanticDriftFinding] = []
    repo_dir = tracked_root / repo_slug
    if not repo_dir.is_dir():
        return findings

    now = datetime.now(UTC)
    checked = 0
    for topic_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        for entry_path in sorted(topic_dir.glob("*.md")):
            if checked >= max_entries_per_tick:
                return findings
            try:
                text = entry_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fields = _parse_frontmatter(text)
            if not fields or fields.get("status", "active") != "active":
                continue
            created = _entry_created_at(fields)
            if created is None or (now - created).days < min_age_days:
                continue

            finding = await detect_semantic_drift_for_entry(
                entry_path=entry_path,
                repo_root=repo_root,
                ask_llm=ask_llm,
            )
            checked += 1
            if finding is not None:
                findings.append(finding)
    return findings
