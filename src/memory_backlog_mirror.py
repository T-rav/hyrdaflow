"""Pure helpers for `MemoryBacklogLoop` (no IO except file read/write).

See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §6
and `docs/wiki/memory-feedback/README.md` for the frontmatter schema and
status state-machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml

logger = logging.getLogger("hydraflow.memory_backlog_mirror")

Status = Literal["pending", "issue-open", "promoted", "wontfix"]
_VALID_STATUS: frozenset[str] = frozenset(
    {"pending", "issue-open", "promoted", "wontfix"}
)


@dataclass(frozen=True)
class MirrorEntry:
    slug: str
    path: Path
    source: str
    name: str
    description: str
    status: Status
    issue: int | None
    promoted_in: str | None
    wontfix_reason: str | None
    body: str


def dedup_key_for(slug: str) -> str:
    return f"memory_backlog:{slug}"


def load_mirror_entry(path: Path) -> MirrorEntry:
    text = path.read_text()
    if not text.startswith("---\n"):
        msg = f"missing frontmatter in {path}"
        raise ValueError(msg)
    end = text.find("\n---", 4)
    if end == -1:
        msg = f"unterminated frontmatter in {path}"
        raise ValueError(msg)
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        # A malformed entry is data corruption, not a loop bug — surface as
        # ValueError so callers (pending_entries) can skip it uniformly.
        msg = f"malformed frontmatter in {path}: {exc}"
        raise ValueError(msg) from exc
    body = text[end + 4 :].lstrip("\n").rstrip() + "\n"
    status = front.get("status", "pending")
    if status not in _VALID_STATUS:
        msg = f"invalid status {status!r} in {path}"
        raise ValueError(msg)
    return MirrorEntry(
        slug=path.stem,
        path=path,
        source=str(front.get("source", "")),
        name=str(front.get("name", path.stem)),
        description=str(front.get("description", "")),
        status=cast(Status, status),
        issue=front.get("issue"),
        promoted_in=front.get("promoted_in"),
        wontfix_reason=front.get("wontfix_reason"),
        body=body,
    )


def pending_entries(mirror_dir: Path) -> list[MirrorEntry]:
    entries: list[MirrorEntry] = []
    for path in sorted(mirror_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            entry = load_mirror_entry(path)
        except ValueError as exc:
            logger.warning("Skipping malformed mirror entry %s: %s", path, exc)
            continue
        if entry.status == "pending":
            entries.append(entry)
    return entries


def render_issue_body(entry: MirrorEntry, *, repo_relative_path: str) -> str:
    return (
        f"# {entry.name}\n\n"
        f"{entry.description}\n\n"
        f"## Source memory\n\n"
        f"- Mirror: [`{repo_relative_path}`]({repo_relative_path})\n"
        f"- Originally captured as `{entry.source}`\n\n"
        f"## Rule (from memory)\n\n"
        f"{entry.body}\n"
        f"---\n"
        f"_Filed by `MemoryBacklogLoop` (ADR-0057) — promote by enforcing "
        f"the rule (test/fixture/lint/loop), then close this issue with "
        f"`promoted_in: <PR>` in the mirror frontmatter._\n"
    )


def update_status(
    path: Path,
    *,
    status: Status,
    issue: int | None = None,
    promoted_in: str | None = None,
    wontfix_reason: str | None = None,
) -> None:
    """Re-write only the frontmatter status fields. Preserves body verbatim."""
    text = path.read_text()
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1:
        msg = f"can't update status — bad frontmatter in {path}"
        raise ValueError(msg)
    front = yaml.safe_load(text[4:end]) or {}
    front["status"] = status
    if issue is not None:
        front["issue"] = issue
    if promoted_in is not None:
        front["promoted_in"] = promoted_in
    if wontfix_reason is not None:
        front["wontfix_reason"] = wontfix_reason
    body = text[end + 4 :].lstrip("\n")
    front_yaml = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    path.write_text(f"---\n{front_yaml}\n---\n\n{body}")
