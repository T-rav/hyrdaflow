# Auto-Agent HITL Pre-Flight Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `AutoAgentPreflightLoop` (spec §1–§11) — a new caretaker loop that intercepts every `hitl-escalation` issue before a human sees it, runs an emulated-engineer Claude Code subprocess to attempt autonomous resolution, and only escalates to a new `human-required` label when the agent itself bails or 3 attempts exhaust. Closes the largest remaining dark-factory gap in HydraFlow.

**Architecture:** Polling caretaker pattern — one new loop polls open `hitl-escalation` issues, gathers context (issue body + escalation_context + wiki + Sentry + recent commits + prior attempts), spawns a Claude Code subprocess with a sub-label-routed persona prompt, captures cost telemetry, and applies a label-state decision. Zero call-site changes anywhere — every existing escalation continues to add `hitl-escalation` exactly like today; the new loop is the chokepoint. Five-checkpoint wiring per ADR-0049. Cost / wall-clock / daily-budget caps wired into code paths but defaulted to unlimited (observability-first).

**Tech Stack:** Python 3.11, `BaseBackgroundLoop` (existing), `HITLRunner` reused as subprocess base, Pydantic models, JSONL append-only audit store, React (System tab dashboard tile), pytest + cassette-fake Claude Code, VCR for Sentry contract tests.

**Spec ref:** `docs/superpowers/specs/2026-04-25-auto-agent-hitl-preflight-design.md` (446 lines + 3 review-pass fixes).

---

## Decisions Locked (spec → plan)

