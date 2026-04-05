# HITL Queue Hygiene — Dedup, Reclassify, Reserve for Humans

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reserve `hydraflow-hitl` for issues that genuinely require human review. Route everything else through the EventBus into the normal pipeline, add dedup to `create_issue`, and have triage close duplicates automatically.

**Architecture:** Three changes: (1) Add a dedup guard to `PRManager.create_issue` that searches for existing open issues with the same title before filing. (2) Replace HITL escalation with EventBus routing for non-urgent categories (ADR validation, triage fallthrough, audit findings). (3) Extend triage to detect and close duplicate open issues.

**Tech Stack:** Python 3.11, asyncio, `gh` CLI, EventBus, Pydantic

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/pr_manager.py:910-959` | Add dedup guard to `create_issue` |
| Modify | `src/events.py:53-93` | Add new `EventType` values |
| Modify | `src/triage_phase.py:102-244` | Replace HITL escalation with park-and-ask; add duplicate detection |
| Modify | `src/review_phase.py:309-326` | Replace HITL escalation for ADR validation with event + re-queue |
| Modify | `src/phase_utils.py:177-195` | Add `park_issue` helper alongside `escalate_to_hitl` |
| Modify | `src/adr_reviewer.py:938-960` | Replace HITL escalation with event + triage issue (dedup-safe) |
| Modify | `src/config.py` | Add `parked_label` config field |
| Modify | `src/prep.py` | Add `parked_label` to `HYDRAFLOW_LABELS` |
| Create | `tests/test_create_issue_dedup.py` | Tests for dedup guard |
| Create | `tests/test_triage_duplicate_detection.py` | Tests for duplicate closure in triage |
| Create | `tests/test_park_issue.py` | Tests for park-and-ask flow |
| Modify | `tests/test_triage_phase.py` | Update existing triage tests for new routing |
| Modify | `tests/test_review_phase.py` | Update ADR review escalation tests |

---

### Task 1: Dedup Guard on `create_issue`

**Files:**
- Modify: `src/pr_manager.py:910-959`
- Create: `tests/test_create_issue_dedup.py`

The root cause of 297 duplicate ADR issues: `create_issue` has zero duplicate detection. Add a title-match search before filing.

- [ ] **Step 1: Write the failing test — dedup skips creation when open issue exists**

```python
# tests/test_create_issue_dedup.py
"""Tests for create_issue dedup guard."""

from __future__ import annotations

import pytest

from tests.conftest import make_pr_manager


@pytest.fixture
def pr_manager(tmp_path, mock_config, mock_event_bus):
    """PRManager wired with mock config and event bus."""
    return make_pr_manager(tmp_path, config=mock_config, bus=mock_event_bus)


@pytest.mark.asyncio
async def test_create_issue_returns_existing_when_duplicate(pr_manager, monkeypatch):
    """When an open issue with the same title exists, return its number instead of creating."""
    # Simulate gh search finding an existing issue
    async def fake_run(*args, **kwargs):
        cmd = args if not isinstance(args[0], list) else args[0]
        joined = " ".join(str(c) for c in cmd)
        if "search" in joined and "issues" in joined:
            return "42\n"
        # Should NOT reach create
        raise AssertionError("create_issue should not be called when duplicate exists")

    monkeypatch.setattr(pr_manager, "_run", fake_run)
    result = await pr_manager.create_issue("Fix the widget", "body", labels=["bug"])
    assert result == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_create_issue_dedup.py::test_create_issue_returns_existing_when_duplicate -xvs`
Expected: FAIL — no dedup logic exists yet

- [ ] **Step 3: Write the failing test — dedup allows creation when no match**

```python
@pytest.mark.asyncio
async def test_create_issue_creates_when_no_duplicate(pr_manager, monkeypatch):
    """When no open issue matches, proceed with normal creation."""
    created = False

    async def fake_run(*args, **kwargs):
        nonlocal created
        cmd = args if not isinstance(args[0], list) else args[0]
        joined = " ".join(str(c) for c in cmd)
        if "search" in joined and "issues" in joined:
            return "\n"  # Empty — no match
        if "issue" in joined and "create" in joined:
            created = True
            return "https://github.com/org/repo/issues/99\n"
        return ""

    monkeypatch.setattr(pr_manager, "_run", fake_run)
    result = await pr_manager.create_issue("Brand new issue", "body")
    assert result == 99
    assert created
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_create_issue_dedup.py -xvs`
Expected: FAIL

- [ ] **Step 5: Implement dedup guard in `create_issue`**

In `src/pr_manager.py`, add a `_find_existing_issue` method and call it at the top of `create_issue`:

```python
async def _find_existing_issue(self, title: str) -> int:
    """Search for an open issue with an exact title match. Returns issue number or 0."""
    self._assert_repo()
    try:
        output = await self._run(
            "gh", "search", "issues",
            "--repo", self._repo,
            "--state", "open",
            "--match", "title",
            "--json", "number,title",
            "--jq", f'.[] | select(.title == "{title}") | .number',
            "--", title,
            cwd=self._config.repo_root,
        )
        first_line = output.strip().split("\n")[0].strip()
        return int(first_line) if first_line else 0
    except (RuntimeError, ValueError):
        return 0
