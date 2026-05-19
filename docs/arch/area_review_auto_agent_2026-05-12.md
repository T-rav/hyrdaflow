# Per-Area Code Review — Auto-Agent (HITL Pre-Flight) (slice 5.3 of 5)

**Date:** 2026-05-12
**Auditor:** Claude Sonnet 4.6 (slice 5.3 agent)
**Worktree SHA:** 038f2146
**Functional area:** Auto-Agent (HITL Pre-Flight) — ADR-0050 / ADR-0052

---

## Members audited

- **AutoAgentPreflightLoop** (`src/auto_agent_preflight_loop.py`, 288 lines)
- **SandboxFailureFixerLoop** (`src/sandbox_failure_fixer_loop.py`, 180 lines)
- **HITLController** (`src/hitl_controller.py`, 73 lines)
- **HITLPhase** (`src/hitl_phase.py`, 341 lines)
- **HITLRunner** (`src/hitl_runner.py`, 231 lines)
- Supporting layer: `src/preflight/` (agent.py, context.py, decision.py, runner.py, audit.py, auto_agent_runner.py)

---

## Matrix

| Component | Code Quality | Test Coverage | MockWorld Fidelity | Subprocess / Billing Safety | Wiki / ADR Currency |
|---|---|---|---|---|---|
| AutoAgentPreflightLoop | ✅ clean | ✅ covered | ✅ matches-reality | ⚠️ gap [bd:advisor-preflight-credit] | ✅ documented |
| SandboxFailureFixerLoop | ✅ clean | ✅ covered | ❌ missing [bd:advisor-sandbox-fixer-scenario] | ✅ safe | ✅ documented |
| HITLController | ✅ clean | ✅ covered | N/A | N/A | ⚠️ sparse [bd:advisor-hitl-wiki] |
| HITLPhase | ✅ clean | ✅ covered | N/A | ⚠️ gap [bd:advisor-hitl-batch-abort] | ⚠️ sparse [bd:advisor-hitl-wiki] |
| HITLRunner | ✅ clean | ✅ covered | N/A | ✅ safe | ✅ documented |
| preflight/agent.py | ✅ clean | ✅ covered | N/A | ❌ unsafe [bd:advisor-preflight-credit] | ✅ documented |
| preflight/decision.py | ✅ clean | ✅ covered | N/A | N/A | ✅ documented |
| preflight/context.py | ✅ clean | ⚠️ thin [bd:advisor-preflight-context-tests] | N/A | N/A | ✅ documented |
| preflight/runner.py | ✅ clean | ⚠️ thin [bd:advisor-preflight-context-tests] | N/A | N/A | ✅ documented |

**Column counts:**
- Code quality: ✅ 9 / ⚠️ 0 / ❌ 0
- Test coverage: ✅ 6 / ⚠️ 2 / ❌ 0
- MockWorld fidelity: ✅ 1 / ⚠️ 0 / ❌ 1 / N/A 7
- Subprocess/billing safety: ✅ 2 / ⚠️ 1 / ❌ 1 / N/A 5
- Wiki/ADR currency: ✅ 7 / ⚠️ 2 / ❌ 0

---

## Per-Component Notes

### AutoAgentPreflightLoop (`src/auto_agent_preflight_loop.py`)

**Code quality: ✅ clean**
All methods are well-scoped (longest is `_process_one` at ~95 lines including comments). The five-checkpoint wiring pattern is followed correctly. The comment explaining alphabetical sub-label sorting for determinism (lines 133–138) is load-bearing and clear. `_resolve_worktree` mirrors the diagnostic-loop fallback pattern.

**Test coverage: ✅ covered**
Unit tests (`test_auto_agent_preflight_loop.py`, 243 lines) cover kill-switch, config-disable, daily-budget gate, reconcile-on-close, deny-list bypass, attempt-cap, and all three worktree-resolution paths. Scenario layer (`tests/scenarios/test_auto_agent_preflight.py`) adds full-loop MockWorld tests for resolved, fatal, pr_failed, exhausted, and deny-list paths — the five load-bearing branches.

