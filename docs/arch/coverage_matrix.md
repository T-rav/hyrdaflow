# Coverage Matrix Baseline

**Snapshot date:** 2026-05-12
**Audit commit SHA:** `de42e482cfce04eb8a584a2e4ebeb02cb96aa35d`
**Spec:** `docs/superpowers/specs/2026-05-12-coverage-matrix-design.md`
**Automation follow-up bead:** `<paste bead ID after Task 14>`

## Column criteria

(Copy verbatim from the spec, §4. Reproduced here so the matrix is self-contained.)

### Loops table

- **ADR.** `grep -l "LoopName" docs/adr/*.md` returns ≥1 file where the loop is referenced in body prose. Cell shows ADR number + status (Proposed / Accepted / Superseded).
- **Wiki.** `grep -l "LoopName" docs/wiki/*.md` returns ≥1 substantive match (not bare cross-link).
- **Generated.** Loop appears in `docs/arch/generated/loops.md` with non-`—` Tick AND Kill Switch columns.
- **Standard.** Loop bound by a rule in `docs/standards/**/README.md` (roll-up rules count).
- **Unit tests.** `tests/test_<snake_case_loop>*.py` exists with ≥1 test exercising the class directly.
- **MockWorld scenario.** Loop in `tests/scenarios/catalog/loop_registrations.py` AND scenario file invokes it.
- **Sandbox e2e.** Loop exercised in `tests/sandbox_scenarios/scenarios/`.

### Ports table

- **ADR / Wiki / Generated / Standard.** Same predicates with PortName.
- **Fake adapter.** `Fake<PortName>` class under `tests/scenarios/fakes/` implementing every Protocol method (ADR-0047).
- **Cassette tests.** `tests/trust/contracts/cassettes/<port>/` exists with recordings.
- **Contract test.** Test asserts fake satisfies same contract as real adapter (ADR-0047).

### Phases table

- **ADR / Wiki / Standard.** Phase named in substantive prose.
- **Loops driving it.** Hand-mapped against `factory_operation/README.md` and `docs/arch/generated/labels.md`.
- **Escalation path.** One sentence: what event or label transition fires on failure / stall.
- **HITL trigger.** One sentence: condition that escalates to human. Cells reading "human always reviews" are explicit signal for a slice #4 drift bead.

## Cell vocabulary

- ✅ followed by ref (ADR number, wiki path, test path).
- ⚠️ followed by what's missing + `[bd:N]`.
- ❌ followed by `[bd:N]`.
- N/A when column doesn't apply (must be justified inline).

## Aliases

(Populated during extraction. Maps row name to extra grep-matching strings.)

## Excluded refs

(Populated during extraction. Per-row list of files whose mention does not count.)

---

## Section 1: Loops (41 × 7)