1. **Polling, not in-place interception.** New loop polls `hitl-escalation` items; existing call sites unchanged (spec §1, §2.2, §9.2).
2. **Three attempts per issue.** `auto_agent_max_attempts = 3`. Each subsequent attempt receives prior-attempt diagnoses in its prompt context (spec §3.5, §4.2).
3. **Caps wired but default-unlimited.** `auto_agent_cost_cap_usd`, `auto_agent_wall_clock_cap_s`, `auto_agent_daily_budget_usd` all default `None`. Code paths exist; operator can flip on (spec §5.1).
4. **Deny-list defaults `["principles-stuck", "cultural-check"]`** — match `principles_audit_loop.py:339-345` exact label names; recursive-safety guard (spec §5.1, §4.2; review-pass fix #1).
5. **Sequential single-issue-per-tick.** Bounds concurrent cost; pre-flight latency tolerance is "minutes" (spec §2.3).
6. **`escalation_context` may be `None`.** Most caretaker-loop escalations never call `set_escalation_context`. The prompt template MUST tolerate `None` and operate from issue body + sub-label + wiki + sentry alone (spec §3.2, §7; review-pass fix #3).
7. **StateData additions are explicit Pydantic fields**, not just mixin methods. Two new fields on `StateData` for serialization (spec §3.6; review-pass fix #2).
8. **Hard tool restrictions enforced at the worktree-tool layer**, not just the prompt: no `.github/workflows/`, no force-push, no secrets, no `principles_audit_loop.py` / `auto_agent_preflight_loop.py` / ADR-0044 / ADR-0049 file edits (spec §5.2).
9. **PreflightAgent reuses HITLRunner as subprocess base**, parameterized with the auto-agent prompt envelope and tool-restriction overrides. Composition over a fork (spec §3.3, §10 open decision #1 — resolved here as: subclass HITLRunner via a thin `AutoAgentRunner` adapter; do NOT fork the whole BaseRunner stack).
10. **Generic naming** — every public surface uses `auto-agent` / `auto_agent`. The persona prompt parameter (`auto_agent_persona`) defaults to a generic "lead engineer for this project" string; operators can override locally (spec rename throughout).
11. **JSONL audit store is the source of truth.** StateData mirrors `auto_agent_daily_spend` for fast dashboard reads, but the JSONL is canonical (spec §6.3).
12. **No alerts.** Dashboard surfaces information; no thresholds page anyone (spec §6.1).
13. **Tick cadence = 120s** (spec §2.1). Bounds `60–600` in `_INTERVAL_BOUNDS` and `Field(...)` constraints.
14. **`run_on_startup=False`** — first cycle waits for the interval, no cold-start surprise (spec §2.1).
15. **One-shot escalation** when caps fire or attempt cap exhausts — no retry queue, no exponential backoff. The audit + label IS the record.
16. **ADR-0050 lands with this plan** — net-new ADR documenting the auto-agent pre-flight pattern (spec §10 open decision #5 — resolved here as: yes, separate ADR, since the caretaker pattern exists in ADR-0029 but the pre-flight semantics are net-new).

---

## File Structure

| File | Role | C/M |
|---|---|---|
| `docs/adr/0050-auto-agent-hitl-preflight.md` | ADR-0050: auto-agent pre-flight pattern + label semantics + recursion guards | C |
| `src/models.py:1764` | Append two `StateData` fields after `contract_refresh_attempts`: `auto_agent_attempts` + `auto_agent_daily_spend` | M |
| `src/state/_auto_agent.py` | New `AutoAgentStateMixin` — attempts getter/inc/clear + daily-spend getter/add | C |
| `src/state/__init__.py:25-53, 62-92` | Import mixin + append to `StateTracker` MRO | M |
| `src/config.py:213` (env-overrides) | Append rows for `auto_agent_preflight_interval` + `auto_agent_max_attempts` | M |
| `src/config.py:~1850` | Append seven `HydraFlowConfig` fields after `principles_audit_*` block | M |
| `src/preflight/__init__.py` | Empty package marker | C |
| `src/preflight/audit.py` | `PreflightAuditStore` — append-only JSONL + 24h/7d/top-spend/by-issue queries | C |
| `src/preflight/context.py` | `PreflightContext` dataclass + `gather_context()` factory function | C |
| `src/preflight/decision.py` | `PreflightDecision` — pure logic mapping `PreflightResult` → label operations | C |
| `src/preflight/agent.py` | `PreflightAgent` — wraps `AutoAgentRunner` (new HITLRunner subclass), cost-cap + wall-clock-cap watchers, returns `PreflightResult` | C |
| `src/preflight/runner.py` | `AutoAgentRunner` — thin `HITLRunner` subclass with auto-agent prompt envelope + tool-restriction overrides | C |
| `src/sentry/__init__.py` | Empty package marker | C |
| `src/sentry/reverse_lookup.py` | `query_sentry_by_fingerprint(title, fingerprint) -> list[SentryEvent]` — VCR-cassette-tested | C |
| `prompts/auto_agent/_envelope.md` | Shared prompt envelope (identity / context / prior-attempts / tool-restrictions / decision-protocol blocks) | C |
| `prompts/auto_agent/_default.md` | Default fallback prompt (any unmapped sub-label) | C |
| `prompts/auto_agent/flaky-test-stuck.md` | Flaky-test-fix playbook | C |
| `prompts/auto_agent/revert-conflict.md` | Staging revert cleanup playbook | C |
| `prompts/auto_agent/rc-red-bisect-exhausted.md` | Bisect-recovery playbook | C |
| `prompts/auto_agent/fake-drift-stuck.md` | Adapter cassette drift fix | C |
| `prompts/auto_agent/fake-coverage-stuck.md` | Fake coverage hole fix | C |
| `prompts/auto_agent/wiki-rot-stuck.md` | Wiki entry rewrite playbook | C |
| `prompts/auto_agent/rc-duration-stuck.md` | Release-critical unblock playbook | C |
| `prompts/auto_agent/skill-prompt-stuck.md` | Skill prompt-eval regression fix | C |
| `prompts/auto_agent/trust-loop-anomaly.md` | Trust-loop anomaly investigation playbook | C |
| `src/auto_agent_preflight_loop.py` | `AutoAgentPreflightLoop` — `BaseBackgroundLoop` subclass; `_do_work` pipeline | C |
| `src/service_registry.py:~70` | `from auto_agent_preflight_loop import AutoAgentPreflightLoop` | M |
| `src/service_registry.py:~175` | Append `auto_agent_preflight_loop: AutoAgentPreflightLoop` to dataclass | M |
| `src/service_registry.py:~810` | Construct loop instance | M |
| `src/service_registry.py:~910` | Append `auto_agent_preflight_loop=auto_agent_preflight_loop,` to `ServiceRegistry(...)` | M |
| `src/orchestrator.py:~166` | Append `"auto_agent_preflight": svc.auto_agent_preflight_loop,` to `bg_loop_registry` | M |
| `src/orchestrator.py:~948` | Append `("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),` to `loop_factories` | M |
| `src/ui/src/constants.js:252` | Append `'auto_agent_preflight'` to `EDITABLE_INTERVAL_WORKERS` | M |
| `src/ui/src/constants.js:~277` | Append `auto_agent_preflight: 120,` to `SYSTEM_WORKER_INTERVALS` | M |
| `src/ui/src/constants.js:~325` | Append `BACKGROUND_WORKERS` entry (label + description + tags) | M |
| `src/dashboard_routes/_common.py:~58` | Append `"auto_agent_preflight": (60, 600),` to `_INTERVAL_BOUNDS` | M |
| `src/dashboard_routes/_diagnostics_routes.py` | Add `GET /api/diagnostics/auto-agent` route | M |
| `src/ui/src/components/system/AutoAgentStats.jsx` | New React component for the System tab tile | C |
| `src/ui/src/components/system/SystemTab.jsx` | Mount `AutoAgentStats` tile | M |
| `tests/test_state_auto_agent.py` | Mixin unit tests (attempts, daily spend) | C |
| `tests/test_preflight_audit_store.py` | Append-only correctness, 24h/7d aggregator, top-spend ranking | C |
| `tests/test_preflight_context.py` | Context gathering, escalation_context=None handling, prior-attempts injection | C |
| `tests/test_preflight_decision.py` | Each PreflightResult status → correct label transition; idempotency; race detection | C |
| `tests/test_preflight_agent.py` | Subprocess spawn + cost telemetry capture + soft/hard cap kill + persona substitution | C |
| `tests/test_auto_agent_preflight_loop.py` | Loop scaffolding: kill-switch, single-issue-per-tick, deny-list bypass, attempt-cap, daily-budget gate | C |
| `tests/test_auto_agent_close_reconciliation.py` | Issue-close → `clear_auto_agent_attempts` integration | C |
| `tests/contracts/test_sentry_reverse_lookup.py` | VCR cassette of Sentry API → assert parser extracts the right metadata | C |
| `tests/auto_agent/adversarial/__init__.py` | Empty package marker | C |
| `tests/auto_agent/adversarial/test_corpus.py` | Adversarial corpus runner — iterates `corpus/` entries, asserts golden outcomes | C |
| `tests/auto_agent/adversarial/corpus/<sub-label>/` | One directory per sub-label with `issue.json`, `cassette.json`, `expected.json` | C |
| `tests/scenarios/test_auto_agent_preflight.py` | Full-loop scenarios with mocked GitHub + cassette-fake Claude Code | C |
| `tests/scenarios/catalog/loop_registrations.py:~234` | `_build_auto_agent_preflight` + `_BUILDERS` entry | M |
| `tests/scenarios/catalog/test_loop_instantiation.py` | `"auto_agent_preflight",` | M |
| `tests/scenarios/catalog/test_loop_registrations.py` | `"auto_agent_preflight",` | M |
| `Makefile` | Add `auto-agent-adversarial` target | M |

---

## Task 1 — StateData fields + `AutoAgentStateMixin`

**Modify** `src/models.py:1764` — after `contract_refresh_attempts: dict[str, int] = Field(default_factory=dict)`, insert:

```python
    # Auto-Agent — AutoAgentPreflightLoop (spec §3.6)
    auto_agent_attempts: dict[str, int] = Field(default_factory=dict)
    auto_agent_daily_spend: dict[str, float] = Field(default_factory=dict)
```

**Create** `src/state/_auto_agent.py`:

```python
"""State mixin for AutoAgentPreflightLoop (spec §3.6)."""

from __future__ import annotations


class AutoAgentStateMixin:
    """Per-issue attempt counter + per-day spend tracker."""

    def get_auto_agent_attempts(self, issue: int) -> int:
        return int(self._data.auto_agent_attempts.get(str(issue), 0))

    def bump_auto_agent_attempts(self, issue: int) -> int:
        key = str(issue)
        current = int(self._data.auto_agent_attempts.get(key, 0))
        self._data.auto_agent_attempts[key] = current + 1
        self._save()
        return current + 1

    def clear_auto_agent_attempts(self, issue: int) -> None:
        key = str(issue)
        if key in self._data.auto_agent_attempts:
            del self._data.auto_agent_attempts[key]
            self._save()

    def get_auto_agent_daily_spend(self, date_iso: str) -> float:
        return float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))

    def add_auto_agent_daily_spend(self, date_iso: str, usd: float) -> float:
        current = float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))
        new_total = current + float(usd)
        self._data.auto_agent_daily_spend[date_iso] = new_total
        self._save()
        return new_total
```

**Modify** `src/state/__init__.py` — add `from ._auto_agent import AutoAgentStateMixin` (alphabetical: after `from ._auto_*` if any — currently first alphabetically; insert at line 25 area). Append `AutoAgentStateMixin,` to `StateTracker` MRO (alphabetical position — first or near top).

- [ ] **Step 1: Write failing mixin test** — `tests/test_state_auto_agent.py`:

```python
"""Tests for AutoAgentStateMixin (spec §3.6)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_attempts_default_zero(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_auto_agent_attempts(8501) == 0


def test_bump_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.bump_auto_agent_attempts(8501) == 1
    assert st.bump_auto_agent_attempts(8501) == 2
    assert st.get_auto_agent_attempts(8501) == 2


def test_clear_resets_single_issue(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.bump_auto_agent_attempts(1)
    st.bump_auto_agent_attempts(2)
    st.clear_auto_agent_attempts(1)
    assert st.get_auto_agent_attempts(1) == 0
    assert st.get_auto_agent_attempts(2) == 1


def test_daily_spend_default_zero(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_auto_agent_daily_spend("2026-04-25") == 0.0


def test_add_daily_spend_accumulates(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.add_auto_agent_daily_spend("2026-04-25", 1.50) == 1.50
    assert st.add_auto_agent_daily_spend("2026-04-25", 0.75) == 2.25
    assert st.get_auto_agent_daily_spend("2026-04-25") == 2.25
    assert st.get_auto_agent_daily_spend("2026-04-26") == 0.0


def test_state_persists_across_load(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.bump_auto_agent_attempts(8501)
    st1.add_auto_agent_daily_spend("2026-04-25", 5.0)

    st2 = _tracker(tmp_path)
    assert st2.get_auto_agent_attempts(8501) == 1
    assert st2.get_auto_agent_daily_spend("2026-04-25") == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.hydraflow/worktrees/<branch> && uv run pytest tests/test_state_auto_agent.py -v`
Expected: FAIL with `AttributeError: 'StateTracker' object has no attribute 'get_auto_agent_attempts'` or `ValidationError` on the new fields.

- [ ] **Step 3: Apply the StateData field additions in `models.py:1764`** (insert the two `Field(default_factory=dict)` lines shown above).

- [ ] **Step 4: Create `src/state/_auto_agent.py`** with the mixin code shown above.

- [ ] **Step 5: Modify `src/state/__init__.py`** — add the import and append `AutoAgentStateMixin,` to the `StateTracker(...)` base class list. Place it in alphabetical position (likely first or near-first since "AutoAgent" sorts early).

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_state_auto_agent.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 7: Commit**

```bash
git add src/models.py src/state/_auto_agent.py src/state/__init__.py tests/test_state_auto_agent.py
git commit -m "feat(state): AutoAgentStateMixin + StateData fields (auto-agent §3.6)"
```

---

## Task 2 — Config fields

**Modify** `src/config.py` — env-override block (around line 213, after `principles_audit_interval`):

```python
    ("auto_agent_preflight_interval", "HYDRAFLOW_AUTO_AGENT_PREFLIGHT_INTERVAL", 120),
    ("auto_agent_max_attempts", "HYDRAFLOW_AUTO_AGENT_MAX_ATTEMPTS", 3),
```

**Modify** `src/config.py` — `HydraFlowConfig` class (after `principles_audit_*` block, around line 1980; locate by `principles_audit_interval` field). Append:

```python
    auto_agent_preflight_enabled: bool = Field(
        default=True,
        description="UI kill-switch for AutoAgentPreflightLoop (ADR-0049).",
    )
    auto_agent_preflight_interval: int = Field(
        default=120,
        ge=60,
        le=600,
        description="Seconds between AutoAgentPreflightLoop cycles (default 120).",
    )
    auto_agent_persona: str = Field(
        default=(
            "the lead engineer for this project — pragmatic, prefers small fixes, "
            "leaves regression tests, doesn't over-engineer. When in doubt about "
            "scope, do less."
        ),
        description="Persona substituted into the auto-agent shared prompt envelope.",
    )
    auto_agent_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Per-issue attempt cap before auto-agent-exhausted (default 3).",
    )
    auto_agent_skip_sublabels: list[str] = Field(
        default_factory=lambda: ["principles-stuck", "cultural-check"],
        description=(
            "Sub-labels that bypass auto-agent pre-flight entirely. Default = the "
            "principles-audit recursion guard."
        ),
    )
    auto_agent_cost_cap_usd: float | None = Field(
        default=None,
        description=(
            "Per-attempt cost cap in USD. None = unlimited (observability-first; "
            "operator can set when needed)."
        ),
    )
    auto_agent_wall_clock_cap_s: int | None = Field(
        default=None,
        description="Per-attempt wall-clock cap in seconds. None = unlimited.",
    )
    auto_agent_daily_budget_usd: float | None = Field(
        default=None,
        description="Per-day total spend budget in USD. None = unlimited.",
    )
```

- [ ] **Step 1: Write failing config test** — `tests/test_config_auto_agent.py`:

```python
"""Auto-agent config field defaults (spec §5.1)."""

from __future__ import annotations

from config import HydraFlowConfig


def test_defaults() -> None:
    c = HydraFlowConfig()
    assert c.auto_agent_preflight_enabled is True
    assert c.auto_agent_preflight_interval == 120
    assert c.auto_agent_max_attempts == 3
    assert c.auto_agent_skip_sublabels == ["principles-stuck", "cultural-check"]
    assert c.auto_agent_cost_cap_usd is None
    assert c.auto_agent_wall_clock_cap_s is None
    assert c.auto_agent_daily_budget_usd is None
    assert "lead engineer" in c.auto_agent_persona


def test_interval_bounds_enforced() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_preflight_interval=30)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_preflight_interval=601)


def test_max_attempts_bounds_enforced() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_max_attempts=0)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_max_attempts=11)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_auto_agent.py -v`
Expected: FAIL with attribute errors.

- [ ] **Step 3: Add the config fields and env overrides shown above.**

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_auto_agent.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_auto_agent.py
git commit -m "feat(config): auto-agent config fields (spec §5.1)"
```

---

## Task 3 — `PreflightAuditStore`

**Create** `src/preflight/__init__.py` (empty file).

**Create** `src/preflight/audit.py`:

```python
"""Append-only JSONL audit store for AutoAgentPreflightLoop (spec §3.5)."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreflightAuditEntry:
    ts: str  # ISO 8601
    issue: int
    sub_label: str
    attempt_n: int
    prompt_hash: str
    cost_usd: float
    wall_clock_s: float
    tokens: int
    status: str  # "resolved" | "needs_human" | "fatal" | "pr_failed" | "cost_exceeded" | "timeout"
    pr_url: str | None
    diagnosis: str
    llm_summary: str


@dataclass(frozen=True)
class AuditWindowStats:
    spend_usd: float
    attempts: int
    resolved: int
    resolution_rate: float
    p50_cost_usd: float
    p95_cost_usd: float
    p50_wall_clock_s: float
    p95_wall_clock_s: float


class PreflightAuditStore:
    """Append-only JSONL store at <data_root>/auto_agent/audit.jsonl."""

    def __init__(self, data_root: Path) -> None:
        self._path = data_root / "auto_agent" / "audit.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: PreflightAuditEntry) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    def _read_all(self) -> list[PreflightAuditEntry]:
        if not self._path.exists():
            return []
        out: list[PreflightAuditEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                out.append(PreflightAuditEntry(**row))
        return out

    def query_window(self, since: datetime) -> AuditWindowStats:
        entries = [
            e for e in self._read_all()
            if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= since
        ]
        return _compute_window(entries)

    def query_24h(self) -> AuditWindowStats:
        return self.query_window(datetime.now(UTC) - timedelta(hours=24))

    def query_7d(self) -> AuditWindowStats:
        return self.query_window(datetime.now(UTC) - timedelta(days=7))

    def top_spend(self, n: int = 5, since: datetime | None = None) -> list[PreflightAuditEntry]:
        entries = self._read_all()
        if since is not None:
            entries = [
                e for e in entries
                if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= since
            ]
        return sorted(entries, key=lambda e: e.cost_usd, reverse=True)[:n]

    def entries_for_issue(self, issue: int) -> list[PreflightAuditEntry]:
        return [e for e in self._read_all() if e.issue == issue]


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _compute_window(entries: list[PreflightAuditEntry]) -> AuditWindowStats:
    if not entries:
        return AuditWindowStats(0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    costs = sorted(e.cost_usd for e in entries)
    walls = sorted(e.wall_clock_s for e in entries)
    resolved = sum(1 for e in entries if e.status == "resolved")
    return AuditWindowStats(
        spend_usd=sum(costs),
        attempts=len(entries),
        resolved=resolved,
        resolution_rate=resolved / len(entries),
        p50_cost_usd=_percentile(costs, 0.5),
        p95_cost_usd=_percentile(costs, 0.95),
        p50_wall_clock_s=_percentile(walls, 0.5),
        p95_wall_clock_s=_percentile(walls, 0.95),
    )
```

- [ ] **Step 1: Write failing tests** — `tests/test_preflight_audit_store.py`:

```python
"""PreflightAuditStore tests (spec §3.5, §6.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from preflight.audit import PreflightAuditEntry, PreflightAuditStore


def _entry(
    ts: str = "2026-04-25T12:00:00Z",
    issue: int = 1,
    cost: float = 1.0,
    wall: float = 60.0,
    status: str = "resolved",
) -> PreflightAuditEntry:
    return PreflightAuditEntry(
        ts=ts,
        issue=issue,
        sub_label="flaky-test-stuck",
        attempt_n=1,
        prompt_hash="sha256:abc",
        cost_usd=cost,
        wall_clock_s=wall,
        tokens=1000,
        status=status,
        pr_url=None,
        diagnosis="x",
        llm_summary="y",
    )


def test_append_and_query_for_issue(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    store.append(_entry(issue=1))
    store.append(_entry(issue=2))
    store.append(_entry(issue=1, ts="2026-04-25T13:00:00Z"))
    assert len(store.entries_for_issue(1)) == 2
    assert len(store.entries_for_issue(2)) == 1


def test_query_window_filters_by_ts(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    old = datetime.now(UTC) - timedelta(hours=48)
    fresh = datetime.now(UTC) - timedelta(hours=1)
    store.append(_entry(ts=old.isoformat().replace("+00:00", "Z")))
    store.append(_entry(ts=fresh.isoformat().replace("+00:00", "Z")))
    stats = store.query_24h()
    assert stats.attempts == 1


def test_resolution_rate(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    store.append(_entry(ts=now, status="resolved"))
    store.append(_entry(ts=now, status="needs_human"))
    store.append(_entry(ts=now, status="resolved"))
    stats = store.query_24h()
    assert stats.resolution_rate == 2 / 3


def test_top_spend(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    for c in [1.0, 5.0, 0.5, 10.0, 2.0]:
        store.append(_entry(cost=c))
    top = store.top_spend(n=3)
    assert [e.cost_usd for e in top] == [10.0, 5.0, 2.0]


def test_percentiles(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for c in [1.0, 2.0, 3.0, 4.0, 5.0]:
        store.append(_entry(ts=now, cost=c, wall=c * 10))
    stats = store.query_24h()
    assert stats.p50_cost_usd == 3.0
    assert stats.p95_cost_usd == 4.8


def test_empty_window(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    stats = store.query_24h()
    assert stats.attempts == 0
    assert stats.resolution_rate == 0.0
```

- [ ] **Step 2: Run** `uv run pytest tests/test_preflight_audit_store.py -v` → FAIL (no module).

- [ ] **Step 3: Create the two files** (`src/preflight/__init__.py`, `src/preflight/audit.py`).

- [ ] **Step 4: Run** the test → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/preflight/__init__.py src/preflight/audit.py tests/test_preflight_audit_store.py
git commit -m "feat(preflight): PreflightAuditStore with 24h/7d/top-spend queries (spec §3.5)"
```

---

## Task 4 — Sentry reverse-lookup helper + VCR contract test

**Create** `src/sentry/__init__.py` (empty file).

**Create** `src/sentry/reverse_lookup.py`:

```python
"""Sentry reverse lookup — given an issue title or fingerprint, find recent events.

Spec §3.2 / §3.6. Used by PreflightContext to enrich the agent's prompt with
recent Sentry events relevant to the escalated issue.

Failure mode: returns [] and logs a warning. Never raises to the caller —
absent Sentry data is a degraded but valid pre-flight context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("hydraflow.sentry.reverse_lookup")


@dataclass(frozen=True)
class SentryEvent:
    sentry_id: str
    title: str
    message: str
    level: str
    last_seen: str  # ISO 8601
    permalink: str
    event_count: int
    user_count: int


async def query_sentry_by_title(
    title: str,
    *,
    auth_token: str,
    org: str,
    project: str | None = None,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> list[SentryEvent]:
    """Query Sentry's issue-search API for events matching `title`.

    Returns up to `limit` events, newest first. Returns [] on any failure
    (auth, HTTP, parse). Never raises.
    """
    if not auth_token or not org:
        logger.info("Sentry reverse lookup skipped — missing creds")
        return []

    base = "https://sentry.io/api/0"
    if project:
        url = f"{base}/projects/{org}/{project}/issues/"
    else:
        url = f"{base}/organizations/{org}/issues/"

    params = {"query": title, "limit": str(limit)}
    headers = {"Authorization": f"Bearer {auth_token}"}

    own_client = client is None
    cli = client or httpx.AsyncClient(timeout=10.0)

    try:
        try:
            resp = await cli.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Sentry reverse-lookup HTTP error: %s", exc)
            return []
        except ValueError as exc:
            logger.warning("Sentry reverse-lookup parse error: %s", exc)
            return []

        return [_parse(item) for item in payload[:limit]]
    finally:
        if own_client:
            await cli.aclose()


def _parse(item: dict[str, Any]) -> SentryEvent:
    return SentryEvent(
        sentry_id=str(item.get("id", "")),
        title=str(item.get("title", "")),
        message=str(item.get("metadata", {}).get("value", "") or item.get("culprit", "")),
        level=str(item.get("level", "error")),
        last_seen=str(item.get("lastSeen", "")),
        permalink=str(item.get("permalink", "")),
        event_count=int(item.get("count", 0) or 0),
        user_count=int(item.get("userCount", 0) or 0),
    )
```

- [ ] **Step 1: Write failing test** — `tests/contracts/test_sentry_reverse_lookup.py`:

```python
"""Sentry reverse-lookup contract test (spec §3.2). VCR-driven."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sentry.reverse_lookup import query_sentry_by_title


@pytest.mark.asyncio
async def test_parses_sentry_issues_response(tmp_path: Path, httpx_mock) -> None:
    """Cassette: realistic Sentry issues-search payload → parsed events."""
    httpx_mock.add_response(
        url=httpx.URL(
            "https://sentry.io/api/0/organizations/myorg/issues/",
            params={"query": "ConnectionError: timeout", "limit": "5"},
        ),
        json=[
            {
                "id": "1234567",
                "title": "ConnectionError: timeout",
                "level": "error",
                "lastSeen": "2026-04-25T12:00:00Z",
                "permalink": "https://sentry.io/organizations/myorg/issues/1234567/",
                "count": 42,
                "userCount": 7,
                "metadata": {"value": "Connection to db.local timed out after 30s"},
                "culprit": "ingest.fetcher",
            },
        ],
    )
    out = await query_sentry_by_title(
        "ConnectionError: timeout",
        auth_token="tok",
        org="myorg",
    )
    assert len(out) == 1
    e = out[0]
    assert e.sentry_id == "1234567"
    assert e.event_count == 42
    assert e.user_count == 7
    assert e.message == "Connection to db.local timed out after 30s"


@pytest.mark.asyncio
async def test_returns_empty_on_http_error(httpx_mock) -> None:
    httpx_mock.add_response(status_code=500)
    out = await query_sentry_by_title("anything", auth_token="tok", org="myorg")
    assert out == []


@pytest.mark.asyncio
async def test_returns_empty_when_no_creds() -> None:
    out = await query_sentry_by_title("x", auth_token="", org="myorg")
    assert out == []
```

- [ ] **Step 2: Run** → FAIL (no module).

- [ ] **Step 3: Create the two files** above. Add `pytest-httpx` to dev deps if not present (likely already there — check `pyproject.toml`).

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sentry/__init__.py src/sentry/reverse_lookup.py tests/contracts/test_sentry_reverse_lookup.py
git commit -m "feat(sentry): reverse-lookup helper for auto-agent context (spec §3.2)"
```

---

## Task 5 — `PreflightContext` + `gather_context()`

**Create** `src/preflight/context.py`:

```python
"""PreflightContext — what the auto-agent knows when it starts a pre-flight.

Spec §3.2. Pure data-gathering with graceful degradation: any source that
fails returns empty/None rather than raising.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from models import EscalationContext
from preflight.audit import PreflightAuditEntry
from sentry.reverse_lookup import SentryEvent

logger = logging.getLogger("hydraflow.preflight.context")


@dataclass(frozen=True)
class IssueComment:
    author: str
    body: str
    created_at: str  # ISO 8601


@dataclass(frozen=True)
class CommitRef:
    sha: str
    title: str
    author: str
    date: str  # ISO 8601


@dataclass(frozen=True)
class PreflightContext:
    issue_number: int
    issue_body: str
    issue_comments: list[IssueComment]
    sub_label: str
    escalation_context: EscalationContext | None
    wiki_excerpts: str
    sentry_events: list[SentryEvent]
    recent_commits: list[CommitRef]
    sublabel_extras: dict[str, Any]
    prior_attempts: list[PreflightAuditEntry]


class _PRPort(Protocol):
    async def get_issue(self, number: int) -> dict[str, Any]: ...
    async def list_issue_comments(self, number: int) -> list[dict[str, Any]]: ...


class _WikiPort(Protocol):
    def query(self, repo_slug: str, keywords: list[str], **kwargs: Any) -> str: ...


async def gather_context(
    *,
    issue_number: int,
    issue_body: str,
    sub_label: str,
    pr_port: _PRPort,
    wiki_store: _WikiPort | None,
    state: Any,  # StateTracker (avoid circular import)
    audit_store: Any,  # PreflightAuditStore
    repo_slug: str,
    sentry_lookup: Any | None = None,  # callable returning list[SentryEvent]
    git_log_fn: Any | None = None,  # callable(files, since_days) -> list[CommitRef]
) -> PreflightContext:
    """Gather everything PreflightAgent needs to act."""
    # Comments — degrade gracefully
    try:
        raw_comments = await pr_port.list_issue_comments(issue_number)
        comments = [
            IssueComment(
                author=str(c.get("user", {}).get("login", "?")),
                body=str(c.get("body", "")),
                created_at=str(c.get("created_at", "")),
            )
            for c in raw_comments[-10:]
        ]
    except Exception as exc:
        logger.warning("Issue comments fetch failed for #%d: %s", issue_number, exc)
        comments = []

    # Escalation context — may legitimately be None for caretaker-loop escalations
    escalation_context: EscalationContext | None
    try:
        escalation_context = state.get_escalation_context(issue_number)
    except Exception as exc:
        logger.warning("Escalation context read failed for #%d: %s", issue_number, exc)
        escalation_context = None

    # Wiki — keyword extraction is naive on purpose; the wiki layer does its own ranking
    wiki_excerpts = ""
    if wiki_store is not None:
        try:
            keywords = _extract_keywords(issue_body)
            wiki_excerpts = wiki_store.query(repo_slug, keywords=keywords, max_chars=15_000)
        except Exception as exc:
            logger.warning("Wiki query failed for #%d: %s", issue_number, exc)

    # Sentry — degrade to []
    sentry_events: list[SentryEvent] = []
    if sentry_lookup is not None:
        try:
            sentry_events = await sentry_lookup(issue_body)
        except Exception as exc:
            logger.warning("Sentry reverse-lookup failed for #%d: %s", issue_number, exc)

    # Recent commits
    recent_commits: list[CommitRef] = []
    if git_log_fn is not None:
        try:
            files = _files_mentioned(issue_body)
            recent_commits = git_log_fn(files, 7) if files else []
        except Exception as exc:
            logger.warning("Recent-commits read failed for #%d: %s", issue_number, exc)

    # Prior attempts
    try:
        prior_attempts = audit_store.entries_for_issue(issue_number)
    except Exception as exc:
        logger.warning("Audit read failed for #%d: %s", issue_number, exc)
        prior_attempts = []

    return PreflightContext(
        issue_number=issue_number,
        issue_body=issue_body,
        issue_comments=comments,
        sub_label=sub_label,
        escalation_context=escalation_context,
        wiki_excerpts=wiki_excerpts,
        sentry_events=sentry_events,
        recent_commits=recent_commits,
        sublabel_extras={},  # populated per-sublabel in later iteration
        prior_attempts=prior_attempts,
    )


def _extract_keywords(body: str) -> list[str]:
    """Naive keyword extraction — uppercase identifiers + first 5 unique nouns."""
    import re
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", body)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= 10:
            break
    return out


def _files_mentioned(body: str) -> list[str]:
    """Extract file-like tokens (paths with / and an extension)."""
    import re
    return re.findall(r"\b[\w./_-]+\.[a-z]{1,5}\b", body)[:10]
```

- [ ] **Step 1: Write failing tests** — `tests/test_preflight_context.py`:

```python
"""PreflightContext tests (spec §3.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.audit import PreflightAuditStore
from preflight.context import PreflightContext, gather_context


@pytest.mark.asyncio
async def test_handles_missing_escalation_context(tmp_path: Path) -> None:
    """Spec §3.2 / §7: most caretaker escalations have escalation_context=None."""
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)

    ctx = await gather_context(
        issue_number=8501,
        issue_body="Body here",
        sub_label="flaky-test-stuck",
        pr_port=pr,
        wiki_store=None,
        state=state,
        audit_store=PreflightAuditStore(tmp_path),
        repo_slug="acme/widget",
    )
    assert ctx.escalation_context is None
    assert ctx.wiki_excerpts == ""
    assert ctx.sentry_events == []
    assert ctx.recent_commits == []
    assert ctx.prior_attempts == []


@pytest.mark.asyncio
async def test_wiki_query_failure_does_not_block(tmp_path: Path) -> None:
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)
    wiki = MagicMock()
    wiki.query = MagicMock(side_effect=RuntimeError("boom"))

    ctx = await gather_context(
        issue_number=1,
        issue_body="x",
        sub_label="x",
        pr_port=pr,
        wiki_store=wiki,
        state=state,
        audit_store=PreflightAuditStore(tmp_path),
        repo_slug="x/y",
    )
    assert ctx.wiki_excerpts == ""


@pytest.mark.asyncio
async def test_prior_attempts_loaded(tmp_path: Path) -> None:
    from preflight.audit import PreflightAuditEntry
    audit = PreflightAuditStore(tmp_path)
    audit.append(PreflightAuditEntry(
        ts="2026-04-25T12:00:00Z", issue=42, sub_label="x", attempt_n=1,
        prompt_hash="h", cost_usd=1.0, wall_clock_s=10.0, tokens=100,
        status="needs_human", pr_url=None, diagnosis="d", llm_summary="s",
    ))
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)

    ctx = await gather_context(
        issue_number=42, issue_body="x", sub_label="x",
        pr_port=pr, wiki_store=None, state=state,
        audit_store=audit, repo_slug="x/y",
    )
    assert len(ctx.prior_attempts) == 1
    assert ctx.prior_attempts[0].attempt_n == 1
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Create `src/preflight/context.py`** above.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add src/preflight/context.py tests/test_preflight_context.py
git commit -m "feat(preflight): PreflightContext + gather_context (spec §3.2)"
```

---

## Task 6 — `PreflightDecision`

**Create** `src/preflight/decision.py`:

```python
"""PreflightDecision — pure label-state mapping for AutoAgentPreflightLoop.

Spec §2.2, §2.3, §7. Translates a PreflightResult into label operations
applied via PRPort. Idempotent: re-runs on the same input are no-ops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("hydraflow.preflight.decision")


@dataclass(frozen=True)
class PreflightResult:
    status: str  # "resolved" | "needs_human" | "fatal" | "pr_failed" | "cost_exceeded" | "timeout"
    pr_url: str | None
    diagnosis: str
    cost_usd: float
    wall_clock_s: float
    tokens: int


class _PRPort(Protocol):
    async def add_labels(self, issue: int, labels: list[str]) -> None: ...
    async def remove_labels(self, issue: int, labels: list[str]) -> None: ...
    async def add_comment(self, issue: int, body: str) -> None: ...


# Status → (labels-to-add, labels-to-remove)
_LABEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    "resolved": ([], ["hitl-escalation"]),
    "needs_human": (["human-required"], []),
    "fatal": (["human-required", "auto-agent-fatal"], []),
    "pr_failed": (["human-required", "auto-agent-pr-failed"], []),
    "cost_exceeded": (["human-required", "cost-exceeded"], []),
    "timeout": (["human-required", "timeout"], []),
}


async def apply_decision(
    *,
    issue_number: int,
    sub_label: str,
    result: PreflightResult,
    pr_port: _PRPort,
    state: Any,
    max_attempts: int,
) -> dict[str, Any]:
    """Apply labels + comment for a single attempt's result."""
    # Race-detection: re-read attempts to ensure no concurrent bumper.
    current_attempts = state.get_auto_agent_attempts(issue_number)

    add, remove = _LABEL_MAP.get(result.status, _LABEL_MAP["needs_human"])

    # Exhaustion check — if this attempt brought us to the cap and it didn't resolve,
    # flag as exhausted on top of the normal needs_human/fatal label set.
    exhausted = (
        result.status != "resolved"
        and current_attempts >= max_attempts
    )
    if exhausted:
        add = list(add) + ["auto-agent-exhausted"]

    if add:
        await pr_port.add_labels(issue_number, add)
    if remove:
        await pr_port.remove_labels(issue_number, remove)

    comment = _format_comment(sub_label, result, current_attempts, exhausted)
    if comment:
        await pr_port.add_comment(issue_number, comment)

    return {
        "issue": issue_number,
        "status": result.status,
        "exhausted": exhausted,
        "added": add,
        "removed": remove,
    }


def _format_comment(
    sub_label: str,
    result: PreflightResult,
    attempts: int,
    exhausted: bool,
) -> str:
    if result.status == "resolved":
        pr_link = f" PR: {result.pr_url}" if result.pr_url else ""
        return (
            f"**Auto-Agent resolved this issue** (attempt {attempts}, "
            f"sub-label `{sub_label}`, ${result.cost_usd:.2f}, "
            f"{result.wall_clock_s:.0f}s).{pr_link}\n\n"
            f"{result.diagnosis}"
        )
    suffix = " — **3 attempts exhausted, no further auto-agent retries**" if exhausted else ""
    return (
        f"**Auto-Agent attempt {attempts} → `{result.status}`** "
        f"(sub-label `{sub_label}`, ${result.cost_usd:.2f}, "
        f"{result.wall_clock_s:.0f}s){suffix}.\n\n"
        f"**Diagnosis:**\n{result.diagnosis}"
    )
```

- [ ] **Step 1: Write failing tests** — `tests/test_preflight_decision.py`:

```python
"""PreflightDecision tests (spec §2.2, §2.3, §7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.decision import PreflightResult, apply_decision


def _result(status: str, **kwargs) -> PreflightResult:
    return PreflightResult(
        status=status,
        pr_url=kwargs.get("pr_url"),
        diagnosis=kwargs.get("diagnosis", "diag"),
        cost_usd=kwargs.get("cost_usd", 1.0),
        wall_clock_s=kwargs.get("wall_clock_s", 60.0),
        tokens=kwargs.get("tokens", 1000),
    )


@pytest.mark.asyncio
async def test_resolved_removes_hitl_escalation() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    out = await apply_decision(
        issue_number=42, sub_label="flaky-test-stuck",
        result=_result("resolved", pr_url="https://x/pr/1"),
        pr_port=pr, state=state, max_attempts=3,
    )
    pr.remove_labels.assert_awaited_with(42, ["hitl-escalation"])
    pr.add_comment.assert_awaited()
    assert out["status"] == "resolved"


@pytest.mark.asyncio
async def test_needs_human_adds_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42, sub_label="flaky-test-stuck",
        result=_result("needs_human"),
        pr_port=pr, state=state, max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required"])


@pytest.mark.asyncio
async def test_fatal_adds_paired_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42, sub_label="x",
        result=_result("fatal"),
        pr_port=pr, state=state, max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required", "auto-agent-fatal"])


@pytest.mark.asyncio
async def test_exhaustion_appends_label() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    out = await apply_decision(
        issue_number=42, sub_label="x",
        result=_result("needs_human"),
        pr_port=pr, state=state, max_attempts=3,
    )
    assert "auto-agent-exhausted" in out["added"]
    pr.add_labels.assert_awaited_with(42, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_resolved_at_cap_does_not_mark_exhausted() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    out = await apply_decision(
        issue_number=42, sub_label="x",
        result=_result("resolved"),
        pr_port=pr, state=state, max_attempts=3,
    )
    assert "auto-agent-exhausted" not in out["added"]


@pytest.mark.asyncio
async def test_cost_exceeded_pairs_correctly() -> None:
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    await apply_decision(
        issue_number=42, sub_label="x",
        result=_result("cost_exceeded"),
        pr_port=pr, state=state, max_attempts=3,
    )
    pr.add_labels.assert_awaited_with(42, ["human-required", "cost-exceeded"])
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Create `src/preflight/decision.py`** above.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add src/preflight/decision.py tests/test_preflight_decision.py
git commit -m "feat(preflight): PreflightDecision pure label logic (spec §2.2)"
```

---

## Task 7 — Shared prompt envelope + `_default.md`

**Create** `prompts/auto_agent/_envelope.md`:

```markdown
# Auto-Agent — Shared Prompt Envelope

You are {persona}.

You have been dispatched to attempt autonomous resolution of an issue that
HydraFlow's pipeline escalated. If you can fix it, do. If you cannot, return
a precise diagnosis so a human can pick up where you left off.

## Issue context

- **Issue:** #{issue_number}
- **Sub-label:** {sub_label}
- **Repo:** {repo_slug}
- **Worktree:** {worktree_path}

### Issue body

{issue_body}

### Recent comments

{issue_comments_block}

### Escalation context

{escalation_context_block}

### Relevant wiki entries

{wiki_excerpts_block}

### Recent Sentry events

{sentry_events_block}

### Recent commits touching mentioned files

{recent_commits_block}

## Previous attempts

{prior_attempts_block}

## Tool restrictions

You are NOT permitted to:

- Modify any file under `.github/workflows/`
- Modify branch protection or repo settings
- Force-push, delete branches, or rewrite history
- Read or write any file matching the secrets-allowlist (`.env`, `secrets.*`, etc.)
- Approve or merge your own PR
- Modify `src/principles_audit_loop.py`, `src/auto_agent_preflight_loop.py`, or
  any ADR-0044 / ADR-0049 implementation file (recursion guard — you must not
  modify the system that judges or governs you)

These restrictions are enforced at the worktree-tool layer; calling forbidden
tools will return errors. Do not attempt to circumvent them.

## Decision protocol

You MUST terminate by returning ONE of:

1. **`resolved`** — you made the change, ran the tests, pushed the branch, and
   opened a PR. Provide the PR URL and a brief diagnosis describing what was
   wrong and how you fixed it.

2. **`needs_human`** — you investigated but cannot resolve this autonomously.
   Provide a precise diagnosis: what's wrong, what you tried, what you ruled
   out, and a specific question or action for the human.

Format your final response as:

```
<status>resolved</status>
<pr_url>https://...</pr_url>
<diagnosis>
... your diagnosis or fix summary ...
</diagnosis>
```

Or:

```
<status>needs_human</status>
<diagnosis>
... your diagnosis ...
</diagnosis>
```

Be precise. A vague diagnosis wastes the human's time.
```

**Create** `prompts/auto_agent/_default.md`:

```markdown
# Auto-Agent — Default Playbook

{{> _envelope.md}}

## Default sub-label guidance

You're picking up an escalation that doesn't have a specialized playbook. Read
the escalation context (if present), look at what was attempted in previous
attempts, and try the obvious recovery action for whatever phase produced this
escalation.

If the context indicates a CI failure, look at the failing test output, fix the
test or the production code, and push.

If the context indicates a phase failure (review, plan, implement), read what
the phase tried, understand why it failed, and either: (a) make the small
correction the phase needed, or (b) escalate with a specific recommendation.

When in doubt, escalate cleanly with a specific question. A two-sentence
diagnosis a human can act on is more valuable than a sloppy half-fix.
```

- [ ] **Step 1: Just create both files.** No code yet — these are content. (No test for prompt content; rendering tests live in Task 9.)

- [ ] **Step 2: Commit**

```bash
git add prompts/auto_agent/_envelope.md prompts/auto_agent/_default.md
git commit -m "feat(prompts): auto-agent shared envelope + default prompt (spec §4.1)"
```

---

## Task 8 — Sub-label-specific prompt files

**Create** the 9 sub-label prompt files at `prompts/auto_agent/<sub-label>.md`. Each starts with `{{> _envelope.md}}` and adds a focused playbook section. Use spec §4.2 routing-table descriptions verbatim as the playbook content.

Files (one per sub-label):

1. `prompts/auto_agent/flaky-test-stuck.md`
2. `prompts/auto_agent/revert-conflict.md`
3. `prompts/auto_agent/rc-red-bisect-exhausted.md`
4. `prompts/auto_agent/fake-drift-stuck.md`
5. `prompts/auto_agent/fake-coverage-stuck.md`
6. `prompts/auto_agent/wiki-rot-stuck.md`
7. `prompts/auto_agent/rc-duration-stuck.md`
8. `prompts/auto_agent/skill-prompt-stuck.md`
9. `prompts/auto_agent/trust-loop-anomaly.md`

**Template** (apply to each — substitute the playbook text from spec §4.2):

```markdown
# Auto-Agent — {sub-label} Playbook

{{> _envelope.md}}

## Sub-label: {sub-label}

{spec-§4.2-playbook-text-verbatim}

## Specific guidance for this sub-label

{2-4 paragraphs of detail expanding the spec stance, written in second person}
```

Example, fully-formed — `prompts/auto_agent/flaky-test-stuck.md`:

```markdown
# Auto-Agent — flaky-test-stuck Playbook

{{> _envelope.md}}

## Sub-label: flaky-test-stuck

Read the test, the recent flake history, the git blame on the test file. Most
flakes are timing or order-dependent — fix the test, not the production code.
If you can't reproduce, mark `@pytest.mark.flaky(reruns=3)` with a clear comment
and open a follow-up issue.

## Specific guidance

The flake-tracker loop has been retrying this test repair for several attempts;
its prior diagnoses are visible in the escalation context (if any) and in the
prior attempts block.

Order of operations:

1. Read the test file. Look for: time.sleep(), wall-clock comparisons, ordering
   assumptions in async tests, shared-state across tests in the same module.
2. Run the test in isolation 5 times (`pytest path::test_name -v --count=5`).
   If it passes 5/5, it's an order/state issue — find the leak.
3. If it still flakes in isolation, the test logic itself is wrong. Fix it.
4. If you cannot identify the cause within a reasonable budget, mark
   `@pytest.mark.flaky(reruns=3, reruns_delay=2)` with a comment linking back
   to the original issue, open a follow-up `tech-debt` issue, and return
   `resolved`. The flaky decorator is a stop-gap, not a permanent fix.

Do NOT mark a test flaky if a one-line fix is obvious. Do NOT change production
code unless the test was correct and caught a real race.
```

- [ ] **Step 1: Create all 9 files** using the template + spec §4.2 stance text. No test required (prompt rendering tested in Task 9).

- [ ] **Step 2: Commit**

```bash
git add prompts/auto_agent/
git commit -m "feat(prompts): nine auto-agent sub-label playbooks (spec §4.2)"
```

---

## Task 9 — `AutoAgentRunner` + `PreflightAgent`

**Create** `src/preflight/runner.py`:

```python
"""AutoAgentRunner — thin HITLRunner subclass for auto-agent invocations.

Spec §3.3, §10 (decision: subclass HITLRunner with prompt-envelope override).
Reuses HITLRunner's worktree-spawn + tool-restriction infrastructure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hitl_runner import HITLRunner


_PROMPT_DIR = Path(__file__).parent.parent.parent / "prompts" / "auto_agent"


def render_prompt(
    *,
    sub_label: str,
    persona: str,
    issue_number: int,
    repo_slug: str,
    worktree_path: str,
    issue_body: str,
    issue_comments_block: str,
    escalation_context_block: str,
    wiki_excerpts_block: str,
    sentry_events_block: str,
    recent_commits_block: str,
    prior_attempts_block: str,
) -> str:
    """Load the sub-label prompt file (or _default.md) + envelope, render."""
    prompt_path = _PROMPT_DIR / f"{sub_label}.md"
    if not prompt_path.exists():
        prompt_path = _PROMPT_DIR / "_default.md"

    content = prompt_path.read_text(encoding="utf-8")

    # Inline the envelope partial — simple {{> _envelope.md}} substitution.
    envelope_path = _PROMPT_DIR / "_envelope.md"
    envelope = envelope_path.read_text(encoding="utf-8")
    content = content.replace("{{> _envelope.md}}", envelope)

    # Substitute fields
    return content.format(
        persona=persona,
        issue_number=issue_number,
        sub_label=sub_label,
        repo_slug=repo_slug,
        worktree_path=worktree_path,
        issue_body=issue_body,
        issue_comments_block=issue_comments_block,
        escalation_context_block=escalation_context_block,
        wiki_excerpts_block=wiki_excerpts_block,
        sentry_events_block=sentry_events_block,
        recent_commits_block=recent_commits_block,
        prior_attempts_block=prior_attempts_block,
    )


def render_blocks(
    *,
    issue_comments: list,
    escalation_context: Any | None,
    wiki_excerpts: str,
    sentry_events: list,
    recent_commits: list,
    prior_attempts: list,
) -> dict[str, str]:
    """Render the structured-block strings injected into the prompt."""
    return {
        "issue_comments_block": _render_comments(issue_comments),
        "escalation_context_block": _render_escalation_context(escalation_context),
        "wiki_excerpts_block": wiki_excerpts or "(no relevant wiki entries found)",
        "sentry_events_block": _render_sentry(sentry_events),
        "recent_commits_block": _render_commits(recent_commits),
        "prior_attempts_block": _render_prior_attempts(prior_attempts),
    }


def _render_comments(comments: list) -> str:
    if not comments:
        return "(no comments)"
    return "\n\n".join(f"- {c.author} ({c.created_at}): {c.body[:500]}" for c in comments)


def _render_escalation_context(ctx: Any | None) -> str:
    if ctx is None:
        return (
            "(no structured escalation context — operate from the issue body, "
            "sub-label, wiki, sentry, and recent commits)"
        )
    # EscalationContext is Pydantic — render its dict form
    try:
        return "```\n" + ctx.model_dump_json(indent=2) + "\n```"
    except AttributeError:
        return f"```\n{ctx!r}\n```"


def _render_sentry(events: list) -> str:
    if not events:
        return "(no recent Sentry events match)"
    return "\n".join(
        f"- {e.title} ({e.event_count} events, {e.user_count} users) — {e.permalink}"
        for e in events
    )


def _render_commits(commits: list) -> str:
    if not commits:
        return "(no recent commits to mentioned files)"
    return "\n".join(f"- {c.sha[:8]} {c.title} — {c.author} {c.date}" for c in commits)


def _render_prior_attempts(attempts: list) -> str:
    if not attempts:
        return "(no prior attempts on this issue — this is attempt 1)"
    out = []
    for i, a in enumerate(attempts, 1):
        out.append(
            f"### Attempt {a.attempt_n} ({a.ts}) → {a.status}\n"
            f"**Diagnosis:** {a.diagnosis}\n"
            f"**LLM summary:** {a.llm_summary}"
        )
    return "\n\n".join(out)


_TAG_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)


def parse_agent_response(text: str) -> dict[str, str]:
    """Parse <status>...</status> + <pr_url>...</pr_url> + <diagnosis>...</diagnosis>."""
    tags = {m.group(1): m.group(2).strip() for m in _TAG_RE.finditer(text)}
    return {
        "status": tags.get("status", "needs_human"),
        "pr_url": tags.get("pr_url") or None,
        "diagnosis": tags.get("diagnosis", text.strip()),
    }
```

**Create** `src/preflight/agent.py`:

```python
"""PreflightAgent — spawns AutoAgentRunner + caps + cost telemetry.

Spec §3.3, §5.1.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from preflight.context import PreflightContext
from preflight.decision import PreflightResult
from preflight.runner import parse_agent_response, render_blocks, render_prompt

logger = logging.getLogger("hydraflow.preflight.agent")


@dataclass
class PreflightAgentDeps:
    persona: str
    cost_cap_usd: float | None
    wall_clock_cap_s: int | None
    spawn_fn: Any  # callable(prompt, worktree_path) -> PreflightSpawn (see test for shape)


@dataclass(frozen=True)
class PreflightSpawn:
    """Returned by spawn_fn — represents the running subprocess + cost meter."""
    process: Any  # subprocess.Process or asyncio task
    output_text: str  # populated after wait()
    cost_usd: float
    tokens: int
    crashed: bool


async def run_preflight(
    *,
    context: PreflightContext,
    repo_slug: str,
    worktree_path: str,
    deps: PreflightAgentDeps,
) -> PreflightResult:
    """Run one auto-agent attempt; return the result."""
    blocks = render_blocks(
        issue_comments=context.issue_comments,
        escalation_context=context.escalation_context,
        wiki_excerpts=context.wiki_excerpts,
        sentry_events=context.sentry_events,
        recent_commits=context.recent_commits,
        prior_attempts=context.prior_attempts,
    )
    prompt = render_prompt(
        sub_label=context.sub_label,
        persona=deps.persona,
        issue_number=context.issue_number,
        repo_slug=repo_slug,
        worktree_path=worktree_path,
        issue_body=context.issue_body,
        **blocks,
    )

    start = time.monotonic()
    try:
        spawn = await deps.spawn_fn(prompt=prompt, worktree_path=worktree_path)
    except Exception as exc:
        logger.exception("PreflightAgent spawn failed: %s", exc)
        return PreflightResult(
            status="fatal",
            pr_url=None,
            diagnosis=f"Subprocess spawn failed: {exc}",
            cost_usd=0.0,
            wall_clock_s=time.monotonic() - start,
            tokens=0,
        )

    wall_s = time.monotonic() - start

    if spawn.crashed:
        return PreflightResult(
            status="fatal",
            pr_url=None,
            diagnosis=f"Subprocess crashed. Partial output: {spawn.output_text[-1000:]}",
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
        )

    # Cap checks (post-hoc — caps were enforced inside spawn_fn or by watchers)
    if deps.cost_cap_usd is not None and spawn.cost_usd > deps.cost_cap_usd:
        return PreflightResult(
            status="cost_exceeded",
            pr_url=None,
            diagnosis=f"Cost cap (${deps.cost_cap_usd:.2f}) hit. Partial output: {spawn.output_text[-1000:]}",
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
        )
    if deps.wall_clock_cap_s is not None and wall_s > deps.wall_clock_cap_s:
        return PreflightResult(
            status="timeout",
            pr_url=None,
            diagnosis=f"Wall-clock cap ({deps.wall_clock_cap_s}s) hit. Partial output: {spawn.output_text[-1000:]}",
            cost_usd=spawn.cost_usd,
            wall_clock_s=wall_s,
            tokens=spawn.tokens,
        )

    parsed = parse_agent_response(spawn.output_text)
    return PreflightResult(
        status=parsed["status"] if parsed["status"] in {"resolved", "needs_human"} else "needs_human",
        pr_url=parsed["pr_url"],
        diagnosis=parsed["diagnosis"],
        cost_usd=spawn.cost_usd,
        wall_clock_s=wall_s,
        tokens=spawn.tokens,
    )


def hash_prompt(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 1: Write failing tests** — `tests/test_preflight_agent.py`:

```python
"""PreflightAgent tests (spec §3.3, §5.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from preflight.agent import (
    PreflightAgentDeps, PreflightSpawn, hash_prompt, run_preflight,
)
from preflight.context import PreflightContext


def _ctx(sub_label: str = "flaky-test-stuck") -> PreflightContext:
    return PreflightContext(
        issue_number=42, issue_body="body", issue_comments=[],
        sub_label=sub_label, escalation_context=None,
        wiki_excerpts="", sentry_events=[], recent_commits=[],
        sublabel_extras={}, prior_attempts=[],
    )


@pytest.mark.asyncio
async def test_resolved_response_parsed() -> None:
    spawn_fn = AsyncMock(return_value=PreflightSpawn(
        process=None,
        output_text="<status>resolved</status>\n<pr_url>https://x/pr/1</pr_url>\n<diagnosis>fixed it</diagnosis>",
        cost_usd=1.0, tokens=1000, crashed=False,
    ))
    deps = PreflightAgentDeps(
        persona="x", cost_cap_usd=None, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    out = await run_preflight(context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps)
    assert out.status == "resolved"
    assert out.pr_url == "https://x/pr/1"
    assert out.diagnosis == "fixed it"


@pytest.mark.asyncio
async def test_subprocess_crash_returns_fatal() -> None:
    spawn_fn = AsyncMock(return_value=PreflightSpawn(
        process=None, output_text="partial output", cost_usd=0.5, tokens=500, crashed=True,
    ))
    deps = PreflightAgentDeps(
        persona="x", cost_cap_usd=None, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    out = await run_preflight(context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps)
    assert out.status == "fatal"
    assert "Subprocess crashed" in out.diagnosis


@pytest.mark.asyncio
async def test_spawn_exception_returns_fatal() -> None:
    spawn_fn = AsyncMock(side_effect=RuntimeError("oom"))
    deps = PreflightAgentDeps(
        persona="x", cost_cap_usd=None, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    out = await run_preflight(context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps)
    assert out.status == "fatal"
    assert "spawn failed" in out.diagnosis


@pytest.mark.asyncio
async def test_cost_cap_returns_cost_exceeded() -> None:
    spawn_fn = AsyncMock(return_value=PreflightSpawn(
        process=None, output_text="<status>resolved</status><diagnosis>x</diagnosis>",
        cost_usd=10.0, tokens=10000, crashed=False,
    ))
    deps = PreflightAgentDeps(
        persona="x", cost_cap_usd=5.0, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    out = await run_preflight(context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps)
    assert out.status == "cost_exceeded"


def test_hash_prompt_stable() -> None:
    assert hash_prompt("abc") == hash_prompt("abc")
    assert hash_prompt("abc") != hash_prompt("def")
    assert hash_prompt("abc").startswith("sha256:")


@pytest.mark.asyncio
async def test_unparseable_response_falls_back_to_needs_human() -> None:
    spawn_fn = AsyncMock(return_value=PreflightSpawn(
        process=None, output_text="garbage no tags", cost_usd=1.0, tokens=100, crashed=False,
    ))
    deps = PreflightAgentDeps(
        persona="x", cost_cap_usd=None, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    out = await run_preflight(context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps)
    assert out.status == "needs_human"
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Create `src/preflight/runner.py`** and `src/preflight/agent.py`** above.

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Add a render-test** in `tests/test_preflight_runner.py`:

```python
"""PreflightRunner prompt-rendering tests."""

from __future__ import annotations

from preflight.runner import (
    parse_agent_response, render_blocks, render_prompt,
)


def test_persona_and_fields_substituted() -> None:
    out = render_prompt(
        sub_label="flaky-test-stuck",
        persona="Travis",
        issue_number=42,
        repo_slug="acme/widget",
        worktree_path="/tmp/wt",
        issue_body="body",
        issue_comments_block="(no comments)",
        escalation_context_block="(none)",
        wiki_excerpts_block="(no wiki)",
        sentry_events_block="(no sentry)",
        recent_commits_block="(no commits)",
        prior_attempts_block="(none)",
    )
    assert "You are Travis" in out
    assert "#42" in out
    assert "acme/widget" in out
    assert "{{> _envelope.md}}" not in out  # envelope was inlined


def test_default_fallback_for_unknown_sub_label() -> None:
    out = render_prompt(
        sub_label="totally-made-up-label",
        persona="x", issue_number=1, repo_slug="r/s", worktree_path="/tmp",
        issue_body="b", issue_comments_block="x", escalation_context_block="x",
        wiki_excerpts_block="x", sentry_events_block="x", recent_commits_block="x",
        prior_attempts_block="x",
    )
    assert "Default Playbook" in out


def test_parse_agent_response_resolved() -> None:
    out = parse_agent_response(
        "<status>resolved</status><pr_url>https://x</pr_url><diagnosis>did it</diagnosis>"
    )
    assert out["status"] == "resolved"
    assert out["pr_url"] == "https://x"


def test_parse_agent_response_needs_human() -> None:
    out = parse_agent_response("<status>needs_human</status><diagnosis>nope</diagnosis>")
    assert out["status"] == "needs_human"
    assert out["pr_url"] is None
```

- [ ] **Step 6: Run** → PASS.

- [ ] **Step 7: Commit**

```bash
git add src/preflight/runner.py src/preflight/agent.py tests/test_preflight_agent.py tests/test_preflight_runner.py
git commit -m "feat(preflight): PreflightAgent + AutoAgentRunner prompt renderer (spec §3.3)"
```

---

## Task 10 — `AutoAgentPreflightLoop` scaffolding (registers, gates, no agent yet)

**Create** `src/auto_agent_preflight_loop.py` (skeleton — full pipeline lands in Task 11):

```python
"""AutoAgentPreflightLoop — intercepts hitl-escalation issues for auto-resolution.

Spec §1–§11. Polls hitl-escalation items, runs PreflightAgent in attempt
sequence, applies PreflightDecision to the result, records audit + spend.

Layered kill-switch (ADR-0049): in-body enabled_cb gate at top of _do_work.
Sequential single-issue-per-tick. Daily-budget gate. Sub-label deny-list.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.auto_agent_preflight")


class AutoAgentPreflightLoop(BaseBackgroundLoop):
    """Intercepts hitl-escalation issues for auto-agent pre-flight."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: Any,  # StateTracker
        pr_manager: Any,  # PRPort
        wiki_store: Any | None,
        audit_store: Any,  # PreflightAuditStore
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="auto_agent_preflight",
            deps=deps,
            run_on_startup=False,
        )
        self._config = config
        self._state = state
        self._prs = pr_manager
        self._wiki_store = wiki_store
        self._audit_store = audit_store

    def _get_default_interval(self) -> int:
        return self._config.auto_agent_preflight_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch gate (universal mandate).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Daily-budget gate (None = unlimited).
        cap = self._config.auto_agent_daily_budget_usd
        if cap is not None:
            today = datetime.now(UTC).date().isoformat()
            spend = self._state.get_auto_agent_daily_spend(today)
            if spend >= cap:
                return {"status": "budget_exceeded", "spend_usd": spend, "cap_usd": cap}

        # Pipeline lands in Task 11.
        return {"status": "ok", "issues_processed": 0}
```

- [ ] **Step 1: Write failing tests** — `tests/test_auto_agent_preflight_loop.py`:

```python
"""AutoAgentPreflightLoop scaffolding tests (spec §2.1, §5.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True, **config_overrides):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    state = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    audit = MagicMock()
    loop = AutoAgentPreflightLoop(
        config=deps.config, state=state, pr_manager=pr,
        wiki_store=None, audit_store=audit, deps=deps.loop_deps,
    )
    return loop, state


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "auto_agent_preflight"


def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, auto_agent_preflight_interval=180)
    assert loop._get_default_interval() == 180


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_daily_budget_gate(tmp_path: Path) -> None:
    loop, state = _make_loop(tmp_path, auto_agent_daily_budget_usd=50.0)
    state.get_auto_agent_daily_spend = MagicMock(return_value=51.0)
    result = await loop._do_work()
    assert result["status"] == "budget_exceeded"
    assert result["cap_usd"] == 50.0


@pytest.mark.asyncio
async def test_no_cap_passes_gate(tmp_path: Path) -> None:
    loop, state = _make_loop(tmp_path)  # cap = None
    state.get_auto_agent_daily_spend = MagicMock(return_value=999.0)
    result = await loop._do_work()
    assert result["status"] == "ok"
```

- [ ] **Step 2: Run** → FAIL (no module).
- [ ] **Step 3: Create the loop file** above.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add src/auto_agent_preflight_loop.py tests/test_auto_agent_preflight_loop.py
git commit -m "feat(loop): AutoAgentPreflightLoop scaffolding + kill-switch + budget gate (spec §2.1)"
```

---

## Task 11 — Wire the `_do_work` pipeline (poll → context → agent → decision → audit)

**Modify** `src/auto_agent_preflight_loop.py` — replace the `_do_work` body with the full pipeline. Add helper methods.

```python
    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        cap = self._config.auto_agent_daily_budget_usd
        if cap is not None:
            today = datetime.now(UTC).date().isoformat()
            spend = self._state.get_auto_agent_daily_spend(today)
            if spend >= cap:
                return {"status": "budget_exceeded", "spend_usd": spend, "cap_usd": cap}

        # Poll for hitl-escalation issues that don't already have human-required.
        issues = await self._poll_eligible_issues()
        if not issues:
            return {"status": "ok", "issues_processed": 0}

        # Sequential single-issue-per-tick.
        issue = issues[0]
        result = await self._process_one(issue)
        return {
            "status": "ok",
            "issues_processed": 1,
            "result_status": result.get("status"),
        }

    async def _poll_eligible_issues(self) -> list[dict[str, Any]]:
        """Return open hitl-escalation issues lacking human-required."""
        try:
            raw = await self._prs.list_issues_by_label("hitl-escalation")
        except Exception as exc:
            logger.warning("Eligible-issue poll failed: %s", exc)
            return []
        return [
            issue for issue in raw
            if "human-required" not in {l.get("name", "") for l in issue.get("labels", [])}
        ]

    async def _process_one(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Run one full pre-flight attempt for a single issue."""
        from preflight.agent import PreflightAgentDeps, hash_prompt, run_preflight
        from preflight.audit import PreflightAuditEntry
        from preflight.context import gather_context
        from preflight.decision import apply_decision

        issue_number = int(issue.get("number", 0))
        issue_body = str(issue.get("body", "") or "")
        labels = {l.get("name", "") for l in issue.get("labels", [])}
        sub_labels = labels - {"hitl-escalation"}
        sub_label = next(iter(sub_labels), "_default")

        # Sub-label deny-list.
        if sub_label in self._config.auto_agent_skip_sublabels:
            await self._prs.add_labels(issue_number, ["human-required"])
            await self._audit_store.append(_skip_audit(issue_number, sub_label, "deny_list"))
            return {"status": "skipped_deny_list"}

        # Attempt-cap check.
        attempts = self._state.get_auto_agent_attempts(issue_number)
        if attempts >= self._config.auto_agent_max_attempts:
            await self._prs.add_labels(issue_number, ["human-required", "auto-agent-exhausted"])
            return {"status": "skipped_exhausted"}

        # Gather context.
        ctx = await gather_context(
            issue_number=issue_number,
            issue_body=issue_body,
            sub_label=sub_label,
            pr_port=self._prs,
            wiki_store=self._wiki_store,
            state=self._state,
            audit_store=self._audit_store,
            repo_slug=self._config.repo_slug if hasattr(self._config, "repo_slug") else "",
        )

        # Bump attempts atomically before spawning.
        attempt_n = self._state.bump_auto_agent_attempts(issue_number)

        # Spawn agent.
        spawn_fn = self._build_spawn_fn(issue_number)
        deps = PreflightAgentDeps(
            persona=self._config.auto_agent_persona,
            cost_cap_usd=self._config.auto_agent_cost_cap_usd,
            wall_clock_cap_s=self._config.auto_agent_wall_clock_cap_s,
            spawn_fn=spawn_fn,
        )
        worktree_path = await self._resolve_worktree(issue_number)
        result = await run_preflight(
            context=ctx, repo_slug="", worktree_path=worktree_path, deps=deps,
        )

        # Apply decision.
        decision_out = await apply_decision(
            issue_number=issue_number,
            sub_label=sub_label,
            result=result,
            pr_port=self._prs,
            state=self._state,
            max_attempts=self._config.auto_agent_max_attempts,
        )

        # Append audit.
        await self._audit_store.append(PreflightAuditEntry(
            ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            issue=issue_number,
            sub_label=sub_label,
            attempt_n=attempt_n,
            prompt_hash=hash_prompt(""),  # populated by spawn_fn in real impl
            cost_usd=result.cost_usd,
            wall_clock_s=result.wall_clock_s,
            tokens=result.tokens,
            status=result.status,
            pr_url=result.pr_url,
            diagnosis=result.diagnosis,
            llm_summary=result.diagnosis[:500],
        ))

        # Update daily spend cache.
        today = datetime.now(UTC).date().isoformat()
        self._state.add_auto_agent_daily_spend(today, result.cost_usd)

        return {"status": result.status, "issue": issue_number}

    def _build_spawn_fn(self, issue_number: int):
        """Returns the actual subprocess-spawning callable. Replaced in tests."""
        # In production: spawns AutoAgentRunner subprocess.
        # In tests: monkeypatched to return a fake PreflightSpawn.
        # Placeholder until full HITLRunner integration is wired.
        from preflight.agent import PreflightSpawn
        async def _fake(prompt: str, worktree_path: str) -> PreflightSpawn:
            return PreflightSpawn(
                process=None, output_text="<status>needs_human</status><diagnosis>not yet wired</diagnosis>",
                cost_usd=0.0, tokens=0, crashed=False,
            )
        return _fake

    async def _resolve_worktree(self, issue_number: int) -> str:
        """Return worktree path for the issue, or main repo as fallback."""
        # Real impl uses WorkspacePort. Placeholder returns repo_root.
        return str(self._config.repo_root)


def _skip_audit(issue: int, sub_label: str, reason: str):
    from preflight.audit import PreflightAuditEntry
    return PreflightAuditEntry(
        ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        issue=issue, sub_label=sub_label, attempt_n=0,
        prompt_hash="", cost_usd=0.0, wall_clock_s=0.0, tokens=0,
        status="skipped",
        pr_url=None, diagnosis=f"skipped: {reason}",
        llm_summary=f"skipped: {reason}",
    )
```

- [ ] **Step 1: Append integration tests** to `tests/test_auto_agent_preflight_loop.py`:

```python
@pytest.mark.asyncio
async def test_no_eligible_issues(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    loop._prs.list_issues_by_label = AsyncMock(return_value=[])
    result = await loop._do_work()
    assert result == {"status": "ok", "issues_processed": 0}


@pytest.mark.asyncio
async def test_skips_human_required_already_set(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    loop._prs.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "human-required"},
        ]},
    ])
    eligible = await loop._poll_eligible_issues()
    assert eligible == []


@pytest.mark.asyncio
async def test_deny_list_bypasses_agent(tmp_path: Path) -> None:
    loop, state = _make_loop(tmp_path)
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    loop._prs.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "principles-stuck"},
        ]},
    ])
    result = await loop._do_work()
    loop._prs.add_labels.assert_awaited_with(1, ["human-required"])
    assert result["result_status"] == "skipped_deny_list"


@pytest.mark.asyncio
async def test_attempt_cap_marks_exhausted(tmp_path: Path) -> None:
    loop, state = _make_loop(tmp_path)
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    loop._prs.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "flaky-test-stuck"},
        ]},
    ])
    result = await loop._do_work()
    loop._prs.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-exhausted"])
    assert result["result_status"] == "skipped_exhausted"
```

- [ ] **Step 2: Run** → FAIL (pipeline not wired).
- [ ] **Step 3: Apply the `_do_work` rewrite + helper methods** above.
- [ ] **Step 4: Run** → PASS (all tests in this file).
- [ ] **Step 5: Commit**

```bash
git add src/auto_agent_preflight_loop.py tests/test_auto_agent_preflight_loop.py
git commit -m "feat(loop): wire PreflightContext + Agent + Decision pipeline (spec §2.3)"
```

---

## Task 12 — Five-checkpoint wiring (service_registry, orchestrator, UI constants, _INTERVAL_BOUNDS, scenario catalog)

**Modify** `src/service_registry.py`:

1. Around line 70 (with other loop imports): `from auto_agent_preflight_loop import AutoAgentPreflightLoop`
2. Around line 175 (dataclass fields): `auto_agent_preflight_loop: AutoAgentPreflightLoop`
3. Around line 810 (loop construction):

```python
    auto_agent_audit = PreflightAuditStore(config.data_root)
    auto_agent_preflight_loop = AutoAgentPreflightLoop(
        config=config,
        state=state,
        pr_manager=pr_manager,
        wiki_store=wiki_store,  # already constructed earlier
        audit_store=auto_agent_audit,
        deps=loop_deps,
    )
```

4. Around line 910 (`ServiceRegistry(...)` kwargs): `auto_agent_preflight_loop=auto_agent_preflight_loop,`

**Modify** `src/orchestrator.py`:

1. Around line 166 (in `bg_loop_registry` dict): `"auto_agent_preflight": svc.auto_agent_preflight_loop,`
2. Around line 948 (`loop_factories` list): `("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),`

**Modify** `src/ui/src/constants.js`:

1. Line 252 — append `'auto_agent_preflight'` to the `EDITABLE_INTERVAL_WORKERS` Set.
2. Line ~277 (`SYSTEM_WORKER_INTERVALS`): add `auto_agent_preflight: 120,`
3. Line ~325 (`BACKGROUND_WORKERS` array): append:

```javascript
{
  key: 'auto_agent_preflight',
  label: 'Auto-Agent Pre-Flight',
  description: 'Intercepts hitl-escalation issues; runs an emulated-engineer subprocess to attempt autonomous resolution before the issue surfaces to a human.',
  color: theme.purple,
  group: 'autonomy',
  tags: ['hitl', 'autonomy'],
},
```

**Modify** `src/dashboard_routes/_common.py:~58` — append to `_INTERVAL_BOUNDS`:

```python
"auto_agent_preflight": (60, 600),
```

**Modify** `tests/scenarios/catalog/loop_registrations.py` — add a `_build_auto_agent_preflight` builder + entry in `_BUILDERS` dict.

**Modify** the two scenario catalog tests — add `"auto_agent_preflight"` to their expected-loop-name lists.

- [ ] **Step 1: Write failing wiring test** — `tests/test_auto_agent_loop_wiring.py`:

```python
"""Five-checkpoint wiring assertions for auto_agent_preflight."""

from __future__ import annotations

from dashboard_routes._common import _INTERVAL_BOUNDS


def test_interval_bounds_registered() -> None:
    assert "auto_agent_preflight" in _INTERVAL_BOUNDS
    assert _INTERVAL_BOUNDS["auto_agent_preflight"] == (60, 600)


def test_in_orchestrator_loop_registry() -> None:
    """Loop appears in the orchestrator's bg_loop_registry."""
    import orchestrator
    src = open(orchestrator.__file__).read()
    assert '"auto_agent_preflight"' in src
    assert "auto_agent_preflight_loop.run" in src


def test_in_service_registry() -> None:
    import service_registry
    src = open(service_registry.__file__).read()
    assert "AutoAgentPreflightLoop" in src
    assert "auto_agent_preflight_loop=" in src
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Apply all checkpoint edits** above.
- [ ] **Step 4: Run** → PASS. Also run the existing `tests/test_loop_wiring_completeness.py` (regex auto-discovery — should pass if naming consistent).
- [ ] **Step 5: Run scenario catalog tests** to confirm:

```bash
uv run pytest tests/scenarios/catalog/ -m "" -v
```

- [ ] **Step 6: Commit**

```bash
git add src/service_registry.py src/orchestrator.py src/ui/src/constants.js src/dashboard_routes/_common.py tests/scenarios/catalog/ tests/test_auto_agent_loop_wiring.py
git commit -m "feat(wiring): five-checkpoint registration for auto_agent_preflight (ADR-0049)"
```

---

## Task 13 — Issue-close reconciliation (clear attempts on close)

**Modify** `src/auto_agent_preflight_loop.py` — add a `_reconcile_closed_issues()` method called near the top of `_do_work()` (after the kill-switch and budget gates). Mirror `principles_audit_loop._reconcile_closed_escalations`.

```python
    async def _reconcile_closed_issues(self) -> int:
        """Clear auto_agent_attempts for issues that have been closed.

        Polls the last 200 closed issues with auto-agent-related labels, drops
        their attempt counts so a re-open starts fresh.
        """
        try:
            closed = await self._prs.list_closed_issues_by_label(
                "hitl-escalation", limit=200,
            )
        except Exception as exc:
            logger.warning("Auto-agent close-reconciliation poll failed: %s", exc)
            return 0
        cleared = 0
        for issue in closed:
            issue_number = int(issue.get("number", 0))
            if self._state.get_auto_agent_attempts(issue_number) > 0:
                self._state.clear_auto_agent_attempts(issue_number)
                cleared += 1
        return cleared
```

Insert call at top of `_do_work()` (after kill-switch + budget gates, before poll-eligible-issues):

```python
        cleared = await self._reconcile_closed_issues()
        if cleared:
            logger.info("Auto-agent reconciled %d closed issues", cleared)
```

- [ ] **Step 1: Write failing test** — `tests/test_auto_agent_close_reconciliation.py`:

```python
"""Issue-close → clear_auto_agent_attempts integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from tests.helpers import make_bg_loop_deps


@pytest.mark.asyncio
async def test_closed_issue_attempts_cleared(tmp_path: Path) -> None:
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=2)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[
        {"number": 7}, {"number": 12},
    ])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()

    loop = AutoAgentPreflightLoop(
        config=deps.config, state=state, pr_manager=pr,
        wiki_store=None, audit_store=audit, deps=deps.loop_deps,
    )
    await loop._do_work()

    assert state.clear_auto_agent_attempts.call_count == 2
    state.clear_auto_agent_attempts.assert_any_call(7)
    state.clear_auto_agent_attempts.assert_any_call(12)
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Apply the reconciliation method + integration call** above.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add src/auto_agent_preflight_loop.py tests/test_auto_agent_close_reconciliation.py
git commit -m "feat(loop): clear auto-agent attempts on issue close (spec §3.6)"
```

---

## Task 14 — `/api/diagnostics/auto-agent` endpoint

**Modify** `src/dashboard_routes/_diagnostics_routes.py` — add a new route. Locate by adjacent diagnostic routes (waterfall, loops/cost). Append:

```python
@router.get("/api/diagnostics/auto-agent")
async def auto_agent_stats() -> dict[str, Any]:
    """Auto-agent dashboard payload (spec §6.2)."""
    from preflight.audit import PreflightAuditStore
    config = _get_config()
    audit = PreflightAuditStore(config.data_root)
    today = audit.query_24h()
    week = audit.query_7d()
    top = audit.top_spend(n=5)
    return {
        "today": _stats_payload(today),
        "last_7d": _stats_payload(week),
        "top_spend": [
            {
                "issue": e.issue, "sub_label": e.sub_label, "cost_usd": e.cost_usd,
                "wall_clock_s": e.wall_clock_s, "status": e.status, "ts": e.ts,
            } for e in top
        ],
    }


def _stats_payload(stats: Any) -> dict[str, Any]:
    return {
        "spend_usd": stats.spend_usd, "attempts": stats.attempts,
        "resolved": stats.resolved, "resolution_rate": stats.resolution_rate,
        "p50_cost_usd": stats.p50_cost_usd, "p95_cost_usd": stats.p95_cost_usd,
        "p50_wall_clock_s": stats.p50_wall_clock_s, "p95_wall_clock_s": stats.p95_wall_clock_s,
    }
```

- [ ] **Step 1: Write failing endpoint test** — `tests/test_diagnostics_auto_agent.py`:

```python
"""GET /api/diagnostics/auto-agent endpoint test."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from preflight.audit import PreflightAuditEntry, PreflightAuditStore


@pytest.mark.asyncio
async def test_returns_24h_and_7d_stats(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for c in [1.0, 2.0]:
        store.append(PreflightAuditEntry(
            ts=now, issue=1, sub_label="x", attempt_n=1, prompt_hash="h",
            cost_usd=c, wall_clock_s=10.0, tokens=100,
            status="resolved", pr_url=None, diagnosis="d", llm_summary="s",
        ))
    # Build a minimal app with the diagnostics router and a config pointing at tmp_path.
    from fastapi import FastAPI
    from dashboard_routes._diagnostics_routes import router
    # ... wire config injection per existing test pattern in test_diagnostics_*.py
    # (See existing tests for the full FastAPI + AsyncClient + config-override pattern.)
```

(Full test scaffolding follows the existing pattern in `tests/test_diagnostics_*.py` — copy the FastAPI + config-injection setup from a recent diagnostics test like `test_diagnostics_loops_cost.py`.)

- [ ] **Step 2: Run** → FAIL (endpoint not registered).
- [ ] **Step 3: Implement the route.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add src/dashboard_routes/_diagnostics_routes.py tests/test_diagnostics_auto_agent.py
git commit -m "feat(diagnostics): /api/diagnostics/auto-agent endpoint (spec §6.2)"
```

---

## Task 15 — `AutoAgentStats` UI dashboard tile

**Create** `src/ui/src/components/system/AutoAgentStats.jsx` (React component, ~150 lines):

```jsx
import React, { useEffect, useState } from 'react';
import { theme } from '../../theme.js';

export function AutoAgentStats() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchStats = async () => {
      try {
        const res = await fetch('/api/diagnostics/auto-agent');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };
    fetchStats();
    const t = setInterval(fetchStats, 30_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (error) return <div style={{ color: theme.red }}>Auto-Agent stats unavailable: {error}</div>;
  if (!data) return <div>Loading…</div>;

  return (
    <div style={{ padding: '16px', border: `1px solid ${theme.border}`, borderRadius: 8 }}>
      <h3 style={{ marginTop: 0 }}>Auto-Agent</h3>
      <Window title="Today (24h)" stats={data.today} />
      <Window title="Last 7 days" stats={data.last_7d} />
      <TopSpend rows={data.top_spend} />
    </div>
  );
}

function Window({ title, stats }) {
  return (
    <div style={{ marginTop: 12 }}>
      <h4>{title}</h4>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <span>Spend</span><span>${stats.spend_usd.toFixed(2)}</span>
        <span>Attempts</span><span>{stats.attempts}</span>
        <span>Resolved</span><span>{stats.resolved} ({(stats.resolution_rate * 100).toFixed(0)}%)</span>
        <span>p50 cost</span><span>${stats.p50_cost_usd.toFixed(2)}</span>
        <span>p95 cost</span><span>${stats.p95_cost_usd.toFixed(2)}</span>
        <span>p50 wall</span><span>{stats.p50_wall_clock_s.toFixed(0)}s</span>
        <span>p95 wall</span><span>{stats.p95_wall_clock_s.toFixed(0)}s</span>
      </div>
    </div>
  );
}

function TopSpend({ rows }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <h4>Top spend (24h)</h4>
      <table style={{ width: '100%', fontSize: 12 }}>
        <thead><tr>
          <th>Issue</th><th>Sub-label</th><th>$</th><th>s</th><th>Status</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.issue}-${r.ts}`}>
              <td>#{r.issue}</td>
              <td>{r.sub_label}</td>
              <td>${r.cost_usd.toFixed(2)}</td>
              <td>{r.wall_clock_s.toFixed(0)}</td>
              <td>{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

**Modify** `src/ui/src/components/system/SystemTab.jsx` — import and mount `AutoAgentStats` near other observability tiles. Look for an existing tile import pattern.

- [ ] **Step 1: Create the component.**
- [ ] **Step 2: Mount it in `SystemTab.jsx`.**
- [ ] **Step 3: Verify in dev server**: `cd src/ui && npm run dev`, navigate to System tab, confirm tile renders.
- [ ] **Step 4: Commit**

```bash
git add src/ui/src/components/system/AutoAgentStats.jsx src/ui/src/components/system/SystemTab.jsx
git commit -m "feat(ui): AutoAgentStats System tab tile (spec §6.1)"
```

---

## Task 16 — Adversarial corpus + harness

**Create** `tests/auto_agent/adversarial/__init__.py` (empty).

**Create** the corpus directory structure — one entry per sub-label:

```
tests/auto_agent/adversarial/corpus/
  flaky-test-stuck/
    issue.json          # synthetic issue body
    cassette.json       # frozen Claude Code subprocess output
    expected.json       # expected PreflightResult
  revert-conflict/
    issue.json
    cassette.json
    expected.json
  ... (one per sub-label in spec §4.2)
```

**Initial entry** — `tests/auto_agent/adversarial/corpus/flaky-test-stuck/issue.json`:

```json
{
  "number": 9001,
  "title": "[Flake] flake-tracker: test_async_handler exhausted attempts",
  "body": "Flake-tracker has retried 5 attempts on tests/test_handlers.py::test_async_handler with no success. Recent flakes: 4/10 in last 24h.",
  "labels": [{"name": "hitl-escalation"}, {"name": "flaky-test-stuck"}]
}
```

**Initial entry** — `tests/auto_agent/adversarial/corpus/flaky-test-stuck/cassette.json`:

```json
{
  "output_text": "<status>resolved</status><pr_url>https://github.com/x/y/pull/9002</pr_url><diagnosis>Race in async fixture cleanup; added asyncio.sleep(0) yield before teardown.</diagnosis>",
  "cost_usd": 1.2,
  "tokens": 9500,
  "crashed": false
}
```

**Initial entry** — `tests/auto_agent/adversarial/corpus/flaky-test-stuck/expected.json`:

```json
{
  "status": "resolved",
  "labels_added": [],
  "labels_removed": ["hitl-escalation"],
  "pr_url": "https://github.com/x/y/pull/9002"
}
```

**Create** `tests/auto_agent/adversarial/test_corpus.py`:

```python
"""Adversarial corpus runner — iterates corpus/ entries, asserts golden outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.agent import PreflightAgentDeps, PreflightSpawn, run_preflight
from preflight.context import PreflightContext
from preflight.decision import apply_decision

_CORPUS_ROOT = Path(__file__).parent / "corpus"


def _load(entry: Path) -> tuple[dict, dict, dict]:
    return (
        json.loads((entry / "issue.json").read_text()),
        json.loads((entry / "cassette.json").read_text()),
        json.loads((entry / "expected.json").read_text()),
    )


def _entries() -> list[Path]:
    return sorted(p for p in _CORPUS_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("entry", _entries(), ids=lambda p: p.name)
@pytest.mark.asyncio
async def test_corpus_entry(entry: Path) -> None:
    issue, cassette, expected = _load(entry)
    sub_label = next(
        l["name"] for l in issue["labels"] if l["name"] != "hitl-escalation"
    )

    spawn_fn = AsyncMock(return_value=PreflightSpawn(
        process=None,
        output_text=cassette["output_text"],
        cost_usd=cassette["cost_usd"],
        tokens=cassette["tokens"],
        crashed=cassette["crashed"],
    ))

    ctx = PreflightContext(
        issue_number=issue["number"], issue_body=issue["body"],
        issue_comments=[], sub_label=sub_label, escalation_context=None,
        wiki_excerpts="", sentry_events=[], recent_commits=[],
        sublabel_extras={}, prior_attempts=[],
    )
    deps = PreflightAgentDeps(
        persona="test", cost_cap_usd=None, wall_clock_cap_s=None, spawn_fn=spawn_fn,
    )
    result = await run_preflight(
        context=ctx, repo_slug="x/y", worktree_path="/tmp", deps=deps,
    )
    assert result.status == expected["status"]
    if expected.get("pr_url"):
        assert result.pr_url == expected["pr_url"]

    # Verify decision applies the right labels.
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    out = await apply_decision(
        issue_number=issue["number"], sub_label=sub_label,
        result=result, pr_port=pr, state=state, max_attempts=3,
    )
    assert out["added"] == expected["labels_added"]
    assert out["removed"] == expected["labels_removed"]
```

**Modify** `Makefile` — add target:

```makefile
auto-agent-adversarial:
	uv run pytest tests/auto_agent/adversarial/ -v

.PHONY: auto-agent-adversarial
```

- [ ] **Step 1: Create the corpus directory + 9 entries** (one per sub-label, with realistic synthetic issue bodies + golden outcomes — repeat the pattern shown above; spend more cassette-output detail on the first entry, others can be terser).
- [ ] **Step 2: Create the harness test file.**
- [ ] **Step 3: Add the make target.**
- [ ] **Step 4: Run** `make auto-agent-adversarial` → all corpus entries pass.
- [ ] **Step 5: Commit**

```bash
git add tests/auto_agent/ Makefile
git commit -m "feat(tests): adversarial corpus + harness for auto-agent (spec §8.3)"
```

---

## Task 17 — Scenario test: full loop end-to-end

**Create** `tests/scenarios/test_auto_agent_preflight.py` — full-loop scenarios per spec §8.2. Each scenario uses the loop's real `_do_work` with mocked GitHub + cassette-fake spawn_fn.

```python
"""Full-loop scenario tests for AutoAgentPreflightLoop (spec §8.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from preflight.agent import PreflightSpawn
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path, **overrides):
    deps = make_bg_loop_deps(tmp_path, **overrides)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.bump_auto_agent_attempts = MagicMock(return_value=1)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.add_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_escalation_context = MagicMock(return_value=None)
    pr = AsyncMock()
    audit = MagicMock()
    audit.append = MagicMock()
    audit.entries_for_issue = MagicMock(return_value=[])
    loop = AutoAgentPreflightLoop(
        config=deps.config, state=state, pr_manager=pr,
        wiki_store=None, audit_store=audit, deps=deps.loop_deps,
    )
    return loop, state, pr, audit


def _stub_spawn(loop, output: str, *, cost: float = 1.0, crashed: bool = False):
    async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
        return PreflightSpawn(
            process=None, output_text=output, cost_usd=cost, tokens=100, crashed=crashed,
        )
    loop._build_spawn_fn = lambda issue: _spawn


@pytest.mark.asyncio
async def test_flaky_test_resolved(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "flaky-test-stuck"},
        ]},
    ])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    _stub_spawn(loop, "<status>resolved</status><pr_url>https://x/pr/1</pr_url><diagnosis>fixed</diagnosis>")
    result = await loop._do_work()
    assert result["result_status"] == "resolved"
    pr.remove_labels.assert_awaited_with(1, ["hitl-escalation"])


@pytest.mark.asyncio
async def test_subprocess_fatal(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "flaky-test-stuck"},
        ]},
    ])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    _stub_spawn(loop, "partial output", cost=0.5, crashed=True)
    result = await loop._do_work()
    assert result["result_status"] == "fatal"
    pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-fatal"])


@pytest.mark.asyncio
async def test_pr_open_failure(tmp_path: Path) -> None:
    """Resolved status but agent didn't include pr_url."""
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "flaky-test-stuck"},
        ]},
    ])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    # Resolved but no pr_url in response — should still mark resolved per current logic;
    # the pr_failed status is reserved for downstream PR-creation failures (real impl).
    _stub_spawn(loop, "<status>resolved</status><diagnosis>fixed</diagnosis>")
    result = await loop._do_work()
    assert result["result_status"] == "resolved"


@pytest.mark.asyncio
async def test_third_attempt_marks_exhausted(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.get_auto_agent_attempts = MagicMock(return_value=2)  # before bump
    state.bump_auto_agent_attempts = MagicMock(return_value=3)  # after bump
    # Decision uses get_auto_agent_attempts post-bump for exhaustion check
    state.get_auto_agent_attempts = MagicMock(side_effect=[2, 3])
    pr.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "flaky-test-stuck"},
        ]},
    ])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    _stub_spawn(loop, "<status>needs_human</status><diagnosis>cannot fix</diagnosis>")
    await loop._do_work()
    pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_principles_stuck_bypassed(tmp_path: Path) -> None:
    loop, _state, pr, audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(return_value=[
        {"number": 1, "body": "x", "labels": [
            {"name": "hitl-escalation"}, {"name": "principles-stuck"},
        ]},
    ])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    spawn_called = False
    async def _never_spawn(*a, **kw):
        nonlocal spawn_called
        spawn_called = True
        raise AssertionError("agent must not be spawned for deny-list sub-labels")
    loop._build_spawn_fn = lambda issue: _never_spawn
    result = await loop._do_work()
    assert result["result_status"] == "skipped_deny_list"
    pr.add_labels.assert_awaited_with(1, ["human-required"])
    assert spawn_called is False
