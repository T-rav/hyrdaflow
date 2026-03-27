# Log Ingestion Pipeline Design

**Date:** 2026-03-26
**Status:** Draft
**Beads:** ops-audit-fixes-k7x, plt, 9uc, cd5, lxd, jc3, ysf, lkx, l7v, 3rz

## Problem

HydraFlow produces rich structured JSON logs (via `log.py:JSONFormatter`) with contextual fields (`issue`, `phase`, `worker`, `repo`). These logs are written to rotating files (10MB max, 5 backups) but never read back. Operational patterns — recurring warnings, error clusters, correlated failures across phases — are invisible to the learning system. A human would need to manually grep log files to spot trends.

For a dark factory, this is a critical gap: the system can't learn from its own operational signals.

## Goal

Build a log ingestion pipeline that:
1. Reads structured JSON log files
2. Detects recurring patterns (fingerprinted by message template + source module)
3. Files novel patterns as `[Memory]` items automatically
4. Tracks known patterns to avoid refiling
5. Escalates patterns that increase in frequency
6. Cross-references with EventBus phase/issue data for richer context
7. Emits metrics to Sentry for observability

## Architecture

```
Log Files (JSON, rotating)
    │
    ▼
┌─────────────────────────────────────┐
│     Log Pattern Detector            │
│                                     │
│  1. Parse JSON log entries          │
│  2. Fingerprint messages            │
│  3. Group by (fingerprint, level)   │
│  4. Count occurrences in window     │
│  5. Compare against known patterns  │
│                                     │
│  Output: novel patterns,            │
│          escalating patterns,       │
│          pattern frequency map      │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│     Log-to-Memory Pipeline          │
│                                     │
│  Novel pattern (3+ occurrences):    │
│    → File [Memory] issue            │
│    → Type: instruction              │
│    → Add to log_patterns.jsonl      │
│                                     │
│  Escalating pattern (3x increase):  │
│    → File [Health Monitor] HITL     │
│    → Include frequency trend        │
│                                     │
│  Cross-project match:               │
│    → Promote to global memory       │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│     Health Monitor Integration      │
│                                     │
│  Called each cycle (2 hours)        │
│  Emits Sentry metrics:             │
│    memory.log_patterns_total        │
│    memory.log_patterns_novel        │
│    memory.log_patterns_escalating   │
└─────────────────────────────────────┘
```

---

## Part 1: Structured Log Parser

**Bead:** ops-audit-fixes-9uc (P0)

### New file: `src/log_ingestion.py`

Parse JSON log files produced by `JSONFormatter`. Each line is:

```json
{"ts": "2026-03-26T10:00:00Z", "level": "WARNING", "msg": "Score update failed for item 42", "logger": "hydraflow.memory_scoring", "issue": 42, "phase": "implement"}
```

### Log entry model

```python
class LogEntry(BaseModel):
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
```

### Message fingerprinting

To group similar log messages, strip variable parts:

```python
def fingerprint_message(msg: str) -> str:
    """Reduce a log message to a stable template for grouping."""
    # Replace numbers with <N>
    result = re.sub(r'\b\d+\b', '<N>', msg)
    # Replace quoted strings with <S>
    result = re.sub(r"'[^']*'", '<S>', result)
    result = re.sub(r'"[^"]*"', '<S>', result)
    # Replace hex hashes with <H>
    result = re.sub(r'\b[0-9a-f]{8,}\b', '<H>', result)
    # Replace paths with <P>
    result = re.sub(r'/[\w/.+-]+', '<P>', result)
    return result.strip()
```

Examples:
- `"Score update failed for item 42"` → `"Score update failed for item <N>"`
- `"Merged PR #101 on branch agent/issue-42"` → `"Merged PR #<N> on branch agent<P>"`
- `"Digest hash abc123def456"` → `"Digest hash <H>"`

### Parse function

```python
def parse_log_file(path: Path, *, since: datetime | None = None) -> list[LogEntry]:
    """Parse a JSON log file, returning entries since the given timestamp."""
    entries = []
    for line in path.read_text().strip().splitlines():
        try:
            data = json.loads(line)
            entry = LogEntry.model_validate(data)
            if since and entry.ts < since.isoformat():
                continue
            entries.append(entry)
        except Exception:
            continue  # malformed lines skipped
    return entries
```

---