```

Then in `create_issue`, after the dry-run check and before building the `gh issue create` command:

```python
existing = await self._find_existing_issue(title)
if existing:
    logger.info(
        "Skipping duplicate issue creation — #%d already open with title %r",
        existing,
        title,
    )
    return existing
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_create_issue_dedup.py -xvs`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pr_manager.py tests/test_create_issue_dedup.py
git commit -m "feat: add dedup guard to create_issue — search before filing"
```

---

### Task 2: Add `parked_label` and `SYSTEM_REROUTE` event type

**Files:**
- Modify: `src/config.py`
- Modify: `src/prep.py`
- Modify: `src/events.py:53-93`

Add infrastructure for parking issues and routing non-HITL events.

- [ ] **Step 1: Add `parked_label` to config**

In `src/config.py`, add the field near the other label fields:

```python
parked_label: list[str] = Field(
    default=["hydraflow-parked"],
    description="Labels for issues parked awaiting author clarification (OR logic)",
)
```

And add the env var override in `_ENV_LABEL_OVERRIDES`:

```python
"HYDRAFLOW_LABEL_PARKED": ("parked_label", ["hydraflow-parked"]),
```

- [ ] **Step 2: Add label definition to `prep.py`**

In `src/prep.py` `HYDRAFLOW_LABELS` tuple, add:

```python
(cfg.parked_label[0], "c5c5c5", "Issue parked — awaiting author clarification"),
```

- [ ] **Step 3: Add `SYSTEM_REROUTE` event type**

In `src/events.py` `EventType` enum, add:

```python
SYSTEM_REROUTE = "system_reroute"
```

- [ ] **Step 4: Commit**

```bash
git add src/config.py src/prep.py src/events.py
git commit -m "feat: add parked_label config and SYSTEM_REROUTE event type"
```

---

### Task 3: Add `park_issue` helper in `phase_utils.py`

**Files:**
- Modify: `src/phase_utils.py:177-195`
- Create: `tests/test_park_issue.py`

A new helper that parks an issue (removes pipeline labels, adds `parked_label`, posts a "needs info" comment) instead of escalating to HITL.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_park_issue.py
"""Tests for park_issue helper."""

from __future__ import annotations

import pytest

from phase_utils import park_issue


@pytest.fixture
def mock_state(mocker):
    return mocker.MagicMock()


@pytest.fixture
def mock_prs(mocker):
    prs = mocker.AsyncMock()
    prs.swap_pipeline_labels = mocker.AsyncMock()
    prs.post_comment = mocker.AsyncMock()
    return prs