| Loop | ADR | Wiki | Generated | Standard | Unit | Scenario | Sandbox |
|---|---|---|---|---|---|---|---|
| `ADRReviewerLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_adr_reviewer_loop.py` | ✅ in catalog | ❌ |
| `AdrTouchpointAuditorLoop` | ✅ [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ | ❌ | ❌ | ✅ `test_adr_touchpoint_auditor_loop.py` | ✅ in catalog | ❌ |
| `AutoAgentPreflightLoop` | ✅ [0050](../adr/0050-auto-agent-hitl-preflight.md) | ✅ `dark-factory.md` | ❌ | ❌ | ✅ `test_auto_agent_preflight_loop.py` | ✅ in catalog | ❌ |
| `CIMonitorLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ | ❌ | ❌ | ✅ `test_ci_monitor_loop.py` | ⚠️ in catalog | ❌ |
| `CodeGroomingLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ✅ `architecture-async-control.md` | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_code_grooming_loop.py` | ✅ in catalog | ❌ |
| `ContractRefreshLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0047](../adr/0047-fake-adapter-contract-testing-cassettes.md) | ❌ | ❌ | ❌ | ✅ `test_contract_refresh_loop.py` | ✅ in catalog | ❌ |
| `CorpusLearningLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ | ❌ | ❌ | ✅ `test_corpus_learning_loop.py` | ✅ in catalog | ❌ |
| `CostBudgetWatcherLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md) | ✅ `architecture.md` | ❌ | ✅ (caretaking/caretaker loop) | ❌ | ⚠️ in catalog | ❌ |
| `DependabotMergeLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md), [0057](../adr/0057-term-pruner-loop.md), [0058](../adr/0058-edge-proposer-loop.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_dependabot_merge_loop.py` | ⚠️ in catalog | ✅ `s09_dependabot_auto_merge.py` |
| `DiagnosticLoop` | ✅ [0050](../adr/0050-auto-agent-hitl-preflight.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_diagnostic_loop.py` | ✅ in catalog | ❌ |
| `DiagramLoop` | ✅ [0001](../adr/0001-five-concurrent-async-loops.md) | ❌ | ❌ | ❌ | ✅ `test_diagram_loop.py` | ✅ in catalog | ❌ |
| `EdgeProposerLoop` | ✅ [0058](../adr/0058-edge-proposer-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md), [0062](../adr/0062-entry-evidence-loop.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_edge_proposer_loop.py` | ❌ | ❌ |
| `EntryEvidenceLoop` | ✅ [0062](../adr/0062-entry-evidence-loop.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_entry_evidence_loop.py` | ⚠️  | ❌ |
| `EpicMonitorLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_epic_monitor_loop.py` | ✅ in catalog | ❌ |
| `EpicSweeperLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_epic_sweeper_loop.py` | ⚠️ in catalog | ❌ |
| `FakeCoverageAuditorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ | ❌ | ❌ | ✅ `test_fake_coverage_auditor_loop.py` | ✅ in catalog | ❌ |
| `FlakeTrackerLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ | ❌ | ❌ | ✅ `test_flake_tracker_loop.py` | ✅ in catalog | ❌ |
| `GitHubCacheLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ❌ | ✅ in catalog | ❌ |
| `HealthMonitorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0046](../adr/0046-meta-observability-bounded-recursion.md) | ✅ `testing.md` | ❌ | ✅ (caretaking/caretaker loop) | ❌ | ⚠️ in catalog | ❌ |
| `MergeStateWatcherLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ❌ | ⚠️ in catalog | ❌ |
| `PRUnstickerLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_pr_unsticker_loop.py` | ⚠️ in catalog | ✅ `s08_pr_unsticker_revives_stuck_pr.py` |
| `PricingRefreshLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_pricing_refresh_loop_scenario.py` | ✅ in catalog | ❌ |
| `PrinciplesAuditLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ✅ `dark-factory.md` | ❌ | ❌ | ✅ `test_principles_audit_loop.py` | ✅ in catalog | ❌ |
| `RCBudgetLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ | ❌ | ❌ | ✅ `test_rc_budget_loop.py` | ✅ in catalog | ❌ |
| `RepoWikiLoop` | ✅ [0032](../adr/0032-per-repo-wiki-knowledge-base.md), [0053](../adr/0053-ubiquitous-language-as-living-artifact.md), [0061](../adr/0061-atlas-entries-as-evidence.md) | ✅ `dark-factory.md` | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_repo_wiki_loop.py` | ✅ in catalog | ❌ |
| `ReportIssueLoop` | ✅ [0013](../adr/0013-screenshot-capture-pipeline.md), [0018](../adr/0018-screenshot-capture-pipeline.md), [0028](../adr/0028-event-driven-report-pipeline.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_report_issue_loop.py` | ✅ in catalog | ❌ |
| `RetrospectiveLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_retrospective_loop.py` | ⚠️ in catalog | ❌ |
| `RunsGCLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_runs_gc_loop.py` | ✅ in catalog | ❌ |
| `SandboxFailureFixerLoop` | ✅ [0052](../adr/0052-sandbox-tier-scenarios.md) | ✅ `dark-factory.md` | ❌ | ❌ | ✅ `test_sandbox_failure_fixer_loop.py` | ⚠️ in catalog | ❌ |
| `SecurityPatchLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_security_patch_loop.py` | ✅ in catalog | ❌ |
| `SentryLoop` | ✅ [0055](../adr/0055-otel-honeycomb-instrumentation.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_sentry_loop.py` | ✅ in catalog | ❌ |
| `SkillPromptEvalLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_skill_prompt_eval_loop.py` | ✅ in catalog | ❌ |
| `StagingBisectLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0048](../adr/0048-auto-revert-on-rc-red.md), [0049](../adr/0049-trust-loop-kill-switch-convention.md) | ✅ `architecture.md` | ❌ | ❌ | ✅ `test_staging_bisect_loop.py` | ✅ in catalog | ❌ |
| `StagingPromotionLoop` | ✅ [0042](../adr/0042-two-tier-branch-release-promotion.md) | ✅ `patterns.md` | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_staging_promotion_loop.py` | ⚠️  | ✅ `s13_rc_rebase_recovery.py` |
| `StaleIssueGCLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_stale_issue_gc_loop.py` | ✅ in catalog | ❌ |
| `StaleIssueLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_stale_issue_loop.py` | ✅ in catalog | ❌ |
| `TermProposerLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md), [0057](../adr/0057-term-pruner-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md) | ✅ `bot-pr-port.md`, `task.md` | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_term_proposer_loop.py` | ❌ | ❌ |
| `TermPrunerLoop` | ✅ [0057](../adr/0057-term-pruner-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md), [0062](../adr/0062-entry-evidence-loop.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_term_pruner_loop.py` | ❌ | ❌ |
| `TrustFleetSanityLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0046](../adr/0046-meta-observability-bounded-recursion.md), [0049](../adr/0049-trust-loop-kill-switch-convention.md) | ✅ `testing.md` | ❌ | ❌ | ✅ `test_trust_fleet_sanity_loop.py` | ✅ in catalog | ❌ |
| `WikiRotDetectorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_wiki_rot_detector_loop.py` | ✅ in catalog | ❌ |
| `WorkspaceGCLoop` | ❌ | ❌ | ❌ | ✅ (caretaking/caretaker loop) | ✅ `test_workspace_gc_loop.py` | ⚠️ in catalog | ✅ `s07_workspace_gc_reaps_dead_worktree.py` |

## Section 2: Ports (9 × 7)

| Port | ADR | Wiki | Generated | Standard | Fake | Cassette | Contract |
|---|---|---|---|---|---|---|---|
<!-- rows populated in Task 10 -->

## Section 3: Factory phases (8 × 6)

| Phase | ADR | Wiki | Standard | Loops driving it | Escalation path | HITL trigger |
|---|---|---|---|---|---|---|
<!-- rows populated in Task 11 -->

## Sampling check

(Populated in Task 13.)

**Early extractor sample (post-Task 7, after snake() acronym-bug fix):** WorkspaceGCLoop, CostBudgetWatcherLoop, AdrTouchpointAuditorLoop. Result: 3/3 agree with manual grep. Run on commit `73cf6f28dcf6070a2f7fdba27eefe5075a057e3a`.

## Counts reconciliation

(Populated in Task 13.)
