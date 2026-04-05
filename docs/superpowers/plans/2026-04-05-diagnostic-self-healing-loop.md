# Diagnostic Self-Healing Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-HITL diagnostic stage that analyzes failures with full context, classifies severity, attempts targeted fixes, and only escalates to humans what genuinely requires human judgment.

**Architecture:** New `hydraflow-diagnose` label and `DiagnosticLoop` (BaseBackgroundLoop subclass) sits between pipeline phases and HITL. When any phase would escalate, it routes to diagnostic first. A two-stage `DiagnosticRunner` (diagnose then fix) processes each issue. Failures escalate to HITL with severity classification and root cause analysis attached.

**Tech Stack:** Python 3.11, asyncio, Pydantic, BaseBackgroundLoop, BaseRunner, gh CLI

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/models.py` | Add `Severity`, `AttemptRecord`, `EscalationContext`, `DiagnosisResult` |
| Create | `src/state/_diagnostic.py` | State mixin for escalation context, attempts, severity |
| Modify | `src/state/__init__.py` | Mix in `DiagnosticStateMixin` |
| Modify | `src/config.py` | Add `diagnose_label`, `max_diagnosticians`, `diagnostic_interval`, `max_diagnostic_attempts` |
| Modify | `src/prep.py` | Add `hydraflow-diagnose` to `HYDRAFLOW_LABELS` |
| Modify | `src/events.py` | Add `DIAGNOSTIC_UPDATE` event type |
| Modify | `src/phase_utils.py` | Add `escalate_to_diagnostic()`, update `PipelineEscalator` |
| Create | `src/diagnostic_runner.py` | Two-stage agent: diagnose then fix |
| Create | `src/diagnostic_loop.py` | `BaseBackgroundLoop` subclass |
| Modify | `src/service_registry.py` | Wire `DiagnosticLoop` |
| Modify | `src/orchestrator.py` | Register in `bg_loop_registry` |
| Modify | `src/dashboard_routes/_common.py` | Add to `_INTERVAL_BOUNDS` |
| Modify | `src/ui/src/constants.js` | Add to `BACKGROUND_WORKERS` |
| Modify | `src/review_phase.py` | Route escalations to diagnostic |
| Modify | `src/implement_phase.py` | Route escalations to diagnostic |
| Modify | `src/plan_phase.py` | Route escalations to diagnostic |
| Modify | `src/hitl_phase.py` | Remove `attempt_auto_fixes()` |
| Create | `tests/test_diagnostic_models.py` | Tests for new models |
| Create | `tests/test_diagnostic_state.py` | Tests for state mixin |
| Create | `tests/test_escalate_to_diagnostic.py` | Tests for escalation helper |
| Create | `tests/test_diagnostic_runner.py` | Tests for runner |
| Create | `tests/test_diagnostic_loop.py` | Tests for loop |

---

### Task 1: Models — Severity, AttemptRecord, EscalationContext, DiagnosisResult

**Files:**
- Modify: `src/models.py` (after `HitlEscalation` at ~line 773)
- Create: `tests/test_diagnostic_models.py`

- [ ] **Step 1: Write the failing test for Severity enum**

```python
# tests/test_diagnostic_models.py
"""Tests for diagnostic self-healing models."""

from __future__ import annotations

from models import AttemptRecord, DiagnosisResult, EscalationContext, Severity


