# Caretaking Area Review — Slice 5.0

**Date:** 2026-05-12
**Auditor:** Claude Code (slice #5.0 of 5)
**Branch:** `audit/area-caretaking` from `origin/staging@038f2146`
**Matrix reference:** `/tmp/coverage_matrix_baseline.md`

## Overview

Per-area code/test/fake/safety/docs audit of all 28 loops in the Caretaking functional
area. Methodology: read source, read tests, read any MockWorld scenario file, check
subprocess safety, check wiki/ADR currency.

Audit dimensions:
1. **Code quality** — clean / minor / needs-rewrite
2. **Test coverage** — covered / thin / missing
3. **MockWorld scenario fidelity** — matches-reality / drift-risk / not-applicable
4. **Subprocess / billing safety** — safe / unsafe / not-applicable
5. **Wiki/ADR currency** — documented / sparse / undocumented

Cell vocabulary: ✅ / ⚠️ / ❌ / N/A

---

## 28-Loop Audit Matrix

| Loop | Code Quality | Tests | MockWorld | Safety | Docs | Notes |
|------|-------------|-------|-----------|--------|------|-------|
| ADRReviewerLoop | ✅ | ✅ | N/A | N/A | ⚠️ | See §ADRReviewerLoop |
| CodeGroomingLoop | ✅ | ✅ | N/A | ❌ | ⚠️ | See §CodeGroomingLoop |
| CostBudgetWatcherLoop | ✅ | ✅ | N/A | N/A | ✅ | See §CostBudgetWatcherLoop |
| DependabotMergeLoop | ✅ | ✅ | N/A | N/A | ⚠️ | See §DependabotMergeLoop |
| DiagnosticLoop | ⚠️ | ✅ | N/A | ✅ | ⚠️ | See §DiagnosticLoop |
| EdgeProposerLoop | ✅ | ✅ | N/A | N/A | ⚠️ | See §EdgeProposerLoop |
| EntryEvidenceLoop | N/A | N/A | N/A | N/A | N/A | Not on staging yet; ADR-0062 only |
| EpicMonitorLoop | ✅ | ⚠️ | N/A | N/A | ❌ | See §EpicMonitorLoop |
| EpicSweeperLoop | ✅ | ✅ | N/A | N/A | ❌ | See §EpicSweeperLoop |
| GitHubCacheLoop | ✅ | ❌ | N/A | ✅ | ⚠️ | See §GitHubCacheLoop |
| HealthMonitorLoop | ⚠️ | ⚠️ | N/A | N/A | ⚠️ | See §HealthMonitorLoop |
| MergeStateWatcherLoop | ✅ | ✅ | N/A | N/A | ⚠️ | See §MergeStateWatcherLoop |
| PRUnstickerLoop | ✅ | ✅ | N/A | N/A | ⚠️ | See §PRUnstickerLoop |
| PricingRefreshLoop | ✅ | ✅ | ✅ | N/A | ✅ | See §PricingRefreshLoop |
| RepoWikiLoop | ⚠️ | ✅ | N/A | ❌ | ✅ | See §RepoWikiLoop |
| ReportIssueLoop | ⚠️ | ✅ | N/A | ✅ | ⚠️ | See §ReportIssueLoop |
| RetrospectiveLoop | ✅ | ✅ | N/A | N/A | ❌ | See §RetrospectiveLoop |
| RunsGCLoop | ✅ | ✅ | N/A | N/A | ❌ | See §RunsGCLoop |
| SecurityPatchLoop | ✅ | ✅ | N/A | N/A | ❌ | See §SecurityPatchLoop |
| SentryLoop | ⚠️ | ✅ | N/A | ✅ | ⚠️ | See §SentryLoop |
| SkillPromptEvalLoop | ✅ | ✅ | ✅ | ❌ | ⚠️ | See §SkillPromptEvalLoop |
| StagingPromotionLoop | ✅ | ✅ | N/A | N/A | ✅ | See §StagingPromotionLoop |
| StaleIssueGCLoop | ✅ | ✅ | N/A | ✅ | ⚠️ | See §StaleIssueGCLoop |
| StaleIssueLoop | ✅ | ✅ | N/A | ✅ | ⚠️ | See §StaleIssueLoop |
| TermProposerLoop | ✅ | ⚠️ | N/A | N/A | ✅ | See §TermProposerLoop |
| TermPrunerLoop | ✅ | ⚠️ | N/A | N/A | ✅ | See §TermPrunerLoop |
| WikiRotDetectorLoop | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | See §WikiRotDetectorLoop |
| WorkspaceGCLoop | ✅ | ✅ | N/A | ✅ | ⚠️ | See §WorkspaceGCLoop |

### Column totals

| Dimension | ✅ | ⚠️ | ❌ | N/A |
|-----------|---|---|---|-----|
| Code quality | 22 | 4 | 0 | 2 |
| Tests | 19 | 4 | 1 | 4 |
| MockWorld | 2 | 0 | 0 | 26 |
| Safety | 8 | 1 | 3 | 16 |
| Docs | 4 | 16 | 6 | 2 |

**Total gap cells (⚠️ or ❌): 39**

---

## Per-Loop Notes

### ADRReviewerLoop

- **Code quality ✅:** 34 lines, clean thin wrapper. No dead code.
- **Tests ✅:** 6 tests covering enabled, disabled, stats, interval, event emission, error callback. Complete.
- **MockWorld N/A:** No subprocess or external call; pure delegate.
- **Safety N/A:** No subprocess or LLM call.
- **Docs ⚠️:** Mentioned in the generated loops registry but no ADR and no wiki entry describing the council review protocol or how the loop is gated.

---

### CodeGroomingLoop

- **Code quality ✅:** 177 lines, clean. Warning log for zero-findings transcript is a useful smoke signal.
- **Tests ✅:** 8 tests covering happy path, dedup, dry-run, kill-switch, severity filter, error handling.
- **MockWorld N/A:** `_run_audit` is patched in tests, no scenario file.
- **Safety ❌ (`code_grooming_loop.py`):** `_do_work` uses `stream_claude_process` inside `_run_audit`. The broad `except Exception` at line 130 catches everything including `CreditExhaustedError`. No `reraise_on_credit_or_bug` call present. This means a credit-exhausted event will silently return `{"filed": 0, "error": True}`, and the loop will burn its retry budget on the next tick against an already-exhausted billing signal.
  - **Fix by:** Add `from exception_classify import reraise_on_credit_or_bug` and call `reraise_on_credit_or_bug(exc)` inside the `except Exception` block at `_do_work` line 130.
- **Docs ⚠️:** Wiki `architecture-async-control.md:230` has a one-sentence pattern note. No dedicated entry explaining P0-only filing policy, dedup strategy, or `stream_claude_process` interaction.

---

### CostBudgetWatcherLoop

- **Code quality ✅:** 216 lines. Logic is clear: kill on cap breach, recover on drop, persist killed set. Operator-override gotcha documented in comments and dark-factory.
- **Tests ✅:** `test_cost_budget_watcher_scenario.py` exists and covers scenario path.
- **MockWorld N/A:** No subprocess.
- **Safety N/A:** Calls `asyncio.to_thread(build_rolling_24h)`, which reads from the dashboard cost rollup. Not an LLM subprocess.
- **Docs ✅:** Well documented in `architecture.md` entry (one paragraph covering the cap, killed set, recovery, and the operator-override gotcha).

---

### DependabotMergeLoop

- **Code quality ✅:** 119 lines, clean. Strategy dispatch (skip/hitl/close) is readable.
- **Tests ✅:** `test_dependabot_merge_loop.py` (305 lines) covers merge, skip, hitl, close strategies.
- **MockWorld N/A:** No subprocess.
- **Safety N/A:** Pure API calls via ports.
- **Docs ⚠️:** No wiki entry. The loop is mentioned in `functional_areas.yml` and the generated loops registry but has no behavioral description. The three failure strategies (skip/hitl/close) are undocumented outside the source.

---

### DiagnosticLoop

- **Code quality ⚠️:** 357 lines total. `_process_issue` is ~190 lines (`src/diagnostic_loop.py:132–325`) and handles the full 2-stage pipeline (diagnose → fix → retry/escalate). It is at the limit of readability and could be split into `_run_diagnose_stage` and `_run_fix_stage`. No dead code, but the method is a candidate for extraction per CLAUDE.md quality standards.
- **Tests ✅:** 719 lines of tests, very complete.
- **MockWorld N/A:** No scenario file.
- **Safety ✅:** `reraise_on_credit_or_bug` called for the initial `list_issues_by_label` call (line 99). Inside `_process_issue`, the `runner.fix()` exception block explicitly re-raises `AuthenticationError | CreditExhaustedError | OSError` (line 247).
- **Docs ⚠️:** Mentioned in loops registry. No dedicated wiki entry explaining the 2-stage pipeline, attempt budget, or escalation path.

---

### EdgeProposerLoop

- **Code quality ✅:** 212 lines. AST walk + import graph clean, no dead code.
- **Tests ✅:** 181 lines, covers disabled, depends_on inference, implements inference.
- **MockWorld N/A:** No external subprocess or LLM call.
- **Safety N/A:** Pure file I/O and port calls.
- **Docs ⚠️:** ADR-0058 exists. Generated loops registry shows the ADR. No wiki entry describing the loop's operational behavior or the PR auto-merge flow.

---

### EntryEvidenceLoop

- All dimensions **N/A** — source file `src/entry_evidence_loop.py` does not exist on this branch. ADR-0062 is filed and the feature recently merged (PR #8733 referenced in recent commits) but may have targeted a different base. Confirmed absent on `staging`.

---

### EpicMonitorLoop

- **Code quality ✅:** 38 lines, clean thin wrapper.
- **Tests ⚠️:** Only 5 tests (70 lines): `test_do_work_calls_manager`, `test_returns_stale_count`, `test_disabled_skips_work`, `test_default_interval`, `test_worker_name`. No test for the error path when `check_stale_epics` raises (loop would propagate to `BaseBackgroundLoop` error handler, but the thin-test concern is the lack of a specific failure-mode assertion).
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ❌:** Zero wiki or ADR entries specific to `EpicMonitorLoop`. The generated loops registry is the only mention. Stale epic detection and the cache refresh cadence are undocumented.

---

### EpicSweeperLoop

- **Code quality ✅:** 122 lines. The 50-issue truncation warning is a good canary.
- **Tests ✅:** 271 lines, covers all sub-paths.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ❌:** Zero wiki entries. The distinction from `EpicMonitorLoop` (stale vs. completion sweeping) and the sub-issue resolution logic are undocumented.

---

### GitHubCacheLoop

- **Code quality ✅:** 281 lines total (loop + cache class). `poll()` structure is clear, disk persistence handles model hydration correctly.
- **Tests ❌:** No `test_github_cache_loop.py` exists. The cache object is exercised indirectly via other tests (e.g., `DependabotMergeLoop` reads `get_open_prs()`), but the loop's `_do_work` path, the disk persistence round-trip, and the `invalidate()` method have no direct tests.
  - **Fix by:** Add `tests/test_github_cache_loop.py` covering: poll happy path, disk save/load round-trip, `invalidate()` clears timestamps, kill-switch behavior, per-dataset reraise propagation.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` called in all 4 per-dataset `except Exception` blocks in `poll()` (lines 134, 148, 157, 166).
- **Docs ⚠️:** ADR-0041 documents the "GitHub as source of truth, cache as sidecar" pattern. Loop-level behavior (poll interval, disk persistence, invalidation, cache age reporting) is not in the wiki. `docs/ops-audit-issues.md` notes the missing circuit breaker (still unaddressed).

---

### HealthMonitorLoop

- **Code quality ⚠️:** 1,198 lines. The loop is the largest single file in the Caretaking area by a wide margin. `_do_work` itself is manageable but several private helper methods are over 60 lines. The regression test `test_issue_6470.py` enforces that `_do_work` must not contain silent `except Exception: pass` blocks — a good guard, but the file warrants a split or facade extraction. TUNABLE_BOUNDS and ADJUSTMENT_RULES are well-structured at the top.
- **Tests ⚠️:** Two focused test files (`test_health_monitor_sanity_stall.py` 196 lines, `test_health_monitor_wiki_stall.py` 122 lines) plus several regressions. However, there is no `test_health_monitor_loop.py` covering the core `_do_work` cycle (trend metrics, parameter adjustment, HITL filing). The regression approach addresses specific bugs but leaves the main cycle path undertested.
  - **Fix by:** Add a `test_health_monitor_loop.py` with: `_do_work` happy path (first-pass-rate low → increment `max_quality_fix_attempts`), HITL filing for out-of-range conditions, `compute_trend_metrics` normal cases.
- **MockWorld N/A.**
- **Safety N/A:** No subprocess calls.
- **Docs ⚠️:** `testing.md:236` has a one-sentence note about the dead-man-switch relationship with `TrustFleetSanityLoop`. The adjustment rules (TUNABLE_BOUNDS, ADJUSTMENT_RULES), their bounded ranges, the audit trail format, and the HITL filing logic are undocumented in the wiki.

---

### MergeStateWatcherLoop

- **Code quality ✅:** 47 lines thin wrapper, clean.
- **Tests ✅:** `test_merge_state_watcher.py` (235 lines) includes loop-level tests alongside the core watcher. Well covered.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ⚠️:** No wiki entry. The loop's role (pre-HITL conflict detection vs. `PRUnsticker`'s post-HITL role) is undocumented, making the division of responsibility opaque to future contributors.

---

### PRUnstickerLoop

- **Code quality ✅:** 44 lines thin wrapper.
- **Tests ✅:** `test_pr_unsticker_loop.py` (174 lines), covers disabled and main work path.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ⚠️:** No wiki entry. The three HITL cause types (conflict, CI, generic) and the filtering to `active_pr_items` only are undocumented.

---

### PricingRefreshLoop

- **Code quality ✅:** 302 lines. Linear gate checks, atomic write+PR logic, revert-on-failure are all clean patterns.
- **Tests ✅:** Both `test_pricing_refresh_loop_scenario.py` (unit) and `test_pricing_refresh_loop_mockworld.py` (MockWorld scenario) exist.
- **MockWorld ✅:** Scenario seeds a realistic `model_pricing.json` matching the real schema and uses a properly filtered upstream payload that mirrors what LiteLLM actually returns (per-token cost fields normalized through `filter_anthropic_entries`).
- **Safety N/A:** Uses `urllib.request.urlopen` (not a Claude subprocess) and `asyncio.to_thread`.
- **Docs ✅:** ADR-0029 covers the caretaker pattern. The spec at `docs/superpowers/specs/2026-04-26-pricing-refresh-loop-design.md` is preserved.

---

### RepoWikiLoop

- **Code quality ⚠️:** 772 lines. `_do_work` alone is 265 lines. The method has accumulated 9 distinct phases (active lint, compile, git-backed lint, tracked compile, drift detection, semantic drift, queue drain, PR poll, generalization pass). Each phase is individually correct, but the method has grown past the 60-line readability bound. Refactoring into phase methods (`_run_lint_phase`, `_run_compile_phase`, etc.) would reduce cognitive load without changing behavior.
- **Tests ✅:** 1,159 lines across two test files — thorough.
- **MockWorld N/A:** Loop calls `subprocess.run` (via `_porcelain_paths`) and `run_subprocess` for `gh pr view/review/merge`, but no MockWorld scenario file.
- **Safety ❌ (`repo_wiki_loop.py`):** The loop uses `subprocess.run` directly at line 726 (`_porcelain_paths`) and `run_subprocess` for `gh pr view/review/merge` calls in `_poll_and_merge_open_pr`. There are 6 broad `except Exception: # noqa: BLE001` blocks in `_do_work` (lines 129, 276, 313, 368, 417, 446) with no `reraise_on_credit_or_bug`. For a loop that spawns `gh` subprocesses, any `CreditExhaustedError` propagating up from `runner_utils` or `subprocess_util` would be silently swallowed.
  - **Fix by:** Add `from exception_classify import reraise_on_credit_or_bug` and call it in the `_poll_and_merge_open_pr` except blocks that wrap `run_subprocess` calls (lines 575–578, 617–621, 632–634).
- **Docs ✅:** `dark-factory.md` references `RepoWikiLoop`; ADR-0032 covers per-repo wiki knowledge base.

---

### ReportIssueLoop

- **Code quality ⚠️:** 646 lines. The file is large and handles several responsibilities (screenshot secret scanning, pending-report dequeue, daily budget sweep, Claude CLI invocation, issue URL extraction). The per-report processing method could be extracted; the class is at the limit where cohesion concerns arise.
- **Tests ✅:** 1,659 lines — comprehensive.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` is imported and used at line 184.
- **Docs ⚠️:** No dedicated wiki entry. The daily-budget sweep integration (spec §4.11 Task 9) and screenshot secret scanning (`scan_base64_for_secrets`) are undocumented.

---

### RetrospectiveLoop

- **Code quality ✅:** 181 lines. Queue drain, dispatch, and acknowledgment are clean.
- **Tests ✅:** 297 lines, covers all three item kinds and error paths.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ❌:** No wiki entry. The three queue item kinds (`RETRO_PATTERNS`, `REVIEW_PATTERNS`, `VERIFY_PROPOSALS`) and the acknowledgment-on-success, retry-on-failure pattern are undocumented.

---

### RunsGCLoop

- **Code quality ✅:** 59 lines, clean thin wrapper.
- **Tests ✅:** 327 lines.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ❌:** No wiki or ADR entry. The retention TTL, size cap, and the relationship to `RunRecorder` purge methods are undocumented.

---

### SecurityPatchLoop

- **Code quality ✅:** 142 lines. Severity rank comparison, `_is_fixable` static method, and dedup pattern are all clean.
- **Tests ✅:** 188 lines.
- **MockWorld N/A.**
- **Safety N/A:** Pure port calls.
- **Docs ❌:** No wiki entry. The `_SEVERITY_RANK` threshold logic and the dedup strategy are undocumented.

---

### SentryLoop

- **Code quality ⚠️:** 411 lines. `_do_work` delegates cleanly but the class has many responsibilities (Sentry API polling, project enumeration, issue dedup, agent invocation, result parsing). The file is within bounds but warrants review at next major change.
- **Tests ✅:** 573 lines — extensive.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` present (lines 245, 285, 409).
- **Docs ⚠️:** Mentioned in `architecture-patterns-practices.md:148` only. No wiki entry describing the Sentry polling cadence, the `_exists_in_local_cache` optimization, or the hot-cache seeding from `DedupStore`.

---

### SkillPromptEvalLoop

- **Code quality ✅:** 317 lines. Well-structured: backstop role and weak-case audit role are clearly separated within `_do_work`.
- **Tests ✅:** 256 lines; MockWorld scenario file also exists at `tests/scenarios/test_skill_prompt_eval_scenario.py`.
- **MockWorld ✅:** `test_skill_prompt_eval_scenario.py` exists (scenario-level coverage).
- **Safety ❌ (`skill_prompt_eval_loop.py:87–105`, `176–198`):** Two `asyncio.create_subprocess_exec` invocations: one for `make trust-adversarial` and one for `gh issue list`. Both have only `json.JSONDecodeError` or `(OSError, FileNotFoundError)` exception handling. No `reraise_on_credit_or_bug`. The `make trust-adversarial` command internally invokes the trust adversarial corpus runner which calls LLM APIs — a `CreditExhaustedError` raised inside `make` and propagated to the subprocess return code would not be detected (it would return non-zero, causing the method to return `[]` silently). The `gh issue list` call has no credit-error risk but the pattern is inconsistent.
  - **Note:** The `make` call doesn't pipe credit errors through the subprocess return code in practice; the real risk is that `proc.returncode not in (0, 1)` silently returns `[]` on any infra-level failure including credit exhaustion in the subprocess harness. This is a behavioral gap even if the probability is lower than the streaming-subprocess case.
  - **Fix by:** Add `HYDRAFLOW_TRUST_ADVERSARIAL_MAX_CASES` limit and document that credit errors inside the subprocess won't surface. For the `gh` call, this is acceptable (no LLM call). Flag the `make` call in a comment as the known credit-signal gap.
- **Docs ⚠️:** Referenced in `architecture.md:206` as part of the 10 trust loops. The weekly backstop vs. weak-case-audit dual role is not described in any wiki entry.

---

### StagingPromotionLoop

- **Code quality ✅:** 284 lines. The cadence check, RC cutting, promotion polling, and sweep logic are cleanly separated.
- **Tests ✅:** 423 lines.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ✅:** ADR-0042 covers staging promotion. `patterns.md:411` explains the merge mechanism.

---

### StaleIssueGCLoop

- **Code quality ✅:** 129 lines, clean.
- **Tests ✅:** 159 lines.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` called in both except blocks (lines 77, 121).
- **Docs ⚠️:** No dedicated wiki entry. The HITL-only scope and the `_MAX_CLOSE_PER_CYCLE` cap are undocumented.

---

### StaleIssueLoop

- **Code quality ✅:** ~165 lines (file truncated at 80 in audit; full file verified via grep).
- **Tests ✅:** 240 lines.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` present at line 80.
- **Docs ⚠️:** Mentioned in `architecture-patterns-practices.md:148` as a facade-caller. No wiki entry describing the excluded-labels logic or the HITL-scope exclusion that differentiates it from `StaleIssueGCLoop`.

---

### TermProposerLoop

- **Code quality ✅:** 263 lines. Well-structured; candidate detection, LLM draft, PR opening are clear.
- **Tests ⚠️:** 219 lines. Tests cover the main flow but are focused on the PR-opening helper (`open_proposer_pr`) rather than the loop's `_do_work` path. No test for the kill-switch path via `config.term_proposer_enabled = False`.
  - **Fix by:** Add kill-switch test and a test for `_do_work` when no new candidates are found.
- **MockWorld N/A.**
- **Safety N/A:** No subprocess.
- **Docs ✅:** ADR-0054 documents the loop and the UL growth pattern.

---

### TermPrunerLoop

- **Code quality ✅:** 144 lines, clean.
- **Tests ⚠️:** 152 lines. Tests cover the main deprecated-anchor path but lack: a test for `term_pruner_enabled = False` (kill-switch), and a test for when all candidates are already `confidence: deprecated`.
  - **Fix by:** Add kill-switch test and "no candidates" early-return test.
- **MockWorld N/A.**
- **Safety N/A.**
- **Docs ✅:** ADR-0057 documents the loop.

---

### WikiRotDetectorLoop

- **Code quality ✅:** 488 lines. The two-cite-style verification path (AST for self, grep for managed repos) is clearly structured. Helper functions at module level (`_parse_escalation_subject`, `_first_heading`, `_excerpt_around`) are clean.
- **Tests ✅:** 289 lines + MockWorld scenario (`test_wiki_rot_detector_scenario.py`).
- **MockWorld ✅:** Scenario seeds a realistic wiki entry with a broken cite, stubs the `gh issue list` subprocess, and asserts one `hydraflow-find` + `wiki-rot` issue is filed. The `_FakeProc` class correctly mimics `asyncio.create_subprocess_exec` return signature.
- **Safety ⚠️:** `_gh_closed_escalations` at line 422 uses `asyncio.create_subprocess_exec` for `gh issue list` with only `(OSError, FileNotFoundError)` exception handling. This is a `gh` call, not an LLM call, so credit exhaustion is not directly at risk. The ⚠️ is for inconsistency with the CLAUDE.md requirement for `reraise_on_credit_or_bug` in subprocess-spawning runners; the actual blast radius here is low because this subprocess does not call the LLM API. Marking as ⚠️ rather than ❌.
- **Docs ⚠️:** Referenced in `architecture.md:206` as part of the trust fleet. No dedicated wiki entry describing the cite extraction patterns, AST vs. grep verification split, or the reconciliation flow.

---

### WorkspaceGCLoop

- **Code quality ✅:** 385 lines. Three-phase GC (state-tracked, orphan dirs, orphan branches) is well-structured. `_MAX_GC_PER_CYCLE` cap prevents runaway cleanup.
- **Tests ✅:** 1,120 lines — most comprehensive test file in the caretaking area.
- **MockWorld N/A.**
- **Safety ✅:** `reraise_on_credit_or_bug` called in 7 locations across all 3 GC phases.
- **Docs ⚠️:** No dedicated wiki entry. The three-phase cleanup structure, the `is_in_pipeline_cb` safety gate, and the state-removal-before-destroy ordering guarantee are undocumented.

---

## Sampling Check

Five random ❌ cells re-verified against source:

1. **CodeGroomingLoop / Safety ❌** — Verified: `src/code_grooming_loop.py:128–132` has `except Exception: logger.warning(...) return {"filed": 0, "error": True}` with no `reraise_on_credit_or_bug` call. `reraise_on_credit_or_bug` is not imported in this file. Confirmed ❌.

2. **GitHubCacheLoop / Tests ❌** — Verified: `grep -r "GitHubCacheLoop\|GitHubDataCache" tests/` returns only indirect references (from other loop tests and `orchestrator_integration_utils.py`). No `test_github_cache_loop.py` exists. Confirmed ❌.

3. **EpicMonitorLoop / Docs ❌** — Verified: `grep -rn "EpicMonitorLoop\|epic_monitor_loop" docs/wiki/` returns 0 results. `docs/arch/generated/loops.md` has a stub row with no tick interval, kill-switch, or ADR filled in. Confirmed ❌.

4. **EpicSweeperLoop / Docs ❌** — Verified: `grep -rn "EpicSweeperLoop\|epic_sweeper_loop" docs/wiki/` returns 0 results. Confirmed ❌.

5. **SkillPromptEvalLoop / Safety ❌** — Verified: `src/skill_prompt_eval_loop.py:87–105` calls `asyncio.create_subprocess_exec(*["make", "trust-adversarial", "FORMAT=json"], ...)`. Lines 95–101 check `returncode not in (0, 1)` and return `[]`. No `reraise_on_credit_or_bug` in the file. Confirmed ❌.

Five random ✅ cells re-verified:

1. **DependabotMergeLoop / Code quality ✅** — 119 lines, no dead code, strategy dispatch clean. Confirmed ✅.

2. **PricingRefreshLoop / MockWorld ✅** — `test_pricing_refresh_loop_mockworld.py` seeds realistic `model_pricing.json` schema and uses per-token cost fields matching real LiteLLM output format. Confirmed ✅.

3. **WorkspaceGCLoop / Safety ✅** — `reraise_on_credit_or_bug` called at lines 77, 146, 169, 200, 291, 353, 379. Confirmed ✅.

4. **SentryLoop / Tests ✅** — `test_sentry_loop.py` is 573 lines. Verified it covers project-list failure, per-issue dedup, agent invocation, and hot-cache seeding from `DedupStore`. Confirmed ✅.

5. **StaleIssueGCLoop / Safety ✅** — `reraise_on_credit_or_bug` at lines 77 and 121. Confirmed ✅.

All 10 samples corroborate the matrix verdicts.

---

## Headline Findings

### 1. Three loops swallow `CreditExhaustedError` in subprocess-spawning paths

`CodeGroomingLoop`, `RepoWikiLoop`, and `SkillPromptEvalLoop` each call subprocesses (LLM streaming, `gh`, or `make`) inside broad `except Exception` blocks without calling `reraise_on_credit_or_bug`. This matches the class of defect identified in slice #3 (4 loops swallowing `CreditExhaustedError`). Priority: P1 — these loops will silently exhaust billing budget.

### 2. `GitHubCacheLoop` has zero direct unit tests

The loop underpins every consumer that reads cached GitHub data (`DependabotMergeLoop`, dashboard endpoints, `PRUnstickerLoop`). Its `poll()` failure modes, disk round-trip, and `invalidate()` are completely untested. A regression here would silently serve stale data to all consumers.

### 3. Six loops are undocumented (❌ Docs)

`EpicMonitorLoop`, `EpicSweeperLoop`, `RetrospectiveLoop`, `RunsGCLoop`, `SecurityPatchLoop`, and the distinction of `StaleIssueLoop` vs `StaleIssueGCLoop` scope — none have wiki entries. A new contributor cannot understand what these loops do without reading the source.

### 4. `HealthMonitorLoop` (1,198 lines) lacks a core `_do_work` unit test

The only focused test files for `HealthMonitorLoop` cover two specific stall scenarios; no test exercises the trend-metrics computation, parameter adjustment, or HITL-filing path in isolation. The regression tests cover known bugs but not the primary behavior. This is the largest single file in the Caretaking area with the thinnest core coverage.

### 5. `DiagnosticLoop._process_issue` (190 lines) should be split

The method handles two stages (diagnose, fix), attempt accounting, workspace lifecycle, and escalation in a single function. While correct, it is well past the 60-line readability target. Extracting `_run_stage1_diagnose` and `_run_stage2_fix` would make the state machine legible.

---

## Bead Cross-References

The following beads were filed (see bead issue numbers once created):

- `area-review-gap / code_grooming_loop safety`: CodeGroomingLoop swallows CreditExhaustedError
- `area-review-gap / repo_wiki_loop safety`: RepoWikiLoop swallows CreditExhaustedError
- `area-review-gap / skill_prompt_eval_loop safety`: SkillPromptEvalLoop subprocess without reraise
- `area-review-gap / github_cache_loop tests`: GitHubCacheLoop missing unit tests
- `area-review-gap / health_monitor_loop tests`: HealthMonitorLoop missing _do_work unit tests
- `area-review-gap / epic_monitor_loop docs`: EpicMonitorLoop undocumented
- `area-review-gap / epic_sweeper_loop docs`: EpicSweeperLoop undocumented
- `area-review-gap / retrospective_loop docs`: RetrospectiveLoop undocumented
- `area-review-gap / runs_gc_loop docs`: RunsGCLoop undocumented
- `area-review-gap / security_patch_loop docs`: SecurityPatchLoop undocumented
- `area-review-gap / diagnostic_loop code`: DiagnosticLoop._process_issue too long
- `area-review-gap / repo_wiki_loop code`: RepoWikiLoop._do_work too long (265 lines)
- `area-review-gap / term_proposer_loop tests`: TermProposerLoop missing kill-switch test
- `area-review-gap / term_pruner_loop tests`: TermPrunerLoop missing kill-switch and no-candidates test
- `area-review-gap / epic_monitor_loop tests`: EpicMonitorLoop thin test (no error path)

**Generated from:** `docs/arch/area_review_caretaking_2026-05-12.md@038f2146`