**MockWorld fidelity: ✅ matches-reality**
Scenario tests stub `_build_spawn_fn` to return a controlled `PreflightSpawn` and exercise the real `apply_decision` path. Label assertions are specific (`add_labels`, `remove_label` per label). The adversarial corpus (`tests/auto_agent/adversarial/`, 12 entries) covers edge-case response parsing.

**Subprocess/billing safety: ⚠️ gap [bd:advisor-preflight-credit]**
`AutoAgentPreflightLoop._process_one` calls `run_preflight(...)` with no exception handler. `run_preflight` in `src/preflight/agent.py` (line 73) has a bare `except Exception as exc` around `deps.spawn_fn(...)` that converts ALL exceptions — including `CreditExhaustedError` propagated by `BaseSubprocessRunner.run()` — into a `fatal` `PreflightResult`. The credit error is silently consumed, the loop continues polling, and the daily-budget gate is the only remaining circuit-breaker (only fires when `auto_agent_daily_budget_usd` is configured). Without that cap set, a credit-exhausted account burns attempts indefinitely. The fix is `reraise_on_credit_or_bug(exc)` before the return inside `run_preflight`'s except block.

**Wiki/ADR currency: ✅ documented**
ADR-0050 is thorough — covers the full pipeline, prompt envelope, sub-label routing, attempt cap, deny-list, cost/wall-clock caps, dashboard, and source-file citations. The `dark-factory.md` §2.7 entry covers the deny-list rationale. The adversarial corpus and scenario coverage are explicitly listed in ADR-0050.

---

### SandboxFailureFixerLoop (`src/sandbox_failure_fixer_loop.py`)

**Code quality: ✅ clean**
Well-structured 180-line file. Kill-switch and static-config gates are correct. `reraise_on_credit_or_bug` is called in both the label-swap and runner exception handlers. The `_build_prompt` method correctly reads the `sandbox_fix.md` envelope. The `no-auto-fix` opt-out label and attempt-cap-then-escalate pattern are cleanly implemented.

**Test coverage: ✅ covered**
7 unit tests (`test_sandbox_failure_fixer_loop.py`, 212 lines) cover kill-switch, static-config-disable, no-candidates, dispatch, label-swap-at-cap, opt-out skip, and crashed-runner counting. Good behavioral breadth for a 180-line module.

**MockWorld fidelity: ❌ missing [bd:advisor-sandbox-fixer-scenario]**
No MockWorld scenario exercises this loop. The catalog builder `_build_sandbox_failure_fixer` exists in `tests/scenarios/catalog/loop_registrations.py` (line 661) but no scenario file instantiates it. The coherency drift report (2026-05-12) also flagged this gap as `bd:advisor-rqj`. Without a scenario test: (a) the label-routing sequence `sandbox-fail-auto-fix → sandbox-hitl` is never validated against a mock pipeline; (b) the integration between the loop and the `/api/sandbox-hitl` HITL queue is untested at the scenario tier.

**Subprocess/billing safety: ✅ safe**
Both exception handlers in `_do_work` (lines 123, 139) call `reraise_on_credit_or_bug(exc)` before the swallow path, consistent with `dark-factory.md` §2.2. Pattern is correct.

**Wiki/ADR currency: ✅ documented**
ADR-0052 §5 describes the loop and its escalation path. The `dark-factory.md` §2 mentions the 3-attempt cap and `sandbox-hitl` routing. The loop's module docstring cross-references ADR-0050 and Task 3.12.

---

### HITLController (`src/hitl_controller.py`)

**Code quality: ✅ clean**
Thin coordinator (73 lines) correctly delegates to `HITLPhase` and `IssueFetcher`. No complexity concerns.

**Test coverage: ✅ covered**
`test_hitl_controller.py` (121 lines) covers all public methods. Acceptable for a thin delegation layer.

**MockWorld fidelity: N/A**
`HITLController` is not a loop — it's a component wired into the orchestrator. Scenario-level coverage comes via the orchestrator's integration tests.

**Subprocess/billing safety: N/A**
No subprocess calls.

