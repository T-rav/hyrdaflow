"""Log ingestion pipeline: parser, pattern detection, memory filing, rotation handling."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.log_ingestion")

# ---------------------------------------------------------------------------
# Part 1: Structured Log Parser (bead: 9uc)
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    """A single structured JSON log entry emitted by JSONFormatter."""

    ts: str
    level: str
    msg: str
    logger_name: str = Field(alias="logger")
    exception: str | None = None
    issue: int | None = None
    worker: int | None = None
    pr: int | None = None
    phase: str | None = None
    repo: str | None = None
    session: str | None = None

    model_config = {"populate_by_name": True}


def fingerprint_message(msg: str) -> str:
    """Reduce a log message to a stable template for grouping.

    Strips variable parts:
    - Numbers → ``<N>``
    - Quoted strings → ``<S>``
    - Hex hashes (8+ chars) → ``<H>``
    - Unix-style paths → ``<P>``
    """
    result = re.sub(r"\b\d+\b", "<N>", msg)
    result = re.sub(r"'[^']*'", "<S>", result)
    result = re.sub(r'"[^"]*"', "<S>", result)
    result = re.sub(r"\b[0-9a-f]{8,}\b", "<H>", result)
    result = re.sub(r"/[\w/.+-]+", "<P>", result)
    return result.strip()


def parse_log_file(path: Path, *, since: datetime | None = None) -> list[LogEntry]:
    """Parse a JSON log file, returning entries since the given timestamp.

    Malformed lines are silently skipped.  If the file does not exist,
    an empty list is returned.
    """
    if not path.exists():
        return []
    entries: list[LogEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    since_iso = since.isoformat() if since else None
    for line in text.strip().splitlines():
        try:
            data = json.loads(line)
            entry = LogEntry.model_validate(data)
            if since_iso and entry.ts < since_iso:
                continue
            entries.append(entry)
        except Exception:  # noqa: BLE001
            continue  # malformed lines skipped
    return entries


# ---------------------------------------------------------------------------
# Part 5 / Part 7: Log Rotation Awareness (bead: 3rz)
# ---------------------------------------------------------------------------


def parse_log_files(
    log_dir: Path,
    *,
    since: datetime | None = None,
    max_backups: int = 2,
) -> list[LogEntry]:
    """Parse the main log file plus recent backups.

    Reads backup files oldest-first, then the main file, deduplicates by
    timestamp, and returns entries sorted ascending by ``ts``.
    """
    seen_keys: set[tuple[str, str, str]] = set()
    entries: list[LogEntry] = []

    # Parse backups oldest-first
    for i in range(max_backups, 0, -1):
        backup = log_dir / f"server.log.{i}"
        if backup.exists():
            for entry in parse_log_file(backup, since=since):
                key = (entry.ts, entry.level, entry.msg)
                if key not in seen_keys:
                    seen_keys.add(key)
                    entries.append(entry)

    # Parse main log
    main_log = log_dir / "server.log"
    if main_log.exists():
        for entry in parse_log_file(main_log, since=since):
            key = (entry.ts, entry.level, entry.msg)
            if key not in seen_keys:
                seen_keys.add(key)
                entries.append(entry)

    entries.sort(key=lambda e: e.ts)
    return entries


# ---------------------------------------------------------------------------
# Part 2: Log Pattern Detector (bead: k7x)
# ---------------------------------------------------------------------------


class LogPattern(BaseModel):
    """A recurring log message template detected above the count threshold."""

    fingerprint: str
    level: str
    source_module: str
    count: int
    sample_messages: list[str]
    sample_issues: list[int]
    first_seen: str
    last_seen: str
    phase_context: list[str] = Field(default_factory=list)


def detect_log_patterns(
    entries: list[LogEntry],
    *,
    min_level: str = "WARNING",
    min_count: int = 3,
) -> list[LogPattern]:
    """Group log entries by fingerprint+module and return patterns above threshold.

    Only entries at *min_level* or above are considered.  Results are sorted
    by frequency descending.
    """
    level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level_val = level_order.get(min_level, 2)

    groups: dict[tuple[str, str], list[LogEntry]] = defaultdict(list)
    for entry in entries:
        if level_order.get(entry.level, 0) < min_level_val:
            continue
        fp = fingerprint_message(entry.msg)
        key = (fp, entry.logger_name)
        groups[key].append(entry)

    patterns: list[LogPattern] = []
    for (fp, module), group_entries in groups.items():
        if len(group_entries) < min_count:
            continue
        patterns.append(
            LogPattern(
                fingerprint=fp,
                level=group_entries[0].level,
                source_module=module,
                count=len(group_entries),
                sample_messages=[e.msg for e in group_entries[:3]],
                sample_issues=[e.issue for e in group_entries if e.issue is not None][
                    :5
                ],
                first_seen=group_entries[0].ts,
                last_seen=group_entries[-1].ts,
            )
        )

    return sorted(patterns, key=lambda p: p.count, reverse=True)


# ---------------------------------------------------------------------------
# Part 6: EventBus Cross-Reference (bead: ysf)
# ---------------------------------------------------------------------------


def enrich_patterns_with_events(
    patterns: list[LogPattern],
    event_history: list[dict[str, Any]],
) -> None:
    """Enrich log patterns with phase context from EventBus history.

    Mutates patterns in-place, adding phase_context field.
    """
    for pattern in patterns:
        if not pattern.sample_issues:
            continue
        phase_context: list[str] = []
        for issue_id in pattern.sample_issues[:3]:
            # Find phase events for this issue
            issue_events = [
                e
                for e in event_history
                if e.get("data", {}).get("issue") == issue_id
                and e.get("type") in {"phase_change", "worker_update"}
            ]
            for evt in issue_events[-2:]:  # last 2 events per issue
                phase = evt.get("data", {}).get("phase", "unknown")
                status = evt.get("data", {}).get("status", "")
                ctx = f"issue #{issue_id}: {phase}"
                if status:
                    ctx += f" ({status})"
                if ctx not in phase_context:
                    phase_context.append(ctx)
        pattern.phase_context = phase_context[:5]  # cap at 5


# ---------------------------------------------------------------------------
# Part 4: Cross-Run Pattern Persistence (bead: lxd)
# ---------------------------------------------------------------------------

_LOG_PATTERNS_FILE = "log_patterns.jsonl"


class KnownLogPattern(BaseModel):
    """Persistence record for a previously filed log pattern."""

    fingerprint: str
    source_module: str
    filed_at: str
    issue_number: int = 0  # 0 when filed via local JSONL (no GitHub issue)
    last_count: int
    filed_count: int  # count when first filed — baseline for escalation


def load_known_patterns(memory_dir: Path) -> dict[str, KnownLogPattern]:
    """Load known patterns from ``log_patterns.jsonl``.

    Returns an empty dict if the file does not exist or is unreadable.
    Key format: ``"{source_module}:{fingerprint}"``.
    """
    path = memory_dir / _LOG_PATTERNS_FILE
    if not path.exists():
        return {}
    patterns: dict[str, KnownLogPattern] = {}
    try:
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            try:
                record = KnownLogPattern.model_validate_json(line)
                key = f"{record.source_module}:{record.fingerprint}"
                patterns[key] = record
            except Exception:  # noqa: BLE001
                continue  # skip malformed entries
    except OSError:
        return {}
    return patterns


def save_known_patterns(memory_dir: Path, patterns: dict[str, KnownLogPattern]) -> None:
    """Persist known patterns to ``log_patterns.jsonl``."""
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / _LOG_PATTERNS_FILE
        lines = [p.model_dump_json() for p in patterns.values()]
        path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    except OSError:
        logger.warning("Failed to save known log patterns", exc_info=True)


# ---------------------------------------------------------------------------
# Part 3: Log-to-Memory Pipeline (bead: plt)
# Part 5: Severity Escalation (bead: jc3 — via 3x check)
# ---------------------------------------------------------------------------


class LogIngestionResult(BaseModel):
    """Summary of a log ingestion run."""

    filed: int = 0
    escalated: int = 0
    total_patterns: int = 0


def _build_escalation_body(
    pattern: LogPattern,
    known: KnownLogPattern,
) -> str:
    """Format a [Health Monitor] HITL issue body for an escalating log pattern."""
    increase_factor = (
        pattern.count / known.filed_count if known.filed_count > 0 else pattern.count
    )
    samples = "\n".join(f"- `{m}`" for m in pattern.sample_messages)
    affected = pattern.sample_issues if pattern.sample_issues else "N/A"
    return (
        f"## Observation\n"
        f"Pattern `{pattern.fingerprint}` in `{pattern.source_module}` has increased "
        f"from {known.filed_count} to {pattern.count} occurrences "
        f"({increase_factor:.1f}x increase).\n\n"
        f"## Sample Messages\n"
        f"{samples}\n\n"
        f"## Affected Issues\n"
        f"{affected}\n\n"
        f"## Recommendation\n"
        + (
            f"This pattern was first filed as issue #{known.issue_number} on "
            if known.issue_number
            else "This pattern was first recorded on "
        )
        + f"{known.filed_at}.\n"
        f"The increasing frequency suggests the root cause has not been addressed.\n"
    )


def _escalate_log_pattern(
    pattern: LogPattern,
    known: KnownLogPattern,
    config: HydraFlowConfig,
) -> None:
    """Write a HITL recommendation for an escalating log pattern."""
    title = f"[Health Monitor] Log pattern escalating: {pattern.fingerprint[:60]}"
    body = _build_escalation_body(pattern, known)
    try:
        rec = {
            "title": title,
            "body": body,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": "recommendation",
        }
        rec_path = config.data_path("memory", "hitl_recommendations.jsonl")
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        with rec_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        logger.warning("HITL recommendation: %s", title)
    except OSError:
        logger.debug("Failed to write HITL recommendation", exc_info=True)

    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.capture_message(
            f"Log pattern escalating: {pattern.fingerprint[:60]}",
            level="warning",
        )
    except ImportError:
        pass


async def file_log_patterns(
    patterns: list[LogPattern],
    known_patterns: dict[str, KnownLogPattern],
    config: HydraFlowConfig,
) -> LogIngestionResult:
    """Track novel log patterns for dedup and escalate frequency spikes.

    Mutates *known_patterns* in-place — callers must persist it afterwards via
    :func:`save_known_patterns`. Escalating patterns (3x frequency increase) are
    written to ``hitl_recommendations.jsonl``.

    Tribal-memory filing was removed in the tribal-memory rollout (2026-04-07).
    Novel log patterns are noise below the tribal bar; this function now only
    maintains the dedup state and Sentry breadcrumbs. Use the explicit
    tribal_recorder tool to deliberately preserve hard-won facts. See
    docs/superpowers/plans/2026-04-07-tribal-memory.md.
    """
    filed = 0
    escalated = 0

    for pattern in patterns:
        key = f"{pattern.source_module}:{pattern.fingerprint}"

        if key not in known_patterns:
            # Novel pattern — record for dedup but do NOT file as tribal memory.
            known_patterns[key] = KnownLogPattern(
                fingerprint=pattern.fingerprint,
                source_module=pattern.source_module,
                filed_at=datetime.now(UTC).isoformat(),
                issue_number=0,
                last_count=pattern.count,
                filed_count=pattern.count,
            )
            filed += 1

            try:
                import sentry_sdk  # noqa: PLC0415

                sentry_sdk.add_breadcrumb(
                    category="log_ingestion.novel",
                    message=f"Novel log pattern: {pattern.fingerprint[:80]}",
                    level="info",
                )
            except ImportError:
                pass
        else:
            # Known pattern — check for escalation (3x increase over filed baseline)
            known = known_patterns[key]
            if pattern.count >= known.filed_count * 3:
                _escalate_log_pattern(pattern, known, config)
                escalated += 1
            known.last_count = pattern.count

    return LogIngestionResult(
        filed=filed, escalated=escalated, total_patterns=len(patterns)
    )


# ---------------------------------------------------------------------------
# Part 8: Cross-Project Log Aggregation (bead: lkx)
# ---------------------------------------------------------------------------


@dataclass
class CrossProjectPattern:
    """A log pattern that appears across multiple factory projects."""

    fingerprint: str
    source_module: str
    projects: list[str] = field(default_factory=list)
    total_count: int = 0


def detect_cross_project_log_patterns(
    project_patterns: dict[str, dict[str, KnownLogPattern]],
    *,
    min_projects: int = 2,
) -> list[CrossProjectPattern]:
    """Find log patterns appearing in multiple factory projects."""
    all_keys: dict[str, list[str]] = defaultdict(list)
    for slug, patterns in project_patterns.items():
        for key in patterns:
            all_keys[key].append(slug)

    cross = []
    for key, slugs in all_keys.items():
        if len(slugs) >= min_projects:
            # Parse key back into module:fingerprint
            parts = key.split(":", 1)
            module = parts[0] if len(parts) > 1 else "unknown"
            fp = parts[1] if len(parts) > 1 else key
            total = sum(project_patterns[s][key].last_count for s in slugs)
            cross.append(
                CrossProjectPattern(
                    fingerprint=fp,
                    source_module=module,
                    projects=slugs,
                    total_count=total,
                )
            )

    return sorted(cross, key=lambda p: len(p.projects), reverse=True)