```

- [ ] **Step 1: Create the file** with all five scenarios.
- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_auto_agent_preflight.py
git commit -m "test(scenarios): full-loop auto-agent scenarios (spec §8.2)"
```

---

## Task 18 — ADR-0050

**Create** `docs/adr/0050-auto-agent-hitl-preflight.md`:

```markdown
# ADR-0050: Auto-Agent HITL Pre-Flight Loop

## Status

Accepted

## Context

HydraFlow's stated operating model is dark-factory: software projects meeting
the spec run lights-off, with humans paged only for raging fires. Today this
contract is broken at one specific seam — the `hitl-escalation` label fires
for ~25 distinct failure conditions across phases and caretaker loops, and
every one of them goes straight to a human. Routine, mechanically-resolvable
failures (flaky test, drifted cassette, mergeable rebase, lint regression)
demand the same human attention as genuinely novel failures.

## Decision

Add a new caretaker loop `AutoAgentPreflightLoop` that intercepts every
`hitl-escalation` issue before a human sees it. The loop:

1. Polls open `hitl-escalation` issues that don't already have `human-required`.
2. Spawns a Claude Code subprocess (via `AutoAgentRunner`, a thin `HITLRunner`
   subclass) in the issue's worktree, with a sub-label-routed prompt and a
   parameterized "lead engineer" persona.
3. Up to 3 attempts per issue; subsequent attempts receive prior-attempt
   diagnoses in their context.
4. On success: removes `hitl-escalation`, posts a diagnosis comment, links the PR.
5. On failure: applies `human-required` + diagnosis. Humans watch
   `human-required` exclusively; they no longer watch `hitl-escalation`.

Hard tool restrictions (no CI config, no force-push, no secrets, no
self-modification of principles or auto-agent code) are enforced at the
worktree-tool layer.

The deny-list (default `["principles-stuck", "cultural-check"]`) bypasses
pre-flight for sub-labels where Auto-Agent could recursively modify the system
that judges it.

Cost / wall-clock / daily-budget caps are wired but defaulted to unlimited —
observability-first, no caps until needed. A new `AutoAgentStats` System tab
tile + `/api/diagnostics/auto-agent` endpoint surface the relevant data.

## Consequences

**Positive:**
- The dark-factory contract is honored at the issue-queue layer.
- Routine toil is absorbed by the auto-agent; humans only see what the agent
  itself bails on.
- Human queue diagnoses are richer — failed pre-flights produce structured
  "what was tried, what was ruled out" comments.
- Operator gets observability into "what does HydraFlow's own agent think?"
  via dashboard + audit JSONL.

**Negative:**
- A pre-flight runs on every escalated issue, costing LLM tokens (the audit
  + dashboard make this visible).
- Pre-flight latency adds to the time-to-human for issues that genuinely
  need a human (bounded by 1 cycle ≈ ~3-10 min).
- The label state machine grows (new labels: `human-required`,
  `auto-agent-fatal`, `auto-agent-exhausted`, `auto-agent-pr-failed`,
  `cost-exceeded`, `timeout`).

**Risks:**
- Auto-agent could "fix" something incorrectly. Mitigations: hard tool
  restrictions, principles-audit deny-list, attempt cap, human review of
  the resulting PR before merge.
- Recursive self-modification risk. Mitigations: tool restrictions on
  `principles_audit_loop.py` / `auto_agent_preflight_loop.py` /
  ADR-0044/0049 implementation files.
- Runaway cost. Mitigations: caps wired into code paths (default off);
  audit + dashboard surface unusual spend immediately.

## Alternatives Considered

- **Per-call-site interception** (modify each of ~25 escalation sites to call
  a helper) — rejected: too invasive; couples auto-agent to every loop.
- **Extend `DiagnosticLoop`** to handle all escalations — rejected: conflates
  the focused diagnostic phase with general-purpose rescue; DiagnosticLoop
  would balloon.
- **Investigate-only (no fix)** — rejected: too small an unlock; doesn't honor
  the dark-factory contract.
- **Investigate + targeted fixes only** (no full agent power) — rejected:
  doesn't capture the hardest cases (refactor, novel patches); locks the system
  out of its biggest unlock.

## Spec ref

`docs/superpowers/specs/2026-04-25-auto-agent-hitl-preflight-design.md`

## Plan ref

`docs/superpowers/plans/2026-04-25-auto-agent-hitl-preflight.md`
```