**Wiki/ADR currency: ⚠️ sparse [bd:advisor-hitl-wiki]**
`HITLController` is mentioned in ADR-0022 (integration test architecture) but has no dedicated wiki entry. The wiki `architecture-patterns-practices.md` covers coordinator patterns generally. Given this is the entry point for human corrections, a wiki entry explaining the Controller → Phase → Runner delegation would reduce gotcha risk for future contributors.

---

### HITLPhase (`src/hitl_phase.py`)

**Code quality: ✅ clean**
Well-structured 341-line class. `process_corrections` and `_process_one_hitl` are cleanly separated. The correction snapshot-and-clear pattern (lines 112–114) prevents re-processing. The `_active_hitl_issues` set and callback pattern for UI live-updating are correct.

**Test coverage: ✅ covered**
`test_hitl_phase.py` (725 lines, 30+ tests) is the most thorough test file in this area. Covers success/failure paths, origin-label restoration, visual-evidence clearing, event publishing, stop-event cancellation, memory suggestions, HITL lessons, credit/auth/memory error propagation, and active-issues cleanup on critical errors.

**MockWorld fidelity: N/A**
HITLPhase is not a standalone loop. Integration is via orchestrator scenarios and direct unit coverage.

**Subprocess/billing safety: ⚠️ gap [bd:advisor-hitl-batch-abort]**
`process_corrections` (line 123) iterates `asyncio.as_completed(tasks)` with a bare `await task` and no exception handler. `_process_one_hitl` re-raises `(AuthenticationError, CreditExhaustedError, MemoryError)` (line 326). When any task raises one of these, the bare `await task` propagates the exception out of `process_corrections`, aborting the entire batch. Remaining corrections that were already popped from `_hitl_corrections` (lines 112–114) are silently lost — never retried. This is a known tracked bug: `tests/regressions/test_issue_6958.py` (3 xfail tests, strict=False, message "fix not yet landed").

**Wiki/ADR currency: ⚠️ sparse [bd:advisor-hitl-wiki]**
`HITLPhase` is documented in ADR-0022 (integration architecture) but has no wiki entry of its own. Given the complexity of the correction lifecycle (origin-label restoration, worktree management, memory lessons, trace rollup), a wiki entry would reduce the chance of future contributors misunderstanding the state cleanup sequence.

---

### HITLRunner (`src/hitl_runner.py`)

**Code quality: ✅ clean**
The `_classify_cause` function handles the visual/needs_info/ci/merge-conflict priority ordering correctly, with unit tests for all boundary cases (including the `needs_info`-before-ci substring ambiguity). Prompt templates are comprehensive and include explicit no-push and no-refactoring rules.

**Test coverage: ✅ covered**
`test_hitl_runner.py` (510 lines) covers cause classification, all prompt-template branches, command building, dry-run, success/failure result shapes, prompt-stats pruning, and exception handling.

**MockWorld fidelity: N/A**
Not a loop.

**Subprocess/billing safety: ✅ safe**
`reraise_on_credit_or_bug(exc)` is called correctly at line 152 in the exception handler.

**Wiki/ADR currency: ✅ documented**
Referenced in ADR-0022 and ADR-0050. The runner is load-bearing but not complex enough to warrant a standalone wiki entry.

---

### preflight/agent.py

**Code quality: ✅ clean**
`run_preflight` is 105 lines with clear cap-check → parse → demote logic. The `pr_failed` demotion for `resolved`-without-URL (spec §2.2) is correctly implemented and tested.

**Test coverage: ✅ covered**
`test_preflight_agent.py` (176 lines) covers 8 scenarios: resolved, crash, spawn-exception, cost-cap, wall-clock-cap, unparseable output, hash stability, and multiple format variants.

**Subprocess/billing safety: ❌ unsafe [bd:advisor-preflight-credit]**
The `except Exception as exc` at line 73 around `deps.spawn_fn(...)` does NOT call `reraise_on_credit_or_bug`. When `BaseSubprocessRunner.run()` propagates `CreditExhaustedError`, it is caught here and converted to `PreflightResult(status="fatal", ...)`. This silences the billing signal before it reaches `AutoAgentPreflightLoop._process_one()`. The loop then posts a `human-required` + `auto-agent-fatal` label set (correct behavior for that result), but keeps the orchestrator running rather than suspending — burning attempt budget against an exhausted account. Fix: add `reraise_on_credit_or_bug(exc)` as the first line inside the except block.

