# HITL Issue Resolution Log

**Date:** 2026-02-28
**Purpose:** Track manual resolution of HITL issues to identify automation failure patterns.

## Common Failure Pattern

Most issues (7 of 11 implementable) had complete plans scored 100/100 but the implementation agent produced **zero commits**. This is a systemic implementer failure, not a planning issue.

## Resolution Order

| Priority | Issue | Title | Category | Status |
|----------|-------|-------|----------|--------|
| 1 | #1065 | Test Quality: fixture cleanup | Merge conflict on PR #1613 | DONE |
| 2 | #1622 | Race condition in flat-to-namespaced migration | Target file doesn't exist | DONE |
| 3 | #1464 | Remove +/- controls from session sidebar | Small UI removal | DONE |
| 4 | #1636 | Verify: EventLog mounted in UI | Verification only | DONE |
| 5 | #1625 | Verify: Persist worker last-run status | Verification only | DONE |
| 6 | #830 | Reviewer frequently fixing implementation | Prompt enhancement | DONE |
| 7 | #1109 | Standardize system event labels | Frontend refactor | DONE |
| 8 | #1102 | Memory manager cleanup for stale items | Backend feature | DONE |
| 9 | #1114 | Display credit reset time in local timezone | Full-stack feature | DONE |
| 10 | #1539 | PipelineStats model and emission | Backend feature (epic blocker) | DONE |
| 11 | #1317 | Model-pricing JSON asset | Large (11 files) | PENDING |
| — | #1467-1474 | Multi-repo epic (8 issues) | Deferred — large epic | DEFERRED |
| — | #1630-1632 | ADR drafts (3 issues) | Deferred — architectural | DEFERRED |

---

## Resolutions

### #1065 — Test Quality: Clean up fixture organization and scope
**PR:** #1613 (open, CI green)
**Problem:** Implementation done but PR had 13/15 files conflicting after main diverged.
**Resolution:** Closed PR #1613. Re-labeled issue to `hydraflow-plan` for fresh implementation.
**Root cause of HITL:** PR went stale while main evolved rapidly. The automation's PR unsticker tried to merge but couldn't resolve conflicts.
**Automation fix:** PR unsticker should detect >5 conflicting files and close+re-queue instead of retrying merge.

---

### #1622 — Race condition in concurrent flat-to-namespaced migration
**Problem:** Issue filed for `hydraflow/persistence.py` which doesn't exist. Speculative issue.
**Resolution:** Closed as "not planned". Should be re-filed when migration logic exists.
**Root cause of HITL:** Triage created an issue for hypothetical future code. The triage agent should validate that referenced files/functions actually exist before creating issues.
**Automation fix:** Triage should verify file/function existence before accepting issues.

---

### #1464 — Remove +/- controls from session sidebar
**Problem:** Agent produced zero commits despite complete plan.
**Resolution:** PR #1638 — removed buttons, handlers, styles; updated grid and tests. 28 tests pass.
**Root cause of HITL:** Zero-commit implementer bug. The code change was straightforward (remove ~70 lines).
**Automation fix:** Investigate why implementer produces zero commits on simple deletion tasks.

---

### #1636 — Verify: EventLog component mounted in UI
**Problem:** PR #1621 claimed to fix but EventLog is still never mounted as `<EventLog />`. Only helper functions imported.
**Resolution:** Verification FAILED. Re-labeled to `hydraflow-plan` for fresh implementation.
**Root cause of HITL:** Merged PR didn't actually solve the issue. Review phase didn't catch that the component wasn't mounted.
**Automation fix:** Review agent should verify acceptance criteria against actual code, not just that tests pass.

---

### #1625 — Persist background worker last-run status across restarts
**Problem:** Worker states held in-memory only (`_bg_worker_states` on Orchestrator). No persistence to `state.json`.
**Resolution:** Verification FAILED. Re-labeled to `hydraflow-plan` for fresh implementation.
**Root cause of HITL:** PR #1618 didn't implement actual persistence. Same issue as #1636 — merged PR didn't solve the problem.
**Automation fix:** Verification judge should run code-level checks (grep for save/load patterns) not just manual test instructions.

---

### #830 — Reviewer frequently fixing implementation (self-check)
**PR:** #1639
**Problem:** Agent produced zero commits despite complete plan. Issue asked for a pre-commit self-check checklist.
**Resolution:** Added `_SELF_CHECK_CHECKLIST` class constant to `AgentRunner` (8 checklist items), injected into prompt. Expanded `_build_pre_quality_review_prompt` scope. 4 new tests, 109 total pass.
**Root cause of HITL:** Zero-commit implementer bug on a prompt-addition task.
**Automation fix:** Implementer should be able to handle prompt/string additions without producing zero commits.

---

### #1109 — Standardize system event labels
**PR:** #1640
**Problem:** Agent produced zero commits. Issue asked for consistent event type labels in the event log.
**Resolution:** Added `EVENT_PROCESS_MAP` to `constants.js`, `processLabel()` to `EventLog.jsx`, updated `Livestream.jsx`. Updated tests from raw type names to bracketed process labels. 55 tests pass.
**Root cause of HITL:** Zero-commit implementer bug on a UI refactor task.
**Automation fix:** Same systemic issue — implementer zero-commit pattern.

---

### #1102 — Memory manager stale item cleanup
**PR:** #1641
**Problem:** Agent produced zero commits. Issue asked for pruning stale memory item files.
**Resolution:** Added `_prune_stale_items()` to `MemorySyncWorker`, `memory_prune_stale_items` config flag, updated `_close_synced_issues` return type, updated `MemorySyncResult`. 4 new tests, 140 total pass.
**Root cause of HITL:** Zero-commit implementer bug on a multi-file backend task.
**Automation fix:** Same systemic issue — implementer zero-commit pattern.

---

### #1114 — Display credit reset time in local timezone
**PR:** #1642
**Problem:** Agent produced zero commits. Issue asked for threading `credits_paused_until` through the full stack.
**Resolution:** Added property to orchestrator, threaded through dashboard_routes→WebSocket→React context→Header. Added `creditResumeTime` style, `toLocaleTimeString()` display. 2 new model tests.
**Root cause of HITL:** Zero-commit implementer bug on a full-stack feature.
**Automation fix:** Same systemic issue — implementer zero-commit pattern.

---

### #1539 — PipelineStats model and periodic emission
**PR:** #1643
**Problem:** Agent produced zero commits. Issue asked for unified pipeline stats model and periodic emission.
**Resolution:** Added `StageStats`, `ThroughputStats`, `PipelineStats` models. Added `PIPELINE_STATS` event type. Added `_build_pipeline_stats()`, `emit_pipeline_stats()`, `_pipeline_stats_loop()` to orchestrator. 14 new tests across 3 files.
**Root cause of HITL:** Zero-commit implementer bug on a backend feature spanning 3 files.
**Automation fix:** Same systemic issue — implementer zero-commit pattern.

---
