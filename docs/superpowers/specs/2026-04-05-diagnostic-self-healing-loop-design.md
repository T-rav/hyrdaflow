# Diagnostic Self-Healing Loop

**Goal:** Add a pre-HITL diagnostic stage that analyzes failures with full context, classifies severity, attempts targeted fixes, and only escalates to humans what genuinely requires human judgment.

**Problem:** The current HITL auto-fix agent receives a 200-char cause summary and a generic prompt. The system actually HAS full CI logs, transcripts, review comments, and attempt history — but none of it reaches the agent. Result: trivial 1-2 line bugs that an agent could fix end up waiting for human review.

**Success criteria:** Reduce HITL escalation rate by giving the diagnostic agent enough context to fix the straightforward cases (CI failures with clear errors, missing wiring, trivial bugs). HITL queue contains only issues that genuinely need human judgment, each tagged with severity and root cause analysis.

---

## Architecture

### Pipeline Flow Change

**Current:**
```
Phase failure -> escalate_to_hitl() -> hydraflow-hitl -> auto-fix attempt -> human
```

**New:**
```
Phase failure -> escalate_to_diagnostic() -> hydraflow-diagnose
    -> DiagnosticLoop picks up issue
        -> Stage 1: Diagnose (read-only analysis, severity classification)
        -> Stage 2: Fix (if fixable, create worktree, apply fix, run quality)
            -> Success: push PR, transition to hydraflow-review
            -> Failure: escalate to hydraflow-hitl with full diagnosis + severity
```

### New Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `DiagnosticLoop` | `src/diagnostic_loop.py` | `BaseBackgroundLoop` subclass, polls `hydraflow-diagnose`, dispatches to runner |
| `DiagnosticRunner` | `src/diagnostic_runner.py` | Two-stage agent: diagnose then fix |
| `EscalationContext` | `src/models.py` | Pydantic model capturing full failure context at escalation time |
| `DiagnosisResult` | `src/models.py` | Structured output from Stage 1 (root cause, severity, fix plan) |
| `escalate_to_diagnostic()` | `src/phase_utils.py` | Replaces `escalate_to_hitl()` at most call sites |

### New Label: `hydraflow-diagnose`

- Color: `1d76db` (blue, distinct from HITL red)
- Meaning: "System is analyzing — not yet human-required"
- Sits between pipeline labels and `hydraflow-hitl` in the lifecycle
- Added to config, prep, and ensure-labels

---

## EscalationContext Model

Captures everything available at escalation time. Each escalation site populates whatever fields it has.

```python
class AttemptRecord(BaseModel):
    attempt_number: int
    changes_made: bool
    error_summary: str
    timestamp: str

class EscalationContext(BaseModel):
    cause: str                                    # full cause (not truncated)
    origin_phase: str                             # which phase escalated
    ci_logs: str | None = None                    # full CI output (up to 12k chars)
    review_comments: list[str] = []               # reviewer feedback
    pr_diff: str | None = None                    # what was changed
    pr_number: int | None = None                  # associated PR if any
    code_scanning_alerts: list[str] = []          # security/quality findings
    previous_attempts: list[AttemptRecord] = []   # what was tried before
    agent_transcript: str | None = None           # reasoning from failed attempt
```

### Escalation Site Changes

Each phase that currently calls `escalate_to_hitl()` or `_escalate_to_hitl()` will instead:
1. Build an `EscalationContext` with available data
2. Store it in state via `state.set_escalation_context(issue_number, context)`
3. Call `escalate_to_diagnostic()` which swaps labels to `hydraflow-diagnose`

Sites that populate context:

| Site | Available Context |
|------|-------------------|
| `review_phase.py` — CI failure | `ci_logs`, `pr_diff`, `code_scanning_alerts`, `previous_attempts` |
| `review_phase.py` — review fix cap | `review_comments`, `pr_diff`, `previous_attempts` |
| `review_phase.py` — visual failure | `visual_evidence` (existing), `pr_diff` |
| `review_phase.py` — baseline policy | `pr_diff`, changed baseline files list |
| `implement_phase.py` — zero diff | `agent_transcript`, issue body |
| `implement_phase.py` — attempt cap | `previous_attempts`, `agent_transcript` |
| `plan_phase.py` — plan validation | `agent_transcript` |
| `merge_conflict_resolver.py` | `pr_diff`, conflict details |

---

## DiagnosticRunner — Two-Stage Agent

### Stage 1: Diagnose (Read-Only)

The diagnostic agent receives the full `EscalationContext` and produces a `DiagnosisResult`:

```python
class Severity(StrEnum):
    P0_SECURITY = "P0"    # secrets exposure, auth bypass, data loss risk
    P1_BLOCKING = "P1"    # pipeline blocked, crash loop, state corruption
    P2_FUNCTIONAL = "P2"  # wrong behavior, system keeps running
    P3_WIRING = "P3"      # missing DI, incomplete setup
    P4_HOUSEKEEPING = "P4" # cleanup, renaming, non-urgent

class DiagnosisResult(BaseModel):
    root_cause: str              # what specifically went wrong
    severity: Severity           # P0-P4 classification
    fixable: bool                # agent's confidence it can fix this
    fix_plan: str                # what it would change and where
    human_guidance: str          # what a human should know if this escalates
    affected_files: list[str]    # files that need changes
```

The agent runs read-only (no worktree) in this stage. It explores the codebase, reads the referenced files, and produces its analysis.

### Stage 2: Fix (Conditional)

Only runs if `fixable=True` from Stage 1. Creates a worktree and executes the fix plan:

1. Create worktree from the existing branch (if PR exists) or from main
2. Apply the fix guided by `DiagnosisResult.fix_plan` and `affected_files`
3. Run `make quality`
4. If quality passes: commit, push, create/update PR, transition to `hydraflow-review`
5. If quality fails: record the attempt in state, retry if under `max_diagnostic_attempts`
6. If all attempts exhausted or `fixable=False`: escalate to `hydraflow-hitl` with diagnosis

### Prompt Design

Stage 1 prompt includes:
```
Issue: #{number} — {title}
Body: {issue_body}

Escalation cause: {context.cause}
Origin phase: {context.origin_phase}

[If CI logs available]
CI Logs:
{context.ci_logs}

[If review comments available]
Review Feedback:
{context.review_comments}

[If PR diff available]
PR Diff:
{context.pr_diff}

[If previous attempts available]
Previous Attempts:
- Attempt {n}: {changes_made}, error: {error_summary}

[If agent transcript available]
Agent Reasoning From Failed Attempt:
{context.agent_transcript}

Classify the severity and determine if this is fixable automatically.
Output structured JSON with root_cause, severity, fixable, fix_plan, human_guidance, affected_files.
```

Stage 2 prompt includes the `DiagnosisResult` plus standard implementation instructions.

---

## DiagnosticLoop

`BaseBackgroundLoop` subclass following existing patterns (manifest_refresh_loop, memory_sync_loop, etc.).

### Config

```python
# In HydraFlowConfig:
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
diagnose_label: list[str] = Field(
    default=["hydraflow-diagnose"],
    description="Labels for issues in diagnostic analysis (OR logic)",
)
```

### Loop Behavior

```
_do_work():
    1. Fetch issues labeled hydraflow-diagnose (via IssueStore or direct fetch)
    2. For each issue (up to max_diagnosticians concurrently):
        a. Load EscalationContext from state
        b. Run DiagnosticRunner.diagnose() -> DiagnosisResult
        c. Store severity in state
        d. If fixable and attempts < max_diagnostic_attempts:
            - Run DiagnosticRunner.fix() in worktree
            - On success: transition to hydraflow-review
            - On failure: record attempt, retry or escalate
        e. If not fixable or attempts exhausted:
            - Post diagnosis comment on issue
            - Escalate to hydraflow-hitl with severity badge
    3. Publish DIAGNOSTIC_UPDATE events for dashboard
```

### Wiring Checklist

Per `CLAUDE.md` background loop guidelines:

- `src/service_registry.py` — `diagnostic_loop` field + `build_services()` instantiation
- `src/orchestrator.py` — entry in `bg_loop_registry` dict
- `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`
- `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`
- `src/config.py` — `diagnostic_interval` Field + `_ENV_INT_OVERRIDES` entry
- `src/prep.py` — `hydraflow-diagnose` label in `HYDRAFLOW_LABELS`
- `src/events.py` — `DIAGNOSTIC_UPDATE` event type

---

## Severity on Dashboard

When an issue reaches HITL with a diagnosis:

- Severity badge displayed on the HITL item in dashboard (P0 red, P1 orange, P2 yellow, P3 blue, P4 gray)
- Diagnosis posted as a structured comment on the GitHub issue:

```markdown
## Diagnostic Analysis

**Severity:** P2 — Functional Bug
**Root Cause:** Health check calls `queue_depths` but the method is named `get_queue_stats`
**Affected Files:** `src/dashboard_routes/_routes.py:1226`

### Fix Plan
Rename the method call from `queue_depths` to `get_queue_stats` on line 1226.

### Human Guidance
This is a straightforward method rename. The diagnostic agent could not verify the fix
because [reason]. A human should confirm the method signature hasn't changed.

---
*Generated by HydraFlow Diagnostic Agent*
```

---

## Attempt History Tracking

New state methods:

- `state.set_escalation_context(issue_number, EscalationContext)` — store full context at escalation time
- `state.get_escalation_context(issue_number) -> EscalationContext | None` — retrieve for diagnostic runner
- `state.add_diagnostic_attempt(issue_number, AttemptRecord)` — append attempt
- `state.get_diagnostic_attempts(issue_number) -> list[AttemptRecord]` — for retry decisions
- `state.set_diagnosis_severity(issue_number, Severity)` — for dashboard display

---

## What Changes in Existing Code

### Escalation sites (swap `escalate_to_hitl` for `escalate_to_diagnostic`)

All sites in `review_phase.py`, `implement_phase.py`, `plan_phase.py`, and `merge_conflict_resolver.py` that currently call `escalate_to_hitl()` or `_escalate_to_hitl()` will:
1. Build `EscalationContext` with available data
2. Call `escalate_to_diagnostic()` instead

The `_escalate_to_hitl()` method in `review_phase.py` and `escalate_to_hitl()` in `phase_utils.py` remain available — the diagnostic loop calls them when it needs to escalate after failed diagnosis.

### `PipelineEscalator` in `phase_utils.py`

Updated to call `escalate_to_diagnostic()` instead of `escalate_to_hitl()`. Accepts an optional `EscalationContext` parameter.

### HITL phase

`hitl_phase.py` `attempt_auto_fixes()` is removed — the diagnostic loop replaces it entirely. Issues that reach `hydraflow-hitl` are genuinely human-required and have a diagnosis attached.

---

## Out of Scope

- Suggested fix options for human (Option B from brainstorming) — can layer on later
- Auto-closing issues the diagnostic agent determines are invalid or already fixed
- Feedback loop from human HITL resolutions back into diagnostic agent training
- Dashboard filtering/sorting by severity (basic badge only for now)