class TestSeverity:
    def test_severity_values(self) -> None:
        assert Severity.P0_SECURITY == "P0"
        assert Severity.P1_BLOCKING == "P1"
        assert Severity.P2_FUNCTIONAL == "P2"
        assert Severity.P3_WIRING == "P3"
        assert Severity.P4_HOUSEKEEPING == "P4"

    def test_severity_ordering(self) -> None:
        ordered = sorted(Severity, key=lambda s: s.value)
        assert [s.value for s in ordered] == ["P0", "P1", "P2", "P3", "P4"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_diagnostic_models.py::TestSeverity -xvs`
Expected: FAIL — `Severity` not defined

- [ ] **Step 3: Write the failing test for AttemptRecord**

```python
class TestAttemptRecord:
    def test_round_trip(self) -> None:
        record = AttemptRecord(
            attempt_number=1,
            changes_made=True,
            error_summary="TypeError in line 42",
            timestamp="2026-04-05T12:00:00Z",
        )
        data = record.model_dump()
        restored = AttemptRecord.model_validate(data)
        assert restored.attempt_number == 1
        assert restored.changes_made is True
        assert restored.error_summary == "TypeError in line 42"
```

- [ ] **Step 4: Write the failing test for EscalationContext**

```python
class TestEscalationContext:
    def test_minimal_context(self) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        assert ctx.cause == "CI failed"
        assert ctx.ci_logs is None
        assert ctx.previous_attempts == []

    def test_full_context_round_trip(self) -> None:
        ctx = EscalationContext(
            cause="CI failed after 2 attempts",
            origin_phase="review",
            ci_logs="FAIL test_foo.py::test_bar",
            review_comments=["Fix the import"],
            pr_diff="diff --git a/x b/x",
            pr_number=42,
            code_scanning_alerts=["sql-injection in query.py"],
            previous_attempts=[
                AttemptRecord(
                    attempt_number=1,
                    changes_made=True,
                    error_summary="Still fails",
                    timestamp="2026-04-05T12:00:00Z",
                )
            ],
            agent_transcript="I tried changing the import...",
        )
        data = ctx.model_dump()
        restored = EscalationContext.model_validate(data)
        assert restored.pr_number == 42
        assert len(restored.previous_attempts) == 1
        assert restored.previous_attempts[0].changes_made is True
```

- [ ] **Step 5: Write the failing test for DiagnosisResult**

```python
class TestDiagnosisResult:
    def test_round_trip(self) -> None:
        result = DiagnosisResult(
            root_cause="Method name mismatch: queue_depths vs get_queue_stats",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Rename call on line 1226",
            human_guidance="Straightforward rename",
            affected_files=["src/dashboard_routes/_routes.py"],
        )
        data = result.model_dump()
        restored = DiagnosisResult.model_validate(data)
        assert restored.severity == Severity.P2_FUNCTIONAL
        assert restored.fixable is True
        assert len(restored.affected_files) == 1
```

- [ ] **Step 6: Implement all four models in `src/models.py`**

Add after the `HitlEscalation` dataclass (around line 773):

```python
# --- Diagnostic Self-Healing ---


class Severity(StrEnum):
    """Priority classification for diagnostic escalations."""

    P0_SECURITY = "P0"
    P1_BLOCKING = "P1"
    P2_FUNCTIONAL = "P2"
    P3_WIRING = "P3"
    P4_HOUSEKEEPING = "P4"


class AttemptRecord(BaseModel):
    """Record of a single diagnostic fix attempt."""

    attempt_number: int
    changes_made: bool
    error_summary: str
    timestamp: str


class EscalationContext(BaseModel):
    """Full context captured at escalation time for the diagnostic agent."""

    cause: str
    origin_phase: str
    ci_logs: str | None = None
    review_comments: list[str] = Field(default_factory=list)
    pr_diff: str | None = None
    pr_number: int | None = None
    code_scanning_alerts: list[str] = Field(default_factory=list)
    previous_attempts: list[AttemptRecord] = Field(default_factory=list)
    agent_transcript: str | None = None


class DiagnosisResult(BaseModel):
    """Structured output from diagnostic agent Stage 1."""

    root_cause: str
    severity: Severity
    fixable: bool
    fix_plan: str
    human_guidance: str
    affected_files: list[str] = Field(default_factory=list)
```

Note: `StrEnum` is already imported in `models.py` (used by `ReviewVerdict`). `BaseModel` and `Field` are already imported.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostic_models.py -xvs`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/models.py tests/test_diagnostic_models.py
git commit -m "feat: add Severity, AttemptRecord, EscalationContext, DiagnosisResult models"
```

---

### Task 2: State mixin — DiagnosticStateMixin

**Files:**
- Create: `src/state/_diagnostic.py`
- Modify: `src/state/__init__.py`
- Create: `tests/test_diagnostic_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_diagnostic_state.py
"""Tests for DiagnosticStateMixin."""

from __future__ import annotations

import pytest

from models import AttemptRecord, EscalationContext, Severity
from state import StateTracker


@pytest.fixture
def state(tmp_path):
    return StateTracker(tmp_path / "state.json")


class TestDiagnosticState:
    def test_escalation_context_round_trip(self, state) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        state.set_escalation_context(42, ctx)
        restored = state.get_escalation_context(42)
        assert restored is not None
        assert restored.cause == "CI failed"

    def test_escalation_context_missing_returns_none(self, state) -> None:
        assert state.get_escalation_context(999) is None

    def test_diagnostic_attempts(self, state) -> None:
        record = AttemptRecord(
            attempt_number=1,
            changes_made=True,
            error_summary="still fails",
            timestamp="2026-04-05T12:00:00Z",
        )
        state.add_diagnostic_attempt(42, record)
        attempts = state.get_diagnostic_attempts(42)
        assert len(attempts) == 1
        assert attempts[0].changes_made is True

    def test_diagnostic_attempts_empty(self, state) -> None:
        assert state.get_diagnostic_attempts(999) == []

    def test_diagnosis_severity(self, state) -> None:
        state.set_diagnosis_severity(42, Severity.P2_FUNCTIONAL)
        assert state.get_diagnosis_severity(42) == Severity.P2_FUNCTIONAL

    def test_diagnosis_severity_missing_returns_none(self, state) -> None:
        assert state.get_diagnosis_severity(999) is None

    def test_clear_diagnostic_state(self, state) -> None:
        ctx = EscalationContext(cause="test", origin_phase="review")
        state.set_escalation_context(42, ctx)
        state.set_diagnosis_severity(42, Severity.P1_BLOCKING)
        state.clear_diagnostic_state(42)
        assert state.get_escalation_context(42) is None
        assert state.get_diagnosis_severity(42) is None
        assert state.get_diagnostic_attempts(42) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_diagnostic_state.py -xvs`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Implement `src/state/_diagnostic.py`**

Follow the pattern from `src/state/_hitl.py`:

```python
"""Diagnostic self-healing state — escalation context, attempts, severity."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import AttemptRecord, EscalationContext, Severity

logger = logging.getLogger("hydraflow.state")


class DiagnosticStateMixin:
    """State methods for the diagnostic self-healing loop."""

    def set_escalation_context(
        self, issue_number: int, context: EscalationContext
    ) -> None:
        """Store full escalation context for the diagnostic agent."""
        self._data.escalation_contexts[self._key(issue_number)] = context.model_dump()
        self.save()

    def get_escalation_context(
        self, issue_number: int
    ) -> EscalationContext | None:
        """Retrieve escalation context, or None if not set."""
        from models import EscalationContext as EC  # noqa: PLC0415

        raw = self._data.escalation_contexts.get(self._key(issue_number))
        if raw is None:
            return None
        return EC.model_validate(raw)

    def add_diagnostic_attempt(
        self, issue_number: int, record: AttemptRecord
    ) -> None:
        """Append a diagnostic fix attempt record."""
        key = self._key(issue_number)
        attempts = self._data.diagnostic_attempts.get(key, [])
        attempts.append(record.model_dump())
        self._data.diagnostic_attempts[key] = attempts
        self.save()

    def get_diagnostic_attempts(
        self, issue_number: int
    ) -> list[AttemptRecord]:
        """Return all diagnostic attempts for an issue."""
        from models import AttemptRecord as AR  # noqa: PLC0415

        raw_list = self._data.diagnostic_attempts.get(
            self._key(issue_number), []
        )
        return [AR.model_validate(r) for r in raw_list]

    def set_diagnosis_severity(
        self, issue_number: int, severity: Severity
    ) -> None:
        """Store the severity classification from diagnostic analysis."""
        self._data.diagnosis_severities[self._key(issue_number)] = severity.value
        self.save()

    def get_diagnosis_severity(
        self, issue_number: int
    ) -> Severity | None:
        """Retrieve severity classification, or None if not set."""
        from models import Severity as S  # noqa: PLC0415

        raw = self._data.diagnosis_severities.get(self._key(issue_number))
        if raw is None:
            return None
        return S(raw)

    def clear_diagnostic_state(self, issue_number: int) -> None:
        """Remove all diagnostic state for an issue."""
        key = self._key(issue_number)
        self._data.escalation_contexts.pop(key, None)
        self._data.diagnostic_attempts.pop(key, None)
        self._data.diagnosis_severities.pop(key, None)
        self.save()
```

- [ ] **Step 4: Add state data fields to `StateData`**

In `src/state/_data.py` (or wherever `StateData` is defined), add three new fields:

```python
escalation_contexts: dict[str, dict[str, object]] = Field(default_factory=dict)
diagnostic_attempts: dict[str, list[dict[str, object]]] = Field(default_factory=dict)
diagnosis_severities: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 5: Mix `DiagnosticStateMixin` into `StateTracker`**

In `src/state/__init__.py`, add `DiagnosticStateMixin` to the class bases:

```python
from state._diagnostic import DiagnosticStateMixin

class StateTracker(
    # ... existing mixins ...
    DiagnosticStateMixin,
    # ... rest ...
):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostic_state.py -xvs`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/state/_diagnostic.py src/state/__init__.py src/state/_data.py tests/test_diagnostic_state.py
git commit -m "feat: add DiagnosticStateMixin for escalation context and severity tracking"
```

---

### Task 3: Config, prep, events — infrastructure fields

**Files:**
- Modify: `src/config.py`
- Modify: `src/prep.py`
- Modify: `src/events.py`

- [ ] **Step 1: Add config fields**

In `src/config.py`, add to `_ENV_LABEL_MAP`:

```python
"HYDRAFLOW_LABEL_DIAGNOSE": ("diagnose_label", ["hydraflow-diagnose"]),
```

Add to `_ENV_INT_OVERRIDES` (find the dict):

```python
"HYDRAFLOW_DIAGNOSTIC_INTERVAL": "diagnostic_interval",
```

Add fields to `HydraFlowConfig` class (near other label fields):

```python
diagnose_label: list[str] = Field(
    default=["hydraflow-diagnose"],
    description="Labels for issues in diagnostic analysis (OR logic)",
)
max_diagnosticians: int = Field(
    default=1,
    description="Max concurrent diagnostic workers",
)
diagnostic_interval: int = Field(
    default=30,
    description="Poll interval in seconds for diagnostic loop",
)
max_diagnostic_attempts: int = Field(
    default=2,
    description="Fix attempts before escalating to HITL",
)
```

- [ ] **Step 2: Add label to prep.py**

In `src/prep.py` `HYDRAFLOW_LABELS` tuple, add:

```python
("diagnose_label", "1d76db", "Issue under diagnostic analysis before HITL"),
```

- [ ] **Step 3: Add event type**

In `src/events.py` `EventType` enum, add:

```python
DIAGNOSTIC_UPDATE = "diagnostic_update"
```

- [ ] **Step 4: Update event enum test**

In `tests/test_events.py`, add `"DIAGNOSTIC_UPDATE"` to the expected set in `test_all_expected_values_exist`.

In `tests/test_event_reducer_coverage.py`, add `"diagnostic_update"` to the `SKIP_LIST`.

- [ ] **Step 5: Update label test**

In `tests/test_pr_manager_core.py::test_ensure_labels_exist_uses_config_label_names`, add `"hydraflow-diagnose"` to the expected `created_labels` set (it will use the default since the test doesn't set `diagnose_label`).

- [ ] **Step 6: Run affected tests**

Run: `uv run pytest tests/test_events.py tests/test_event_reducer_coverage.py tests/test_pr_manager_core.py::test_ensure_labels_exist_uses_config_label_names -xvs`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/prep.py src/events.py tests/test_events.py tests/test_event_reducer_coverage.py tests/test_pr_manager_core.py
git commit -m "feat: add diagnose_label, diagnostic config fields, DIAGNOSTIC_UPDATE event"
```

---

### Task 4: `escalate_to_diagnostic()` helper and PipelineEscalator update

**Files:**
- Modify: `src/phase_utils.py`
- Create: `tests/test_escalate_to_diagnostic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_escalate_to_diagnostic.py
"""Tests for escalate_to_diagnostic helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from models import EscalationContext
from phase_utils import escalate_to_diagnostic


class TestEscalateToDiagnostic:
    @pytest.fixture
    def mock_state(self):
        return MagicMock()

    @pytest.fixture
    def mock_prs(self):
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        return prs

    @pytest.mark.asyncio
    async def test_stores_context_and_swaps_label(
        self, mock_state, mock_prs
    ) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        await escalate_to_diagnostic(
            mock_state,
            mock_prs,
            issue_number=42,
            context=ctx,
            origin_label="hydraflow-review",
            diagnose_label="hydraflow-diagnose",
        )
        mock_state.set_escalation_context.assert_called_once_with(42, ctx)
        mock_state.set_hitl_origin.assert_called_once_with(42, "hydraflow-review")
        mock_state.set_hitl_cause.assert_called_once_with(42, "CI failed")
        mock_state.record_hitl_escalation.assert_called_once()
        mock_prs.swap_pipeline_labels.assert_awaited_once_with(
            42, "hydraflow-diagnose"
        )

    @pytest.mark.asyncio
    async def test_swaps_to_diagnose_not_hitl(
        self, mock_state, mock_prs
    ) -> None:
        ctx = EscalationContext(cause="test", origin_phase="implement")
        await escalate_to_diagnostic(
            mock_state,
            mock_prs,
            issue_number=10,
            context=ctx,
            origin_label="hydraflow-ready",
            diagnose_label="hydraflow-diagnose",
        )
        label_arg = mock_prs.swap_pipeline_labels.call_args[0][1]
        assert label_arg == "hydraflow-diagnose"
        assert "hitl" not in label_arg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_escalate_to_diagnostic.py -xvs`
Expected: FAIL — `escalate_to_diagnostic` not defined

- [ ] **Step 3: Implement `escalate_to_diagnostic`**

In `src/phase_utils.py`, add after `escalate_to_hitl`:

```python
async def escalate_to_diagnostic(
    state: StateTracker,
    prs: PRPort,
    issue_number: int,
    *,
    context: EscalationContext,
    origin_label: str,
    diagnose_label: str,
) -> None:
    """Route an issue to the diagnostic loop instead of HITL.

    Stores full escalation context, records HITL origin/cause for
    traceability, and swaps labels to *diagnose_label*.
    """
    state.set_escalation_context(issue_number, context)
    state.set_hitl_origin(issue_number, origin_label)
    state.set_hitl_cause(issue_number, context.cause)
    state.record_hitl_escalation()
    await prs.swap_pipeline_labels(issue_number, diagnose_label)
```

Add the import for `EscalationContext` at the top of the file (TYPE_CHECKING block).

- [ ] **Step 4: Update `PipelineEscalator` to route to diagnostic**

In `src/phase_utils.py`, update `PipelineEscalator.__init__` to accept `diagnose_label`:

```python
def __init__(
    self,
    state: StateTracker,
    prs: PRPort,
    store: IssueStorePort,
    harness_insights: HarnessInsightStore | None,
    *,
    origin_label: str,
    hitl_label: str,
    diagnose_label: str,
    stage: PipelineStage,
) -> None:
    self._state = state
    self._prs = prs
    self._store = store
    self._harness_insights = harness_insights
    self._origin_label = origin_label
    self._hitl_label = hitl_label
    self._diagnose_label = diagnose_label
    self._stage = stage
```

Add `"_diagnose_label"` to `__slots__`.

Update `__call__` to accept an optional `context` and route to diagnostic:

```python
async def __call__(
    self,
    issue: Task,
    *,
    cause: str,
    details: str,
    category: FailureCategory,
    context: EscalationContext | None = None,
) -> None:
    issue_number = issue.id
    if context is None:
        context = EscalationContext(
            cause=cause,
            origin_phase=self._stage.value,
        )
    try:
        await escalate_to_diagnostic(
            self._state,
            self._prs,
            issue_number,
            context=context,
            origin_label=self._origin_label,
            diagnose_label=self._diagnose_label,
        )
    except Exception:
        logger.error(
            "Escalation to diagnostic failed for issue #%d — falling back to HITL",
            issue_number,
            exc_info=True,
        )
        try:
            await self._prs.swap_pipeline_labels(issue_number, self._hitl_label)
        except Exception:
            logger.error(
                "Fallback label swap also failed for issue #%d",
                issue_number,
                exc_info=True,
            )
    self._store.enqueue_transition(issue, "diagnose")
    record_harness_failure(
        self._harness_insights,
        issue_number,
        category,
        details,
        stage=self._stage,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_escalate_to_diagnostic.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/phase_utils.py tests/test_escalate_to_diagnostic.py
git commit -m "feat: add escalate_to_diagnostic helper, update PipelineEscalator"
```

---

### Task 5: DiagnosticRunner — two-stage agent

**Files:**
- Create: `src/diagnostic_runner.py`
- Create: `tests/test_diagnostic_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_diagnostic_runner.py
"""Tests for DiagnosticRunner."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import DiagnosisResult, EscalationContext, Severity


class TestDiagnosticRunner:
    @pytest.fixture
    def runner(self):
        from diagnostic_runner import DiagnosticRunner

        config = MagicMock()
        config.repo_root = "/tmp/repo"
        config.max_diagnostic_attempts = 2
        bus = MagicMock()
        return DiagnosticRunner(config=config, event_bus=bus)

    @pytest.mark.asyncio
    async def test_diagnose_parses_structured_result(self, runner, monkeypatch) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        diagnosis_json = json.dumps({
            "root_cause": "Missing import",
            "severity": "P2",
            "fixable": True,
            "fix_plan": "Add import on line 5",
            "human_guidance": "Straightforward fix",
            "affected_files": ["src/app.py"],
        })

        async def fake_execute(*args, **kwargs):
            return f"```json\n{diagnosis_json}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx)
        assert isinstance(result, DiagnosisResult)
        assert result.severity == Severity.P2_FUNCTIONAL
        assert result.fixable is True

    @pytest.mark.asyncio
    async def test_diagnose_returns_unfixable_on_parse_error(self, runner, monkeypatch) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def fake_execute(*args, **kwargs):
            return "I couldn't figure it out"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx)
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert result.severity == Severity.P2_FUNCTIONAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_diagnostic_runner.py -xvs`
Expected: FAIL — `DiagnosticRunner` not defined

- [ ] **Step 3: Implement `src/diagnostic_runner.py`**

```python
"""Diagnostic runner — two-stage agent for self-healing."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from base_runner import BaseRunner

if TYPE_CHECKING:
    from models import EscalationContext

from models import DiagnosisResult, Severity

logger = logging.getLogger("hydraflow.diagnostic")


def _extract_json(text: str) -> dict | None:
    """Extract first JSON block from agent output."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    raw = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _build_diagnosis_prompt(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    context: EscalationContext,
) -> str:
    """Build the Stage 1 diagnosis prompt with full context."""
    sections = [
        f"# Diagnostic Analysis — Issue #{issue_number}\n",
        f"**Title:** {issue_title}\n",
        f"**Body:**\n{issue_body}\n",
        f"**Escalation cause:** {context.cause}\n",
        f"**Origin phase:** {context.origin_phase}\n",
    ]
    if context.ci_logs:
        sections.append(f"**CI Logs:**\n```\n{context.ci_logs}\n```\n")
    if context.review_comments:
        sections.append(
            "**Review Feedback:**\n"
            + "\n".join(f"- {c}" for c in context.review_comments)
            + "\n"
        )
    if context.pr_diff:
        sections.append(f"**PR Diff:**\n```diff\n{context.pr_diff}\n```\n")
    if context.code_scanning_alerts:
        sections.append(
            "**Code Scanning Alerts:**\n"
            + "\n".join(f"- {a}" for a in context.code_scanning_alerts)
            + "\n"
        )
    if context.previous_attempts:
        lines = []
        for a in context.previous_attempts:
            lines.append(
                f"- Attempt {a.attempt_number}: "
                f"{'made changes' if a.changes_made else 'no changes'}, "
                f"error: {a.error_summary}"
            )
        sections.append("**Previous Attempts:**\n" + "\n".join(lines) + "\n")
    if context.agent_transcript:
        sections.append(
            f"**Agent Reasoning (failed attempt):**\n{context.agent_transcript[:4000]}\n"
        )

    sections.append(
        "\n## Instructions\n\n"
        "Analyze the root cause. Classify severity:\n"
        "- P0: Secrets exposure, auth bypass, data loss\n"
        "- P1: Pipeline blocked, crash loop, state corruption\n"
        "- P2: Wrong behavior, system keeps running\n"
        "- P3: Missing wiring, incomplete setup\n"
        "- P4: Housekeeping, renaming, non-urgent\n\n"
        "Respond with a JSON block:\n"
        "```json\n"
        '{"root_cause": "...", "severity": "P0-P4", "fixable": true/false, '
        '"fix_plan": "...", "human_guidance": "...", "affected_files": [...]}\n'
        "```"
    )
    return "\n".join(sections)


class DiagnosticRunner(BaseRunner):
    """Two-stage diagnostic agent: diagnose, then fix."""

    _log = logger

    async def diagnose(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        context: EscalationContext,
    ) -> DiagnosisResult:
        """Stage 1: Read-only diagnosis. Returns structured result."""
        prompt = _build_diagnosis_prompt(
            issue_number, issue_title, issue_body, context
        )
        try:
            transcript = await self._execute(
                prompt=prompt,
                cwd=self._config.repo_root,
                allowed_tools=["Read", "Glob", "Grep", "Bash(read-only)"],
            )
        except Exception:
            logger.exception("Diagnostic agent failed for issue #%d", issue_number)
            return DiagnosisResult(
                root_cause="Diagnostic agent crashed",
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Diagnostic agent encountered an error. Manual review required.",
            )

        parsed = _extract_json(transcript)
        if parsed is None:
            return DiagnosisResult(
                root_cause=transcript[:500],
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Agent did not produce structured output. Manual review required.",
            )

        try:
            return DiagnosisResult.model_validate(parsed)
        except Exception:
            return DiagnosisResult(
                root_cause=parsed.get("root_cause", transcript[:500]),
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan=parsed.get("fix_plan", ""),
                human_guidance="Agent output did not validate. Manual review required.",
            )

    async def fix(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        diagnosis: DiagnosisResult,
        wt_path: str,
    ) -> tuple[bool, str]:
        """Stage 2: Attempt fix in worktree. Returns (success, transcript)."""
        prompt = (
            f"# Fix Issue #{issue_number}: {issue_title}\n\n"
            f"**Root Cause:** {diagnosis.root_cause}\n\n"
            f"**Fix Plan:** {diagnosis.fix_plan}\n\n"
            f"**Affected Files:** {', '.join(diagnosis.affected_files)}\n\n"
            f"**Issue Body:**\n{issue_body}\n\n"
            "Apply the fix. Run `make quality` to verify. "
            "Commit your changes with a descriptive message."
        )
        try:
            transcript = await self._execute(
                prompt=prompt,
                cwd=wt_path,
            )
            quality_ok = self._verify_quality(wt_path)
            return quality_ok, transcript
        except Exception:
            logger.exception(
                "Diagnostic fix failed for issue #%d", issue_number
            )
            return False, "Fix agent crashed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostic_runner.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diagnostic_runner.py tests/test_diagnostic_runner.py
git commit -m "feat: add DiagnosticRunner with two-stage diagnose/fix"
```

---

### Task 6: DiagnosticLoop — background worker

**Files:**
- Create: `src/diagnostic_loop.py`
- Create: `tests/test_diagnostic_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diagnostic_loop.py
"""Tests for DiagnosticLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDiagnosticLoop:
    @pytest.fixture
    def loop(self, tmp_path):
        from diagnostic_loop import DiagnosticLoop

        config = MagicMock()
        config.diagnostic_interval = 30
        config.max_diagnosticians = 1
        config.max_diagnostic_attempts = 2
        config.diagnose_label = ["hydraflow-diagnose"]
        config.hitl_label = ["hydraflow-hitl"]
        config.review_label = ["hydraflow-review"]
        config.repo_root = tmp_path
        config.state_file = tmp_path / "state.json"
        config.worktree_base = tmp_path / "worktrees"
        config.dry_run = False

        deps = MagicMock()
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.stop_event.is_set = MagicMock(return_value=False)

        runner = AsyncMock()
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        prs.post_comment = AsyncMock()
        state = MagicMock()

        lp = DiagnosticLoop(
            config=config,
            runner=runner,
            prs=prs,
            state=state,
            deps=deps,
        )
        return lp, runner, prs, state

    @pytest.mark.asyncio
    async def test_get_default_interval(self, loop) -> None:
        lp, _, _, _ = loop
        assert lp._get_default_interval() == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_diagnostic_loop.py -xvs`
Expected: FAIL — `DiagnosticLoop` not defined

- [ ] **Step 3: Implement `src/diagnostic_loop.py`**

```python
"""Diagnostic self-healing loop — analyzes and fixes issues before HITL."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop
from events import EventType, HydraFlowEvent
from models import AttemptRecord, DiagnosisResult, Severity

if TYPE_CHECKING:
    from base_background_loop import LoopDeps
    from config import HydraFlowConfig
    from diagnostic_runner import DiagnosticRunner
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.diagnostic_loop")


def _format_diagnosis_comment(diagnosis: DiagnosisResult) -> str:
    """Build a structured GitHub comment from a diagnosis."""
    return (
        "## Diagnostic Analysis\n\n"
        f"**Severity:** {diagnosis.severity.value}\n"
        f"**Root Cause:** {diagnosis.root_cause}\n"
        f"**Affected Files:** {', '.join(diagnosis.affected_files) or 'unknown'}\n\n"
        f"### Fix Plan\n{diagnosis.fix_plan or 'No automated fix available.'}\n\n"
        f"### Human Guidance\n{diagnosis.human_guidance}\n\n"
        "---\n*Generated by HydraFlow Diagnostic Agent*"
    )


class DiagnosticLoop(BaseBackgroundLoop):
    """Polls for hydraflow-diagnose issues and runs diagnostic analysis."""

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: DiagnosticRunner,
        prs: PRPort,
        state: StateTracker,
        *,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="diagnostic",
            config=config,
            deps=deps,
        )
        self._runner = runner
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.diagnostic_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Fetch diagnose-labeled issues and process them."""
        issues = await self._prs.list_issues_by_label(
            self._config.diagnose_label,
        )
        if not issues:
            return {"processed": 0}

        processed = 0
        for issue in issues:
            if self._stop_requested():
                break
            await self._process_issue(issue)
            processed += 1

        return {"processed": processed}

    async def _process_issue(self, issue: Any) -> None:
        """Run diagnostic analysis on a single issue."""
        issue_number = issue.number if hasattr(issue, "number") else issue.id

        context = self._state.get_escalation_context(issue_number)
        if context is None:
            logger.warning(
                "Issue #%d has no escalation context — escalating to HITL",
                issue_number,
            )
            await self._escalate_to_hitl(issue_number, None)
            return

        # Stage 1: Diagnose
        diagnosis = await self._runner.diagnose(
            issue_number=issue_number,
            issue_title=issue.title,
            issue_body=getattr(issue, "body", "") or "",
            context=context,
        )
        self._state.set_diagnosis_severity(issue_number, diagnosis.severity)

        if not diagnosis.fixable:
            await self._escalate_to_hitl(issue_number, diagnosis)
            return

        # Stage 2: Fix (with retry)
        attempts = self._state.get_diagnostic_attempts(issue_number)
        if len(attempts) >= self._config.max_diagnostic_attempts:
            await self._escalate_to_hitl(issue_number, diagnosis)
            return

        success, transcript = await self._runner.fix(
            issue_number=issue_number,
            issue_title=issue.title,
            issue_body=getattr(issue, "body", "") or "",
            diagnosis=diagnosis,
            wt_path=str(self._config.repo_root),
        )

        attempt = AttemptRecord(
            attempt_number=len(attempts) + 1,
            changes_made=success,
            error_summary="" if success else transcript[:200],
            timestamp=datetime.now(UTC).isoformat(),
        )
        self._state.add_diagnostic_attempt(issue_number, attempt)

        if success:
            await self._prs.swap_pipeline_labels(
                issue_number, self._config.review_label[0]
            )
            await self._prs.post_comment(
                issue_number,
                f"## Diagnostic Fix Applied\n\n"
                f"**Root Cause:** {diagnosis.root_cause}\n"
                f"**Severity:** {diagnosis.severity.value}\n\n"
                f"Fix applied and quality checks passed. Returning to review.\n\n"
                f"---\n*Generated by HydraFlow Diagnostic Agent*",
            )
            self._state.clear_diagnostic_state(issue_number)
            logger.info("Issue #%d fixed by diagnostic agent", issue_number)
        else:
            # Check if we have retries left
            all_attempts = self._state.get_diagnostic_attempts(issue_number)
            if len(all_attempts) >= self._config.max_diagnostic_attempts:
                await self._escalate_to_hitl(issue_number, diagnosis)
            else:
                logger.info(
                    "Issue #%d diagnostic attempt %d failed, will retry",
                    issue_number,
                    len(all_attempts),
                )

    async def _escalate_to_hitl(
        self,
        issue_number: int,
        diagnosis: DiagnosisResult | None,
    ) -> None:
        """Move issue to HITL with diagnosis attached."""
        if diagnosis is not None:
            await self._prs.post_comment(
                issue_number, _format_diagnosis_comment(diagnosis)
            )

        await self._prs.swap_pipeline_labels(
            issue_number, self._config.hitl_label[0]
        )

        await self._deps.event_bus.publish(
            HydraFlowEvent(
                type=EventType.DIAGNOSTIC_UPDATE,
                data={
                    "issue": issue_number,
                    "action": "escalated_to_hitl",
                    "severity": diagnosis.severity.value if diagnosis else "unknown",
                },
            )
        )
        logger.info(
            "Issue #%d escalated to HITL after diagnostic analysis", issue_number
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostic_loop.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diagnostic_loop.py tests/test_diagnostic_loop.py
git commit -m "feat: add DiagnosticLoop background worker"
```

---

### Task 7: Service registry + orchestrator wiring

**Files:**
- Modify: `src/service_registry.py`
- Modify: `src/orchestrator.py`
- Modify: `src/dashboard_routes/_common.py`
- Modify: `src/ui/src/constants.js`

- [ ] **Step 1: Add to `ServiceRegistry` dataclass**

In `src/service_registry.py`, add import and field:

```python
from diagnostic_loop import DiagnosticLoop
```

Add field to `ServiceRegistry`:

```python
diagnostic_loop: DiagnosticLoop
```

- [ ] **Step 2: Instantiate in `build_services()`**

After the other loop instantiations, add:

```python
from diagnostic_runner import DiagnosticRunner

diagnostic_runner = DiagnosticRunner(
    config=config,
    event_bus=event_bus,
    runner=subprocess_runner,
    credentials=credentials,
)
diagnostic_loop = DiagnosticLoop(
    config=config,
    runner=diagnostic_runner,
    prs=prs,
    state=state,
    deps=loop_deps,
)
```

Pass `diagnostic_loop=diagnostic_loop` to `ServiceRegistry(...)`.

- [ ] **Step 3: Register in orchestrator**

In `src/orchestrator.py` `bg_loop_registry` dict, add:

```python
"diagnostic": svc.diagnostic_loop,
```

- [ ] **Step 4: Add interval bounds**

In `src/dashboard_routes/_common.py` `_INTERVAL_BOUNDS`, add:

```python
"diagnostic": (10, 3600),
```

- [ ] **Step 5: Add to frontend constants**

In `src/ui/src/constants.js` `BACKGROUND_WORKERS`, add:

```javascript
{ key: 'diagnostic', label: 'Diagnostic Agent', description: 'Analyzes escalated issues, classifies severity, and attempts targeted fixes before HITL.', color: theme.blue, system: true },
```

- [ ] **Step 6: Run loop wiring completeness test**

Run: `uv run pytest tests/test_loop_wiring_completeness.py -xvs`
Expected: PASS (or fix any missing wiring it flags)

- [ ] **Step 7: Commit**

```bash
git add src/service_registry.py src/orchestrator.py src/dashboard_routes/_common.py src/ui/src/constants.js
git commit -m "feat: wire DiagnosticLoop into service registry, orchestrator, dashboard"
```

---

### Task 8: Update escalation sites — review_phase.py

**Files:**
- Modify: `src/review_phase.py`
- Modify: `tests/test_review_phase_core.py` (update affected tests)

This is the largest change — `review_phase.py` has 7 direct `_escalate_to_hitl` calls. Each one needs to build an `EscalationContext` and route to diagnostic.

- [ ] **Step 1: Update `_escalate_to_hitl` method to route through diagnostic**

In `src/review_phase.py`, modify the `_escalate_to_hitl` method (line ~1666) to route to `hydraflow-diagnose` instead of `hydraflow-hitl`:

```python
async def _escalate_to_hitl(self, esc: HitlEscalation) -> None:
    """Route escalation through diagnostic loop instead of direct HITL."""
    from models import EscalationContext  # noqa: PLC0415

    context = EscalationContext(
        cause=esc.cause,
        origin_phase="review",
        pr_number=esc.pr_number,
    )
    # Attach any extra context from the escalation data
    if esc.extra_event_data:
        if "ci_fix_attempts" in esc.extra_event_data:
            context.previous_attempts = []  # populated by caller if available

    self._state.set_escalation_context(esc.issue_number, context)
    self._state.set_hitl_origin(esc.issue_number, esc.origin_label)
    self._state.set_hitl_cause(esc.issue_number, esc.cause)
    self._state.record_hitl_escalation()

    try:
        from memory_scoring import MemoryScorer  # noqa: PLC0415

        scorer = MemoryScorer(self._config.memory_dir)
        scorer.record_hitl_outcome(
            issue_id=esc.issue_number,
            digest_hash=self._state.get_digest_hash(esc.issue_number) or "",
            cause=esc.cause,
            tags=list(esc.task.tags) if esc.task is not None else [],
        )
    except Exception:
        logger.debug("Failed to record HITL outcome", exc_info=True)

    if esc.visual_evidence is not None:
        self._state.set_hitl_visual_evidence(esc.issue_number, esc.visual_evidence)

    if esc.task is not None:
        self._store.enqueue_transition(esc.task, "diagnose")
    await self._transitioner.transition(
        esc.issue_number, "diagnose", pr_number=esc.pr_number
    )

    if esc.post_on_pr and esc.pr_number and esc.pr_number > 0:
        await self._prs.post_pr_comment(esc.pr_number, esc.comment)
    else:
        await self._prs.post_comment(esc.issue_number, esc.comment)

    event_data: dict[str, object] = {
        "issue": esc.issue_number,
        "status": "diagnostic",
        "role": "reviewer",
        "cause": esc.event_cause or esc.cause,
    }
    if esc.pr_number and esc.pr_number > 0:
        event_data["pr"] = esc.pr_number
    if esc.visual_evidence is not None:
        event_data["visual_evidence"] = esc.visual_evidence.model_dump()
    if esc.extra_event_data:
        event_data.update(esc.extra_event_data)
    await self._bus.publish(
        HydraFlowEvent(type=EventType.HITL_ESCALATION, data=event_data)
    )
```

This is a single-point change — all 7 call sites already call `_escalate_to_hitl`, so they all route through diagnostic now.

- [ ] **Step 2: Enrich context at CI failure site**

At line ~1475 (CI failure escalation), build richer context before calling `_escalate_to_hitl`:

Add before the `await self._escalate_to_hitl(...)` call:

```python
from models import EscalationContext  # noqa: PLC0415

ci_context = EscalationContext(
    cause=cause,
    origin_phase="review",
    ci_logs=logs,
    pr_number=pr.number,
)
self._state.set_escalation_context(issue.id, ci_context)
```

- [ ] **Step 3: Enrich context at review fix cap site**

At line ~1918, add context with review transcript:

```python
from models import EscalationContext  # noqa: PLC0415

review_context = EscalationContext(
    cause=f"Review fix cap exceeded after {max_attempts} attempt(s)",
    origin_phase="review",
    pr_number=pr.number,
    agent_transcript=result.transcript if result.transcript else None,
)
self._state.set_escalation_context(pr.issue_number, review_context)
```

- [ ] **Step 4: Update tests that assert HITL transition to expect diagnostic**

In `tests/test_review_phase_core.py`, update tests that check for `transition(..., "hitl", ...)` to expect `transition(..., "diagnose", ...)`.

- [ ] **Step 5: Run review phase tests**

Run: `uv run pytest tests/test_review_phase_core.py -x --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/review_phase.py tests/test_review_phase_core.py
git commit -m "feat: review phase routes escalations through diagnostic loop"
```

---

### Task 9: Update escalation sites — implement_phase.py and plan_phase.py

**Files:**
- Modify: `src/implement_phase.py`
- Modify: `src/plan_phase.py`

- [ ] **Step 1: Update PipelineEscalator instantiation in implement_phase.py**

In `src/implement_phase.py` `__init__`, add `diagnose_label` to the `PipelineEscalator`:

```python
self._escalator = PipelineEscalator(
    state,
    prs,
    store,
    harness_insights,
    origin_label=config.ready_label[0],
    hitl_label=config.hitl_label[0],
    diagnose_label=config.diagnose_label[0],
    stage=PipelineStage.IMPLEMENT,
)
```

- [ ] **Step 2: Enrich context at zero-diff escalation**

In `src/implement_phase.py` `_escalate_no_changes_to_hitl` (~line 697), build context:

```python
from models import EscalationContext  # noqa: PLC0415

context = EscalationContext(
    cause=self._hitl_cause(issue, "implementation produced no changes (zero diff)"),
    origin_phase="implement",
    agent_transcript=result.transcript if result.transcript else None,
)
await self._escalator(
    issue,
    cause=context.cause,
    details="Implementation produced no changes (zero diff)",
    category=FailureCategory.HITL_ESCALATION,
    context=context,
)
```

- [ ] **Step 3: Update PipelineEscalator instantiation in plan_phase.py**

Same pattern — add `diagnose_label=config.diagnose_label[0]` to the `PipelineEscalator` constructor call.

- [ ] **Step 4: Run affected tests**

Run: `uv run pytest tests/test_implement_phase*.py tests/test_plan_phase*.py -x --tb=short`
Expected: PASS (or fix assertions that expect "hitl" to now expect "diagnose")

- [ ] **Step 5: Commit**

```bash
git add src/implement_phase.py src/plan_phase.py
git commit -m "feat: implement and plan phases route through diagnostic loop"
```

---

### Task 10: Remove HITL auto-fix, update HITL phase

**Files:**
- Modify: `src/hitl_phase.py`

- [ ] **Step 1: Remove `attempt_auto_fixes` method**

In `src/hitl_phase.py`, remove the `attempt_auto_fixes()` method (~lines 105-150) and its call site. Issues that reach HITL now have a diagnosis attached — auto-fix is handled by the diagnostic loop.

- [ ] **Step 2: Remove the auto-fix call from the HITL processing loop**

Find where `attempt_auto_fixes` is called (likely in `process_hitl_issues` or similar) and remove the call.

- [ ] **Step 3: Update HITL tests**

Remove or update tests that assert `attempt_auto_fixes` behavior.

- [ ] **Step 4: Run HITL tests**

Run: `uv run pytest tests/test_hitl_phase.py -x --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hitl_phase.py tests/test_hitl_phase.py
git commit -m "feat: remove HITL auto-fix — replaced by diagnostic loop"
```

---

### Task 11: Full test suite and quality gate

**Files:** None — validation only

- [ ] **Step 1: Run lint**

```bash
make lint
```

- [ ] **Step 2: Run full quality check**

```bash
make quality
```

- [ ] **Step 3: Fix any issues found**

Address lint, type, or test failures from the changes.

- [ ] **Step 4: Final commit if fixes were needed**

```bash
git add -u
git commit -m "fix: quality gate fixes for diagnostic self-healing loop"
```