## Part 2: Log Pattern Detector

**Bead:** ops-audit-fixes-k7x (P0)

### Pattern model

```python
class LogPattern(BaseModel):
    fingerprint: str           # template after variable stripping
    level: str                 # WARNING, ERROR
    source_module: str         # logger name (e.g., "hydraflow.memory_scoring")
    count: int                 # occurrences in window
    sample_messages: list[str] # up to 3 original messages (for context)
    sample_issues: list[int]   # issue numbers seen with this pattern
    first_seen: str            # earliest timestamp
    last_seen: str             # latest timestamp
```

### Detection function

```python
def detect_log_patterns(
    entries: list[LogEntry],
    *,
    min_level: str = "WARNING",
    min_count: int = 3,
) -> list[LogPattern]:
    """Group log entries by fingerprint and return patterns above threshold."""
    level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level_val = level_order.get(min_level, 2)

    groups: dict[tuple[str, str], list[LogEntry]] = defaultdict(list)
    for entry in entries:
        if level_order.get(entry.level, 0) < min_level_val:
            continue
        fp = fingerprint_message(entry.msg)
        key = (fp, entry.logger_name)
        groups[key].append(entry)

    patterns = []
    for (fp, module), group_entries in groups.items():
        if len(group_entries) < min_count:
            continue
        patterns.append(LogPattern(
            fingerprint=fp,
            level=group_entries[0].level,
            source_module=module,
            count=len(group_entries),
            sample_messages=[e.msg for e in group_entries[:3]],
            sample_issues=[e.issue for e in group_entries if e.issue][:5],
            first_seen=group_entries[0].ts,
            last_seen=group_entries[-1].ts,
        ))

    return sorted(patterns, key=lambda p: p.count, reverse=True)
```

---

## Part 3: Log-to-Memory Pipeline

**Bead:** ops-audit-fixes-plt (P0)

### Novelty check

Known patterns stored in `.hydraflow/memory/log_patterns.jsonl`:

```json
{"fingerprint": "Score update failed for item <N>", "source_module": "hydraflow.memory_scoring", "filed_at": "...", "issue_number": 5742, "last_count": 5, "filed_count": 5}
```

A pattern is novel if its fingerprint+module combo is NOT in the known patterns file.

### Filing logic

```python
async def file_log_patterns(
    patterns: list[LogPattern],
    known_patterns: dict[str, KnownLogPattern],
    prs: PRPort,
    config: HydraFlowConfig,
) -> LogIngestionResult:
    """File novel patterns as memory items, escalate increasing patterns."""
    filed = 0
    escalated = 0

    for pattern in patterns:
        key = f"{pattern.source_module}:{pattern.fingerprint}"

        if key not in known_patterns:
            # Novel pattern — file as memory item
            title = f"[Memory] Log pattern: {pattern.fingerprint[:60]}"
            body = _build_log_memory_body(pattern)
            issue_number = await prs.create_issue(
                title, body, labels=list(config.improve_label)
            )
            if issue_number > 0:
                known_patterns[key] = KnownLogPattern(
                    fingerprint=pattern.fingerprint,
                    source_module=pattern.source_module,
                    filed_at=datetime.now(UTC).isoformat(),
                    issue_number=issue_number,
                    last_count=pattern.count,
                    filed_count=pattern.count,
                )
                filed += 1
        else:
            # Known pattern — check for escalation
            known = known_patterns[key]
            if pattern.count >= known.last_count * 3:
                # 3x increase — escalate
                await _escalate_log_pattern(pattern, known, prs, config)
                escalated += 1
            known.last_count = pattern.count

    return LogIngestionResult(filed=filed, escalated=escalated, total_patterns=len(patterns))
```

### Memory item body format

```python
def _build_log_memory_body(pattern: LogPattern) -> str:
    return (
        f"**Type:** instruction\n"
        f"**Learning:** Recurring {pattern.level} in `{pattern.source_module}`: "
        f"{pattern.fingerprint}\n\n"
        f"**Context:** Detected {pattern.count} occurrences between "
        f"{pattern.first_seen} and {pattern.last_seen}.\n\n"
        f"**Sample messages:**\n"
        + "\n".join(f"- `{m}`" for m in pattern.sample_messages)
        + "\n\n"
        f"**Affected issues:** {pattern.sample_issues or 'N/A'}\n\n"
        f"**Action needed:** Investigate root cause and add handling or prevention.\n"
    )
```