@pytest.mark.asyncio
async def test_park_issue_swaps_to_parked_label(mock_state, mock_prs):
    """park_issue should swap labels to parked and post a comment."""
    await park_issue(
        mock_prs,
        issue_number=42,
        parked_label="hydraflow-parked",
        reasons=["Missing acceptance criteria", "No repro steps"],
    )
    mock_prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-parked")
    mock_prs.post_comment.assert_awaited_once()
    comment = mock_prs.post_comment.call_args[0][1]
    assert "Missing acceptance criteria" in comment
    assert "re-apply" in comment.lower() or "re-label" in comment.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_park_issue.py -xvs`
Expected: FAIL — `park_issue` does not exist

- [ ] **Step 3: Implement `park_issue`**

In `src/phase_utils.py`, add after `escalate_to_hitl`:

```python
async def park_issue(
    prs: PRPort,
    issue_number: int,
    *,
    parked_label: str,
    reasons: list[str],
) -> None:
    """Park an issue that needs author clarification.

    Swaps pipeline labels to parked_label and posts a comment
    asking the author to provide missing information.
    """
    await prs.swap_pipeline_labels(issue_number, parked_label)
    note = (
        "## Needs More Information\n\n"
        "This issue doesn't have enough detail for HydraFlow to begin work.\n\n"
        "**Missing:**\n" + "\n".join(f"- {r}" for r in reasons) + "\n\n"
        "Please update the issue with more context and re-apply "
        "the `hydraflow-find` label when ready.\n\n"
        "---\n*Generated by HydraFlow Triage*"
    )
    await prs.post_comment(issue_number, note)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_park_issue.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/phase_utils.py tests/test_park_issue.py
git commit -m "feat: add park_issue helper for non-HITL triage fallthrough"
```

---

### Task 4: Replace triage HITL escalation with park_issue

**Files:**
- Modify: `src/triage_phase.py:204-244`
- Modify: `tests/test_triage_phase.py`

The triage fallthrough path (lines 204-221) currently escalates unclear issues to HITL. Replace with `park_issue` — the issue gets parked with a "needs info" comment, and the author re-labels when ready.

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_triage_phase.py — add new test
@pytest.mark.asyncio
async def test_triage_parks_unclear_issue_instead_of_hitl(triage_phase, mock_prs, mock_state):
    """Unclear issues should be parked, not escalated to HITL."""
    issue = make_task(id=10, title="Fix stuff", body="please fix")
    # Mock triage evaluation returning not-ready, not-sentry
    triage_phase._triage.evaluate = AsyncMock(
        return_value=TriageResult(ready=False, reasons=["No acceptance criteria"])
    )
    await triage_phase._triage_single(issue)

    # Should NOT call escalate_to_hitl
    mock_state.set_hitl_origin.assert_not_called()
    # Should swap to parked label
    mock_prs.swap_pipeline_labels.assert_awaited()
    label_arg = mock_prs.swap_pipeline_labels.call_args[0][1]
    assert "parked" in label_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_triage_phase.py::test_triage_parks_unclear_issue_instead_of_hitl -xvs`
Expected: FAIL — still escalates to HITL

- [ ] **Step 3: Replace `_escalate_triage_issue` with park flow**

In `src/triage_phase.py`, replace lines 204-221 (the `else` branch in `_triage_single`):

```python
        else:
            await park_issue(
                self._prs,
                issue_number=issue.id,
                parked_label=self._config.parked_label[0],
                reasons=result.reasons,
            )
            self._store.enqueue_transition(issue, "parked")
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_REROUTE,
                    data={
                        "issue": issue.id,
                        "action": "parked",
                        "reasons": result.reasons,
                    },
                )
            )
            logger.info(
                "Issue #%d triaged → parked (needs info: %s)",
                issue.id,
                "; ".join(result.reasons),
            )
```

Add `park_issue` to the imports from `phase_utils` and `SYSTEM_REROUTE` usage.

