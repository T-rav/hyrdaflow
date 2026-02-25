"""Local markdown issue tracking for prep workflows.

Issues are stored as ``.hydraflow/prep/*.md`` files. A file is considered done
when it contains the marker ``<!-- status: done -->``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_DONE_MARKER = "<!-- status: done -->"
_RUN_ID_ENV = "HYDRAFLOW_PREP_RUN_ID"


@dataclass(frozen=True)
class LocalPrepIssue:
    """A local prep issue loaded from a markdown file."""

    path: Path
    title: str
    body: str


def ensure_pre_dirs(data_root: Path) -> tuple[Path, Path]:
    """Create and return ``(<data_root>/prep, <data_root>/prep/runs/<run-id>)``."""
    pre_dir = data_root / "prep"
    run_id = os.environ.get(_RUN_ID_ENV) or datetime.now(tz=UTC).strftime(
        "%Y%m%d-%H%M%S-%f"
    )
    runs_dir = pre_dir / "runs" / run_id
    pre_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    return pre_dir, runs_dir


def _parse_title(path: Path, body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.name


def load_open_issues(data_root: Path) -> list[LocalPrepIssue]:
    """Load open issues from ``<data_root>/prep/*.md``."""
    pre_dir = data_root / "prep"
    if not pre_dir.is_dir():
        return []

    issues: list[LocalPrepIssue] = []
    for path in sorted(pre_dir.glob("*.md")):
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _DONE_MARKER in body:
            continue
        issues.append(
            LocalPrepIssue(path=path, title=_parse_title(path, body), body=body)
        )
    return issues


def mark_done(issue: LocalPrepIssue) -> None:
    """Mark an issue file as done."""
    try:
        body = issue.path.read_text(encoding="utf-8")
    except OSError:
        return
    if _DONE_MARKER in body:
        return
    timestamp = datetime.now(tz=UTC).isoformat()
    issue.path.write_text(
        f"{body.rstrip()}\n\n{_DONE_MARKER}\n<!-- completed-at: {timestamp} -->\n",
        encoding="utf-8",
    )


def write_run_log(data_root: Path, *, title: str, lines: list[str]) -> Path:
    """Write a markdown run log under ``<data_root>/prep/runs/<run-id>``."""
    _, runs_dir = ensure_pre_dirs(data_root)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    path = runs_dir / f"{ts}-prep-run.md"
    body = "\n".join(lines)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return path


def upsert_issue(
    data_root: Path,
    *,
    filename: str,
    title: str,
    body_lines: list[str],
) -> LocalPrepIssue:
    """Create or update a local `.hydraflow/prep` markdown issue file."""
    pre_dir, _ = ensure_pre_dirs(data_root)
    path = pre_dir / filename
    body = "\n".join([f"# {title}", "", *body_lines, ""])
    path.write_text(body, encoding="utf-8")
    return LocalPrepIssue(path=path, title=title, body=body)