---

## Part 4: Cross-Run Pattern Persistence

**Bead:** ops-audit-fixes-lxd (P1)

### Storage: `.hydraflow/memory/log_patterns.jsonl`

```python
class KnownLogPattern(BaseModel):
    fingerprint: str
    source_module: str
    filed_at: str
    issue_number: int
    last_count: int
    filed_count: int  # count when first filed — baseline for escalation

def load_known_patterns(memory_dir: Path) -> dict[str, KnownLogPattern]:
    """Load known patterns from JSONL."""

def save_known_patterns(memory_dir: Path, patterns: dict[str, KnownLogPattern]) -> None:
    """Persist known patterns to JSONL."""
```

Key format: `"{source_module}:{fingerprint}"` — unique per module+template combo.

---

## Part 5: Severity Escalation

**Bead:** ops-audit-fixes-jc3 (P1)

### Escalation criteria

A known pattern is escalated when:
1. Current count >= 3x the count when it was first filed (`filed_count`)
2. The pattern is level ERROR or CRITICAL
3. OR the pattern's frequency increased 3x since last check (`last_count`)

### Escalation action

File a HITL issue:
```
[Health Monitor] Log pattern escalating: {fingerprint}

## Observation
Pattern `{fingerprint}` in `{source_module}` has increased from {filed_count}
to {current_count} occurrences ({increase_factor}x increase).

## Sample Messages
{sample_messages}

## Affected Issues
{issue_numbers}

## Recommendation
This pattern was first filed as issue #{original_issue_number} on {filed_at}.
The increasing frequency suggests the root cause has not been addressed.
```

Labels: `config.hitl_label`

---

## Part 6: Health Monitor Integration

**Bead:** ops-audit-fixes-cd5 (P1)

### Wire into `health_monitor_loop.py:_do_work()`

Add log ingestion as a step in the health monitor cycle:

```python
# After existing metrics computation and before Sentry emission

# Log pattern analysis
try:
    from log_ingestion import (
        parse_log_files,
        detect_log_patterns,
        file_log_patterns,
        load_known_patterns,
        save_known_patterns,
    )
    log_dir = Path(self._config.log_file).parent if self._config.log_file else None
    if log_dir and log_dir.is_dir():
        entries = parse_log_files(log_dir, since=self._last_log_scan)
        patterns = detect_log_patterns(entries)
        known = load_known_patterns(self._config.memory_dir)
        log_result = await file_log_patterns(patterns, known, self._prs, self._config)
        save_known_patterns(self._config.memory_dir, known)
        self._last_log_scan = datetime.now(UTC)
except ImportError:
    pass
except Exception:
    logger.debug("Log ingestion failed", exc_info=True)
```

---

## Part 7: Log Rotation Awareness

**Bead:** ops-audit-fixes-3rz (P1)

### Problem

`RotatingFileHandler` creates backup files: `server.log`, `server.log.1`, `server.log.2`, etc. When a log file rotates mid-scan, entries could be missed or double-counted.

### Solution

```python
def parse_log_files(
    log_dir: Path,
    *,
    since: datetime | None = None,
    max_backups: int = 2,
) -> list[LogEntry]:
    """Parse the main log file plus recent backups."""
    entries = []
    main_log = log_dir / "server.log"

    # Parse backups oldest-first, then main file
    for i in range(max_backups, 0, -1):
        backup = log_dir / f"server.log.{i}"
        if backup.exists():
            entries.extend(parse_log_file(backup, since=since))

    if main_log.exists():
        entries.extend(parse_log_file(main_log, since=since))

    # Sort by timestamp and deduplicate
    entries.sort(key=lambda e: e.ts)
    return entries
```

Track `_last_log_scan` timestamp in the health monitor to only process new entries each cycle. This naturally handles rotation: if entries moved from `server.log` to `server.log.1`, the timestamp filter skips them on the next scan.

---

## Part 8: EventBus Cross-Reference

**Bead:** ops-audit-fixes-ysf (P2)

### Enrich log patterns with EventBus context

After detecting patterns, cross-reference with EventBus history to add phase and outcome context:

```python
def enrich_patterns_with_events(
    patterns: list[LogPattern],
    event_bus: EventBus,
) -> None:
    """Add phase context from EventBus to log patterns."""
    history = event_bus.get_history()
    for pattern in patterns:
        for issue_id in pattern.sample_issues:
            # Find phase events for this issue
            phase_events = [
                e for e in history
                if e.data.get("issue") == issue_id
                and e.type in {EventType.PHASE_CHANGE, EventType.WORKER_UPDATE}
            ]
            if phase_events:
                pattern.phase_context = [
                    f"{e.type.value}: {e.data.get('phase', 'unknown')}"
                    for e in phase_events[-3:]  # last 3 events
                ]
```

This makes the memory item richer: instead of just "WARNING in memory_scoring", it becomes "WARNING in memory_scoring during implement phase for issues #42, #55".

---

## Part 9: Cross-Project Log Aggregation

**Bead:** ops-audit-fixes-lkx (P2)

### Detection

When the health monitor runs across multiple projects (dashboard mode with registry), compare log patterns across project stores:

```python
def detect_cross_project_log_patterns(
    project_patterns: dict[str, dict[str, KnownLogPattern]],
    min_projects: int = 2,
) -> list[CrossProjectPattern]:
    """Find log patterns appearing in multiple projects."""
    all_fingerprints: dict[str, list[str]] = defaultdict(list)
    for slug, patterns in project_patterns.items():
        for key in patterns:
            all_fingerprints[key].append(slug)

    cross = []
    for key, slugs in all_fingerprints.items():
        if len(slugs) >= min_projects:
            cross.append(CrossProjectPattern(
                fingerprint=key,
                projects=slugs,
                total_count=sum(
                    project_patterns[s][key].last_count for s in slugs
                ),
            ))
    return cross
```

Cross-project patterns are candidates for global memory promotion.

---

## Part 10: Sentry Integration

**Bead:** ops-audit-fixes-l7v (P1)

### Metrics

Add to `_emit_sentry_metrics()` in health_monitor_loop.py:

```python
sentry_sdk.set_measurement("memory.log_patterns_total", total_patterns)
sentry_sdk.set_measurement("memory.log_patterns_novel", novel_count)
sentry_sdk.set_measurement("memory.log_patterns_escalating", escalated_count)
```

### Breadcrumbs

When filing a novel pattern:
```python
sentry_sdk.add_breadcrumb(
    category="log_ingestion.novel",
    message=f"Novel log pattern: {pattern.fingerprint[:80]}",
    level="info",
    data={"module": pattern.source_module, "count": pattern.count},
)
```

When escalating:
```python
sentry_sdk.capture_message(
    f"Log pattern escalating: {pattern.fingerprint[:60]} ({pattern.count}x)",
    level="warning",
)
```

---

## Implementation Order

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 1 | 9uc | Structured log parser | None |
| 2 | k7x | Log pattern detector | 9uc |
| 3 | plt | Log-to-memory pipeline | k7x |
| 4 | lxd | Cross-run pattern persistence | plt |
| 5 | 3rz | Log rotation awareness | 9uc |
| 6 | jc3 | Severity escalation | lxd |
| 7 | cd5 | Health monitor integration | plt, 3rz |
| 8 | l7v | Sentry integration | cd5 |
| 9 | ysf | EventBus cross-reference | k7x (P2) |
| 10 | lkx | Cross-project aggregation | lxd (P2) |

Phases 1-4 are sequential (core pipeline). Phase 5 is parallel with 3-4. Phases 6-8 depend on the core. Phases 9-10 are P2 enhancements.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/log_ingestion.py` | **Create** | LogEntry, fingerprinting, pattern detection, filing, persistence |
| `src/health_monitor_loop.py` | Modify | Wire log ingestion into _do_work cycle |
| `tests/test_log_ingestion.py` | **Create** | Full test suite |

## Testing Strategy

- **Log parser:** Parse fixture JSON log files, handle malformed lines, filter by timestamp
- **Fingerprinting:** Parametrized test: `(input_message, expected_fingerprint)` for numbers, strings, hashes, paths
- **Pattern detection:** Fixture with 50+ entries, verify grouping, threshold, sorting
- **Filing:** Mock prs.create_issue, verify title/body format, dedup via known patterns
- **Escalation:** Verify 3x threshold triggers HITL issue
- **Rotation:** Fixture with main + backup files, verify dedup across files
- **Sentry:** Mock sentry_sdk, verify measurements emitted