- [ ] **Step 1: Create the ADR file** above.
- [ ] **Step 2: Update the ADR index** (`docs/adr/README.md`) — add a row for ADR-0050 in Accepted status.
- [ ] **Step 3: Commit**

```bash
git add docs/adr/0050-auto-agent-hitl-preflight.md docs/adr/README.md
git commit -m "docs(adr): ADR-0050 — auto-agent HITL pre-flight loop"
```

---

## Final Verification

After all 18 tasks complete:

- [ ] **Run full test suite:** `uv run pytest tests/ -m "" -v` → all pass.
- [ ] **Run quality gates:** `make quality` → lint + typecheck + tests + security all green.
- [ ] **Run adversarial corpus:** `make auto-agent-adversarial` → all entries pass.
- [ ] **Smoke-test the loop in dev:**
  - Set `auto_agent_preflight_enabled=False` initially in config.
  - Start orchestrator: `uv run python src/main.py --dev`.
  - Open System tab → confirm `auto_agent_preflight` worker appears with toggleable interval.
  - Open dashboard → confirm `Auto-Agent` tile renders (will show all zeros).
  - Manually toggle to enabled → confirm next cycle status payload reads `{"status": "ok", "issues_processed": 0}`.
- [ ] **Open PR with the cumulative diff** — title: `feat(auto-agent): HITL pre-flight loop (spec §1–§11, plan complete)`. Reference both spec PR (#8431) and ADR-0050.
- [ ] **Wait for CI green, then merge.**
