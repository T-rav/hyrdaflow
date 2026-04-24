"""Wiki-vs-code drift detection — P4 of the wiki-evolution audit.

First-cut detector is deterministic and cheap: for every *active*
tracked-layout entry under ``{tracked_root}/{repo_slug}/{topic}/``,
extract ``src/...`` citations from its body and verify each cited
file still exists under ``repo_root``.  Missing files = drift.

Symbol-level drift (cited class/function removed while file remains)
is intentionally out of scope for this pass — adding an LLM
validator on top of this skeleton is the Phase 2 extension.

The RepoWikiLoop calls ``detect_drift`` on a weekly cadence and can
use the returned findings to mark entries stale with a
``stale_reason: drift_detected <files>`` note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Same shape as src/adr_index.py:_SOURCE_FILE_CITATION_RE — matches
# `src/some/path.py:Symbol` citations inside backticks.
_SOURCE_FILE_CITATION_RE = re.compile(r"`(src/[^`:\s]+\.py):[A-Za-z_]\w*`")


@dataclass(frozen=True)
class DriftFinding:
    """One drifted wiki entry with the cited files that no longer exist."""

    entry_path: Path
    entry_id: str
    topic: str
    missing_files: frozenset[str]


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
            cited = set(_SOURCE_FILE_CITATION_RE.findall(body))
            if not cited:
                continue

            missing = {c for c in cited if not (repo_root / c).is_file()}
            if not missing:
                continue

            result.findings.append(
                DriftFinding(
                    entry_path=entry_path,
                    entry_id=fields.get("id", ""),
                    topic=topic_dir.name,
                    missing_files=frozenset(missing),
                )
            )

    return result