Also update `_escalate_triage_issue` — it can be removed or kept only for the rare cases that genuinely need HITL (if any remain in triage). If no callers remain, delete it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_triage_phase.py -xvs`
Expected: PASS (update any other tests that asserted HITL escalation from triage)

- [ ] **Step 5: Commit**

```bash
git add src/triage_phase.py tests/test_triage_phase.py
git commit -m "feat: triage parks unclear issues instead of HITL escalation"
```

---

### Task 5: Replace ADR review HITL escalation with re-queue

**Files:**
- Modify: `src/review_phase.py:309-326`
- Modify: `tests/test_review_phase.py`

ADR validation failures in review (missing sections, short Decision) should re-queue the issue to `hydraflow-plan` with a comment, not escalate to HITL. The system can retry after the author updates the ADR.

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_review_phase.py — add new test
@pytest.mark.asyncio
async def test_adr_validation_failure_requeues_instead_of_hitl(
    review_phase, mock_prs, mock_state
):
    """ADR validation failures should re-queue to plan, not HITL."""
    issue = make_task(id=20, title="ADR-0050: New pattern")
    issue.body = "## Status\nProposed\n## Context\nShort.\n## Decision\nYes."

    await review_phase._review_adr(issue)

    # Should NOT escalate to HITL
    mock_state.set_hitl_origin.assert_not_called()
    # Should transition back to plan
    mock_prs.swap_pipeline_labels.assert_awaited()
    label_arg = mock_prs.swap_pipeline_labels.call_args[0][1]
    assert "plan" in label_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_review_phase.py::test_adr_validation_failure_requeues_instead_of_hitl -xvs`
Expected: FAIL

- [ ] **Step 3: Replace ADR HITL escalation with re-queue**

In `src/review_phase.py` around lines 309-326, replace the `_escalate_to_hitl` call:

```python
        if reasons:
            # Re-queue for planning instead of HITL — ADR needs author fixes
            await self._prs.post_comment(
                issue.id,
                "## ADR Review — Changes Needed\n\n"
                "The ADR draft needs fixes before finalization.\n\n"
                "**Required fixes:**\n"
                + "\n".join(f"- {reason}" for reason in reasons)
                + "\n\nUpdating and re-labeling will re-enter the pipeline.",
            )
            await self._transitioner.transition(issue.id, "plan")
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_REROUTE,
                    data={
                        "issue": issue.id,
                        "action": "requeued_to_plan",
                        "reasons": reasons,
                    },
                )
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                summary=f"ADR re-queued for fixes: {'; '.join(reasons)}",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review_phase.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review_phase.py tests/test_review_phase.py
git commit -m "feat: ADR validation failures re-queue to plan instead of HITL"
```

---

### Task 6: ADR reviewer — dedup-safe issue filing

**Files:**
- Modify: `src/adr_reviewer.py:938-960`

The ADR reviewer's `_escalate_to_hitl` files issues with titles like `[ADR Review] ADR-0023: ...`. Now that `create_issue` has a dedup guard (Task 1), this path is already safe from duplicates. But it should also route to triage instead of HITL.

- [ ] **Step 1: Write the failing test**

Add a test to the ADR reviewer test file verifying that `_escalate_to_hitl` creates an issue with `hydraflow-find` label (enters triage), not `hydraflow-hitl`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adr_reviewer.py -xvs -k escalate`
Expected: FAIL

- [ ] **Step 3: Update `_escalate_to_hitl` to route through triage**

In `src/adr_reviewer.py:938-960`, change the label from `hitl_label` to `find_label` so the issue enters normal triage:

```python
async def _escalate_to_hitl(self, result: ADRCouncilResult, *, reason: str) -> None:
    """Route ADR council escalation through triage instead of HITL."""
    # ... existing title/body building ...
    issue_number = await self._pr_manager.create_issue(
        title, body, labels=[self._config.find_label[0]]
    )
    # ... rest unchanged ...
```

Rename the method to `_route_to_triage_or_file` if you want clarity, but the functional change is just the label.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adr_reviewer.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/adr_reviewer.py tests/test_adr_reviewer.py
git commit -m "feat: ADR reviewer routes escalations through triage, not HITL"
```

---

### Task 7: Duplicate detection in triage

**Files:**
- Modify: `src/triage_phase.py:102-142`
- Create: `tests/test_triage_duplicate_detection.py`