No test currently asserts that `CreditExhaustedError` propagates through `run_preflight`.

---

### preflight/context.py and preflight/runner.py

**Code quality: ✅ clean**
Both modules are compact and clearly scoped. `gather_context` degrades gracefully on all external port failures. `render_prompt` / `parse_agent_response` are pure functions.

**Test coverage: ⚠️ thin [bd:advisor-preflight-context-tests]**
`test_preflight_context.py` has 3 tests covering missing-escalation-context, wiki-query-failure, and prior-attempts. Missing: sentry-lookup failure path, git-log failure path, and the `sublabel_extras` field (populated as empty dict — never tested populated). `test_preflight_runner.py` has 4 tests covering render and parse; neither tests the case where `sub_label.md` has a `{`-format field that is absent from kwargs (a `KeyError` that would turn every sub-label run `fatal` silently if a prompt template is updated without updating the render call).

---

## Cross-Cutting Observations

### Sub-labels without specialist prompts

Nine sub-labels are applied alongside `hitl-escalation` in production code but have no dedicated prompt file — they fall through to `_default.md`:
- `retry-lineage-exhausted` (from `staging_bisect_loop.py`)
- `rc-red-post-revert-red` (from `staging_bisect_loop.py`)
- `rc-red-verify-timeout` (from `staging_bisect_loop.py`)
- `bisect-harness-failure` (from `staging_bisect_loop.py`)
- `fake-repair-stuck` (from `contract_refresh_loop.py`)
- `corpus-learning-stuck` (from `corpus_learning_loop.py`)
- `adr-drift-stuck` (config `adr_drift_stuck_label`)
- memory-backlog variants (from `memory_backlog_loop.py`)

The `_default.md` prompt is functional but generic — the auto-agent has no specialist knowledge of the escalation type and must infer entirely from issue body and escalation context. This aligns with the Slice 4 / ADR-0063 workstream `advisor-5nxu` (specialist-aware preflight playbooks) — these gaps are best addressed there rather than filing separate beads here.

### Known unfixed regression (issue #6958)

`HITLPhase.process_corrections` has a batch-abort bug when any correction task raises `AuthenticationError` / `CreditExhaustedError`: remaining popped corrections are silently lost. Three xfail regression tests document this (`tests/regressions/test_issue_6958.py`). The fix is to wrap `await task` in a try/except that catches and logs non-critical exceptions while re-raising billing-fatal ones after the batch completes.

### No MockWorld scenario for SandboxFailureFixerLoop

The only integration verification for `SandboxFailureFixerLoop` is the 7-unit-test file. The label routing `sandbox-fail-auto-fix → sandbox-hitl` and the interaction with the `/api/sandbox-hitl` HITL endpoint are never tested end-to-end at the scenario layer. This is higher risk because the loop is part of the CI self-healing path.

---

## Bead inventory (gaps to file as issues)

| Bead ID | Kind | Title |
|---|---|---|
| bd:advisor-preflight-credit | safety | `run_preflight` swallows `CreditExhaustedError` — billing signal silenced at auto-agent layer |
| bd:advisor-hitl-batch-abort | safety | `HITLPhase.process_corrections` aborts batch on credit/auth error, losing pending corrections (issue #6958) |
| bd:advisor-sandbox-fixer-scenario | tests | `SandboxFailureFixerLoop` has no MockWorld scenario — label-routing and `/api/sandbox-hitl` flow untested |
| bd:advisor-hitl-wiki | docs | `HITLController` and `HITLPhase` lack wiki entries — correction lifecycle undocumented for future contributors |
| bd:advisor-preflight-context-tests | tests | `preflight/context.py` and `preflight/runner.py` test coverage thin — sentry/git-log failure paths and prompt-template KeyError risk uncovered |