Triage already closes duplicate ADR issues. Extend it to detect general duplicates: before processing any issue, search for open issues with a very similar title. If found, close the new one as a duplicate.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_triage_duplicate_detection.py
"""Tests for duplicate detection in triage."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_triage_closes_duplicate_issue(triage_phase, mock_prs):
    """When an open issue with the same title exists, close the new one as duplicate."""
    issue = make_task(id=50, title="Fix login timeout")

    # Simulate finding an existing open issue with same title
    mock_prs.find_existing_issue = AsyncMock(return_value=30)

    result = await triage_phase._triage_single(issue)

    # Should close the duplicate
    mock_prs.post_comment.assert_awaited()
    comment = mock_prs.post_comment.call_args[0][1]
    assert "duplicate" in comment.lower()
    assert "#30" in comment
    assert result == 1


@pytest.mark.asyncio
async def test_triage_proceeds_when_no_duplicate(triage_phase, mock_prs):
    """When no duplicate exists, proceed with normal triage."""
    issue = make_task(id=51, title="Unique new feature")
    mock_prs.find_existing_issue = AsyncMock(return_value=0)
    # ... rest of normal triage flow
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_triage_duplicate_detection.py -xvs`
Expected: FAIL

- [ ] **Step 3: Implement duplicate detection at top of `_triage_single`**

In `src/triage_phase.py`, add duplicate detection at the start of `_triage_single`, before the ADR check:

```python
async def _triage_single(self, issue: Task) -> int:
    """Core triage logic for a single issue."""
    # --- General duplicate detection ---
    if not self._config.dry_run:
        existing = await self._prs.find_existing_issue(issue.title)
        if existing and existing != issue.id:
            await self._prs.post_comment(
                issue.id,
                f"## Closing as Duplicate\n\n"
                f"An open issue with the same title already exists: #{existing}.\n\n"
                f"Closing this as a duplicate.",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "Issue #%d closed as duplicate of #%d",
                issue.id,
                existing,
            )
            return 1

    # ... existing ADR check and rest of triage ...
```

This reuses the `_find_existing_issue` method added to `PRManager` in Task 1. Expose it as `find_existing_issue` on the `PRPort` protocol.

- [ ] **Step 4: Add `find_existing_issue` to `PRPort`**

In `src/ports.py`, add to the `PRPort` protocol:

```python
async def find_existing_issue(self, title: str) -> int:
    """Search for an open issue with matching title. Returns issue number or 0."""
    ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_triage_duplicate_detection.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/triage_phase.py src/ports.py tests/test_triage_duplicate_detection.py
git commit -m "feat: triage closes duplicate issues before processing"
```

---

### Task 8: Bulk-close existing duplicate HITL issues

**Files:**
- No source changes — this is a one-time cleanup script run

Use `gh` CLI to close the duplicate/misclassified HITL issues that are currently open. This is a manual step, not automated code.

- [ ] **Step 1: List all open HITL issues for review**

```bash
gh issue list --label hydraflow-hitl --state open --limit 100 --json number,title | jq -r '.[] | "\(.number)\t\(.title)"'
```

- [ ] **Step 2: Identify and close architecture audit issues (relabel)**

These are tech debt findings, not HITL. Remove `hydraflow-hitl`, add `hydraflow-find` so they enter normal triage:

```bash
# For each architecture audit issue (5948-5996 range):
gh issue edit <NUMBER> --remove-label hydraflow-hitl --add-label hydraflow-find
```

- [ ] **Step 3: Identify and close feature request issues (relabel)**

Memory/Hindsight feature requests (6004-6031) should enter normal triage:

```bash
# For each feature request issue:
gh issue edit <NUMBER> --remove-label hydraflow-hitl --add-label hydraflow-find
```

- [ ] **Step 4: Close true duplicates**

For issues that are exact duplicates of other open issues, close them with a comment:

```bash
gh issue close <NUMBER> --comment "Closing as duplicate — see #<ORIGINAL>"
```

- [ ] **Step 5: Verify remaining HITL queue**

```bash
gh issue list --label hydraflow-hitl --state open --limit 100
```

Only genuine pipeline failures (CI failures, review cap exceeded, merge conflicts) should remain.

- [ ] **Step 6: Commit any label changes to prep.py if needed**

No code commit needed — this is a cleanup operation.

---

### Task 9: Run quality gate

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

Address lint, type, or test failures from the changes above.

- [ ] **Step 4: Final commit if fixes were needed**

```bash
git add -u
git commit -m "fix: quality gate fixes for HITL queue hygiene"
```
