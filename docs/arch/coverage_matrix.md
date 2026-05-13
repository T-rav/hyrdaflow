# Coverage Matrix Baseline

**Snapshot date:** 2026-05-12
**Audit commit SHA:** `de42e482cfce04eb8a584a2e4ebeb02cb96aa35d`
**Spec:** `docs/superpowers/specs/2026-05-12-coverage-matrix-design.md`
**Automation follow-up bead:** `bd:advisor-bpl`

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

(Currently none. Add as <RowName>: ["string1", "string2"] when an extractor false-negative is fixed by adding a grep variant.)

## Excluded refs

The following files contain only roll-call mentions and do NOT count as substantive coverage for any row that appears only there:

- `docs/adr/0044-hydraflow-principles.md` — principles audit lists every loop.
- `docs/adr/0049-trust-loop-kill-switch-convention.md` — kill-switch convention lists every loop the convention applies to.
- `docs/wiki/index.md` — wiki index, lists entries by name without describing them.
- `docs/wiki/index.json` — machine wiki index.

Per-row overrides (loops where the only match was in one of the above and the cell was flipped to ⚠️):

None — every loop has substantive (non-roll-call) coverage when an ADR mention exists.

---

## Section 1: Loops (41 × 7)

| Loop | ADR | Wiki | Generated | Standard | Unit | Scenario | Sandbox |
|---|---|---|---|---|---|---|---|
| `ADRReviewerLoop` | ❌ [bd:advisor-pg6] | ❌ [bd:advisor-4mj] | ❌ [bd:advisor-7yr] | ✅ (caretaking/caretaker loop) | ✅ `test_adr_reviewer_loop.py` | ✅ in catalog | ❌ [bd:advisor-dqz] |
| `AdrTouchpointAuditorLoop` | ✅ [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ [bd:advisor-4bd] | ❌ [bd:advisor-xll] | ❌ [bd:advisor-rd8] | ✅ `test_adr_touchpoint_auditor_loop.py` | ✅ in catalog | ❌ [bd:advisor-vch] |
| `AutoAgentPreflightLoop` | ✅ [0050](../adr/0050-auto-agent-hitl-preflight.md) | ✅ `dark-factory.md` | ❌ [bd:advisor-563] | ❌ [bd:advisor-drv] | ✅ `test_auto_agent_preflight_loop.py` | ✅ in catalog | ❌ [bd:advisor-pn6] |
| `CIMonitorLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ [bd:advisor-yr9] | ❌ [bd:advisor-9hj] | ❌ [bd:advisor-uu5] | ✅ `test_ci_monitor_loop.py` | ⚠️ in catalog [bd:advisor-g95] | ❌ [bd:advisor-3e1] |
| `CodeGroomingLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ✅ `architecture-async-control.md` | ❌ [bd:advisor-6v9] | ✅ (caretaking/caretaker loop) | ✅ `test_code_grooming_loop.py` | ✅ in catalog | ❌ [bd:advisor-tmv] |
| `ContractRefreshLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0047](../adr/0047-fake-adapter-contract-testing-cassettes.md) | ❌ [bd:advisor-uxt] | ❌ [bd:advisor-6t8] | ❌ [bd:advisor-vad] | ✅ `test_contract_refresh_loop.py` | ✅ in catalog | ❌ [bd:advisor-nwl] |
| `CorpusLearningLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ [bd:advisor-t28] | ❌ [bd:advisor-9ph] | ❌ [bd:advisor-7jv] | ✅ `test_corpus_learning_loop.py` | ✅ in catalog | ❌ [bd:advisor-2ad] |
| `CostBudgetWatcherLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md) | ✅ `architecture.md` | ❌ [bd:advisor-2ke] | ✅ (caretaking/caretaker loop) | ❌ [bd:advisor-a03] | ⚠️ in catalog [bd:advisor-ga3] | ❌ [bd:advisor-hn9] |
| `DependabotMergeLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md), [0057](../adr/0057-term-pruner-loop.md), [0058](../adr/0058-edge-proposer-loop.md) | ❌ [bd:advisor-m1e] | ❌ [bd:advisor-n96] | ✅ (caretaking/caretaker loop) | ✅ `test_dependabot_merge_loop.py` | ⚠️ in catalog [bd:advisor-lq2] | ✅ `s09_dependabot_auto_merge.py` |
| `DiagnosticLoop` | ✅ [0050](../adr/0050-auto-agent-hitl-preflight.md) | ❌ [bd:advisor-inl] | ❌ [bd:advisor-4k2] | ✅ (caretaking/caretaker loop) | ✅ `test_diagnostic_loop.py` | ✅ in catalog | ❌ [bd:advisor-tjt] |
| `DiagramLoop` | ✅ [0001](../adr/0001-five-concurrent-async-loops.md) | ❌ [bd:advisor-0nr] | ❌ [bd:advisor-db5] | ❌ [bd:advisor-6ln] | ✅ `test_diagram_loop.py` | ✅ in catalog | ❌ [bd:advisor-ytt] |
| `EdgeProposerLoop` | ✅ [0058](../adr/0058-edge-proposer-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md), [0062](../adr/0062-entry-evidence-loop.md) | ❌ [bd:advisor-u3m] | ❌ [bd:advisor-9i3] | ✅ (caretaking/caretaker loop) | ✅ `test_edge_proposer_loop.py` | ❌ [bd:advisor-2kq] | ❌ [bd:advisor-vwh] |
| `EntryEvidenceLoop` | ✅ [0062](../adr/0062-entry-evidence-loop.md) | ❌ [bd:advisor-byh] | ❌ [bd:advisor-6ru] | ✅ (caretaking/caretaker loop) | ✅ `test_entry_evidence_loop.py` | ⚠️ [bd:advisor-4dj] | ❌ [bd:advisor-7m5] |
| `EpicMonitorLoop` | ❌ [bd:advisor-o9d] | ❌ [bd:advisor-c88] | ❌ [bd:advisor-goo] | ✅ (caretaking/caretaker loop) | ✅ `test_epic_monitor_loop.py` | ✅ in catalog | ❌ [bd:advisor-lgd] |
| `EpicSweeperLoop` | ❌ [bd:advisor-0zt] | ❌ [bd:advisor-j43] | ❌ [bd:advisor-8sg] | ✅ (caretaking/caretaker loop) | ✅ `test_epic_sweeper_loop.py` | ⚠️ in catalog [bd:advisor-4m0] | ❌ [bd:advisor-538] |
| `FakeCoverageAuditorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ [bd:advisor-t3h] | ❌ [bd:advisor-aqt] | ❌ [bd:advisor-15g] | ✅ `test_fake_coverage_auditor_loop.py` | ✅ in catalog | ❌ [bd:advisor-ln3] |
| `FlakeTrackerLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ [bd:advisor-ifr] | ❌ [bd:advisor-c6x] | ❌ [bd:advisor-7pg] | ✅ `test_flake_tracker_loop.py` | ✅ in catalog | ❌ [bd:advisor-r8i] |
| `GitHubCacheLoop` | ❌ [bd:advisor-k31] | ❌ [bd:advisor-2k3] | ❌ [bd:advisor-0k3] | ✅ (caretaking/caretaker loop) | ❌ [bd:advisor-87o] | ✅ in catalog | ❌ [bd:advisor-3y4] |
| `HealthMonitorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0046](../adr/0046-meta-observability-bounded-recursion.md) | ✅ `testing.md` | ❌ [bd:advisor-dg3] | ✅ (caretaking/caretaker loop) | ❌ [bd:advisor-2pc] | ⚠️ in catalog [bd:advisor-ddg] | ❌ [bd:advisor-38v] |
| `MergeStateWatcherLoop` | ❌ [bd:advisor-f5i] | ❌ [bd:advisor-c82] | ❌ [bd:advisor-6wp] | ✅ (caretaking/caretaker loop) | ❌ [bd:advisor-2mf] | ⚠️ in catalog [bd:advisor-308] | ❌ [bd:advisor-rxi] |
| `PRUnstickerLoop` | ❌ [bd:advisor-kqr] | ❌ [bd:advisor-9ne] | ❌ [bd:advisor-4ic] | ✅ (caretaking/caretaker loop) | ✅ `test_pr_unsticker_loop.py` | ⚠️ in catalog [bd:advisor-mfs] | ✅ `s08_pr_unsticker_revives_stuck_pr.py` |
| `PricingRefreshLoop` | ❌ [bd:advisor-vcn] | ❌ [bd:advisor-duo] | ❌ [bd:advisor-2xo] | ✅ (caretaking/caretaker loop) | ✅ `test_pricing_refresh_loop_scenario.py` | ✅ in catalog | ❌ [bd:advisor-nv4] |
| `PrinciplesAuditLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ✅ `dark-factory.md` | ❌ [bd:advisor-od5] | ❌ [bd:advisor-4kb] | ✅ `test_principles_audit_loop.py` | ✅ in catalog | ❌ [bd:advisor-1rm] |
| `RCBudgetLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ [bd:advisor-aph] | ❌ [bd:advisor-5zb] | ❌ [bd:advisor-5j0] | ✅ `test_rc_budget_loop.py` | ✅ in catalog | ❌ [bd:advisor-x0v] |
| `RepoWikiLoop` | ✅ [0032](../adr/0032-per-repo-wiki-knowledge-base.md), [0053](../adr/0053-ubiquitous-language-as-living-artifact.md), [0061](../adr/0061-atlas-entries-as-evidence.md) | ✅ `dark-factory.md` | ❌ [bd:advisor-smb] | ✅ (caretaking/caretaker loop) | ✅ `test_repo_wiki_loop.py` | ✅ in catalog | ❌ [bd:advisor-qzq] |
| `ReportIssueLoop` | ✅ [0013](../adr/0013-screenshot-capture-pipeline.md), [0018](../adr/0018-screenshot-capture-pipeline.md), [0028](../adr/0028-event-driven-report-pipeline.md) | ❌ [bd:advisor-uo8] | ❌ [bd:advisor-7oe] | ✅ (caretaking/caretaker loop) | ✅ `test_report_issue_loop.py` | ✅ in catalog | ❌ [bd:advisor-ttm] |
| `RetrospectiveLoop` | ❌ [bd:advisor-bub] | ❌ [bd:advisor-2lq] | ❌ [bd:advisor-y5f] | ✅ (caretaking/caretaker loop) | ✅ `test_retrospective_loop.py` | ⚠️ in catalog [bd:advisor-dca] | ❌ [bd:advisor-t2y] |
| `RunsGCLoop` | ❌ [bd:advisor-09l] | ❌ [bd:advisor-k6i] | ❌ [bd:advisor-fnq] | ✅ (caretaking/caretaker loop) | ✅ `test_runs_gc_loop.py` | ✅ in catalog | ❌ [bd:advisor-7w0] |
| `SandboxFailureFixerLoop` | ✅ [0052](../adr/0052-sandbox-tier-scenarios.md) | ✅ `dark-factory.md` | ❌ [bd:advisor-hcy] | ❌ [bd:advisor-e7a] | ✅ `test_sandbox_failure_fixer_loop.py` | ⚠️ in catalog [bd:advisor-rqj] | ❌ [bd:advisor-z49] |
| `SecurityPatchLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ [bd:advisor-adw] | ❌ [bd:advisor-55q] | ✅ (caretaking/caretaker loop) | ✅ `test_security_patch_loop.py` | ✅ in catalog | ❌ [bd:advisor-ym6] |
| `SentryLoop` | ✅ [0055](../adr/0055-otel-honeycomb-instrumentation.md) | ❌ [bd:advisor-efb] | ❌ [bd:advisor-a5l] | ✅ (caretaking/caretaker loop) | ✅ `test_sentry_loop.py` | ✅ in catalog | ❌ [bd:advisor-ko9] |
| `SkillPromptEvalLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md) | ❌ [bd:advisor-1ena] | ❌ [bd:advisor-w4cw] | ✅ (caretaking/caretaker loop) | ✅ `test_skill_prompt_eval_loop.py` | ✅ in catalog | ❌ [bd:advisor-si37] |
| `StagingBisectLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0048](../adr/0048-auto-revert-on-rc-red.md), [0049](../adr/0049-trust-loop-kill-switch-convention.md) | ✅ `architecture.md` | ❌ [bd:advisor-bgvi] | ❌ [bd:advisor-4p5b] | ✅ `test_staging_bisect_loop.py` | ✅ in catalog | ❌ [bd:advisor-bsn2] |
| `StagingPromotionLoop` | ✅ [0042](../adr/0042-two-tier-branch-release-promotion.md) | ✅ `patterns.md` | ❌ [bd:advisor-m0u9] | ✅ (caretaking/caretaker loop) | ✅ `test_staging_promotion_loop.py` | ⚠️ [bd:advisor-tmo3] | ✅ `s13_rc_rebase_recovery.py` |
| `StaleIssueGCLoop` | ✅ [0029](../adr/0029-caretaker-loop-pattern.md) | ❌ [bd:advisor-gvs9] | ❌ [bd:advisor-ybhd] | ✅ (caretaking/caretaker loop) | ✅ `test_stale_issue_gc_loop.py` | ✅ in catalog | ❌ [bd:advisor-au05] |
| `StaleIssueLoop` | ❌ [bd:advisor-n6cw] | ❌ [bd:advisor-medh] | ❌ [bd:advisor-02ib] | ✅ (caretaking/caretaker loop) | ✅ `test_stale_issue_loop.py` | ✅ in catalog | ❌ [bd:advisor-ry6s] |
| `TermProposerLoop` | ✅ [0054](../adr/0054-term-auto-proposer-loop.md), [0057](../adr/0057-term-pruner-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md) | ✅ `bot-pr-port.md`, `task.md` | ❌ [bd:advisor-pdxv] | ✅ (caretaking/caretaker loop) | ✅ `test_term_proposer_loop.py` | ❌ [bd:advisor-y6vf] | ❌ [bd:advisor-7qvd] |
| `TermPrunerLoop` | ✅ [0057](../adr/0057-term-pruner-loop.md), [0060](../adr/0060-atlas-graph-view-and-provenance.md), [0062](../adr/0062-entry-evidence-loop.md) | ❌ [bd:advisor-rm7j] | ❌ [bd:advisor-7oh9] | ✅ (caretaking/caretaker loop) | ✅ `test_term_pruner_loop.py` | ❌ [bd:advisor-y4e7] | ❌ [bd:advisor-eg1i] |
| `TrustFleetSanityLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0046](../adr/0046-meta-observability-bounded-recursion.md), [0049](../adr/0049-trust-loop-kill-switch-convention.md) | ✅ `testing.md` | ❌ [bd:advisor-6s98] | ❌ [bd:advisor-fapf] | ✅ `test_trust_fleet_sanity_loop.py` | ✅ in catalog | ❌ [bd:advisor-5w20] |
| `WikiRotDetectorLoop` | ✅ [0045](../adr/0045-trust-architecture-hardening.md), [0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) | ❌ [bd:advisor-ujxu] | ❌ [bd:advisor-bzce] | ✅ (caretaking/caretaker loop) | ✅ `test_wiki_rot_detector_loop.py` | ✅ in catalog | ❌ [bd:advisor-5lgn] |
| `WorkspaceGCLoop` | ❌ [bd:advisor-i00b] | ❌ [bd:advisor-w1cn] | ❌ [bd:advisor-91jz] | ✅ (caretaking/caretaker loop) | ✅ `test_workspace_gc_loop.py` | ⚠️ in catalog [bd:advisor-f1wy] | ✅ `s07_workspace_gc_reaps_dead_worktree.py` |

## Section 2: Ports (9 × 7)

Cassette and Contract columns are N/A for all ports because ADR-0047 defines contracts per domain adapter (github / git / docker / llm), not per Port. A port may transitively benefit from cassette/contract coverage via its adapter.

| Port | ADR | Wiki | Generated | Standard | Fake | Cassette | Contract |
|---|---|---|---|---|---|---|---|
| `AgentPort` | ❌ [bd:advisor-79o5] | ✅ `architecture-layers.md` | ✅ ports.md | ❌ [bd:advisor-ylkx] | ❌ [bd:advisor-ayw5] | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `BotPRPort` | ❌ [bd:advisor-grww] | ✅ `bot-pr-port.md` | ✅ ports.md | ❌ [bd:advisor-ysso] | ❌ [bd:advisor-25fr] | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `IssueFetcherPort` | ❌ [bd:advisor-8q9k] | ❌ [bd:advisor-0bhv] | ✅ ports.md | ❌ [bd:advisor-hngi] | ✅ `FakeIssueFetcher` | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `IssueStorePort` | ✅ 0041 | ✅ `architecture-layers.md` | ✅ ports.md | ❌ [bd:advisor-oi2w] | ✅ `FakeIssueStore` | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `ObservabilityPort` | ⚠️ [bd:advisor-yjwy] | ❌ [bd:advisor-wp13] | ✅ ports.md | ❌ [bd:advisor-ocuo] | ❌ [bd:advisor-ddje] | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `PRPort` | ✅ 0052 | ✅ `architecture-layers.md` | ✅ ports.md | ✅ `README.md` | ✅ `FakePR` | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `ReviewInsightStorePort` | ❌ [bd:advisor-kapn] | ❌ [bd:advisor-hqck] | ✅ ports.md | ❌ [bd:advisor-3suf] | ❌ [bd:advisor-luab] | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `RouteBackCounterPort` | ❌ [bd:advisor-kaur] | ❌ [bd:advisor-zdw4] | ✅ ports.md | ❌ [bd:advisor-t2c5] | ❌ [bd:advisor-o0av] | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |
| `WorkspacePort` | ✅ 0003, 0050 | ✅ `workspace-port.md` | ✅ ports.md | ❌ [bd:advisor-4e5e] | ✅ `FakeWorkspace` | N/A (per-adapter, see ADR-0047) | N/A (per-adapter, see ADR-0047) |

## Section 3: Factory phases (8 × 6)

| Phase | ADR | Wiki | Standard | Loops driving it | Escalation path | HITL trigger |
|---|---|---|---|---|---|---|
| `triage` | ✅ [ADR-0002](../adr/0002-labels-as-state-machine.md) (Accepted), [ADR-0001](../adr/0001-five-concurrent-async-loops.md) (Accepted) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `TriagePhase` (orchestrator `_triage_loop`) with `EpicMonitorLoop` monitoring epic health and `StaleIssueLoop` sweeping unrouted issues | triage runner returns a routing outcome; invalid/incomplete issues receive a `parked` label transition with a comment; failed classification left in `find_label` queue for retry | issue parked (`hydraflow-parked`) when triage runner returns `needs_info`; HITL not directly triggered by triage — parked issues await human clarification comment |
| `discover` | ✅ [ADR-0031](../adr/0031-product-track-architecture.md) (Proposed) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `DiscoverPhase` (orchestrator `_discover_loop`); `DiscoverRunner` with `discover-completeness` evaluator (ADR-0045 §4.10) | runner posts research brief and transitions issue to `hydraflow-shape`; evaluator-level failure escalates via `hitl-escalation` through `DiscoverRunner.bind_escalation_deps` | research brief fails coherence evaluation after retry → `hitl-escalation` label applied, then `AutoAgentPreflightLoop` attempts autonomous recovery before issuing `human-required` |
| `shape` | ✅ [ADR-0031](../adr/0031-product-track-architecture.md) (Proposed) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `ShapePhase` (orchestrator `_shape_loop`); `ShapeRunner` with `shape-coherence` evaluator (ADR-0045 §4.10); `StaleIssueLoop` sweeps timed-out shape conversations | conversation times out after `shape_timeout_minutes` (default 60); expert council splits after 2 rounds → escalated to human via `hitl-escalation` label | `shape_timeout_minutes` exceeded with no human direction selection, or expert council remains split after 2 rounds → `hitl-escalation` + `AutoAgentPreflightLoop` pre-flight before `human-required` |
| `plan` | ✅ [ADR-0001](../adr/0001-five-concurrent-async-loops.md) (Accepted), [ADR-0002](../adr/0002-labels-as-state-machine.md) (Accepted) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `PlanPhase` (orchestrator `_plan_loop`) with `PlannerRunner`; `ResearchRunner` for sub-issue discovery; `PlanReviewer` for validation | plan fails `PlanReviewer` validation after retry → `PipelineEscalator` applies `hitl-escalation` label and posts structured failure comment | plan validation fails twice consecutively, or epic-child evidence validation fails → `hitl-escalation` applied, `AutoAgentPreflightLoop` attempts recovery, escalates to `human-required` if 3 attempts exhausted |
| `implement` | ✅ [ADR-0001](../adr/0001-five-concurrent-async-loops.md) (Accepted), [ADR-0024](../adr/0024-implementation-retry-recovery-architecture.md) (Accepted) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `ImplementPhase` (orchestrator `_implement_loop`); `SandboxFailureFixerLoop` on sandbox red; `CIMonitorLoop` watching CI failures | agent exhausts attempt cap (`max_workers` per issue) → `PipelineEscalator` fires; branch with zero diff from main escalates immediately via `_escalate_no_changes_to_hitl` | attempt cap reached or zero-diff branch detected → `hitl-escalation` label; `SandboxFailureFixerLoop` gets up to 3 auto-fix attempts before escalating to sandbox HITL queue |
| `review` | ✅ [ADR-0001](../adr/0001-five-concurrent-async-loops.md) (Accepted), [ADR-0002](../adr/0002-labels-as-state-machine.md) (Accepted) | ✅ `architecture-async-control.md` | ✅ `factory_operation/README.md` | `ReviewPhase` (orchestrator `_review_loop`) with `Reviewer`; `CIMonitorLoop` watching CI; `MergeStateWatcherLoop`; `PRUnstickerLoop` for stuck PRs; `SandboxFailureFixerLoop` on sandbox-tier failures | CI failure after `ci_fix_attempts` retries → `_escalate_ci_failure` posts structured comment and applies `hitl-escalation`; merge conflicts or visual-validation failures also escalate | persistent CI red, merge conflict with main, visual validation failure, or baseline-approval required → `hitl-escalation` applied, `AutoAgentPreflightLoop` pre-flights before `human-required` |
| `HITL` | ✅ [ADR-0050](../adr/0050-auto-agent-hitl-preflight.md) (Accepted), [ADR-0001](../adr/0001-five-concurrent-async-loops.md) (Accepted) | ✅ `dark-factory.md` | ✅ `factory_operation/README.md` | `AutoAgentPreflightLoop` intercepts every `hitl-escalation` issue before human sees it (ADR-0050); `HITLController` manages the human-facing queue; deny-listed sub-labels (`principles-stuck`, `cultural-check`) bypass preflight | `AutoAgentPreflightLoop` runs up to 3 attempts; on success removes `hitl-escalation`; on failure applies `human-required` + structured diagnosis comment | after 3 autonomous pre-flight attempts fail, `human-required` label applied; humans exclusively monitor `human-required` — not `hitl-escalation` directly |
| `merge` | ✅ [ADR-0042](../adr/0042-two-tier-branch-release-promotion.md) (Accepted), [ADR-0048](../adr/0048-auto-revert-on-rc-red.md) (Accepted) | ✅ `dark-factory.md` | ✅ `factory_operation/README.md` | `StagingPromotionLoop` cuts RC snapshots every `rc_cadence_hours` and merges on green; `MergeStateWatcherLoop` watches PR merge state; `StagingBisectLoop` auto-bisects RC red and opens revert PRs (ADR-0042, ADR-0045) | RC promotion PR fails CI → `StagingBisectLoop` attributes culprit and opens auto-revert PR; unresolvable RC failure files `hydraflow-find` issue for next cycle | RC red that `StagingBisectLoop` cannot attribute after bisect → `hitl-escalation` filed; otherwise merge is fully automated with no human gate (ADR-0042 §"Human approval gate" rejected) |

## Sampling check

**Sampling check (post-D8):** Random sample of 5 ✅ cells and 5 ❌ cells across all three sections (seeded `random.seed(2026)`).

- Sample:
  - (`OK`, `` `DiagnosticLoop` ``, col 1 ADR, `✅ [0050](../adr/0050-auto-agent-hitl-preflight.md)`)
  - (`OK`, `` `ReportIssueLoop` ``, col 6 Scenario, `✅ in catalog`)
  - (`OK`, `` `TrustFleetSanityLoop` ``, col 6 Scenario, `✅ in catalog`)
  - (`OK`, `` `WikiRotDetectorLoop` ``, col 5 Unit, `✅ test_wiki_rot_detector_loop.py`)
  - (`OK`, `` `DependabotMergeLoop` ``, col 1 ADR, `✅ [0054](../adr/0054-term-auto-proposer-loop.md), [0057](../adr/0057-term-pruner-loop.md), [0058](../adr/0058-edge-proposer-loop.md)`)
  - (`GAP`, `` `FlakeTrackerLoop` ``, col 3 Generated, `❌`)
  - (`GAP`, `` `ReviewInsightStorePort` ``, col 2 Wiki, `❌`)
  - (`GAP`, `` `RouteBackCounterPort` ``, col 5 Fake adapter, `❌`)
  - (`GAP`, `` `BotPRPort` ``, col 1 ADR, `❌`)
  - (`GAP`, `` `SentryLoop` ``, col 3 Generated, `❌`)
- Result: 10/10 agree with manual verification.
- Disagreements: none

If N < 9, the extractor logic was patched and the affected section was re-run before this entry was recorded.

**Early extractor sample (post-Task 7, after snake() acronym-bug fix):** WorkspaceGCLoop, CostBudgetWatcherLoop, AdrTouchpointAuditorLoop. Result: 3/3 agree with manual grep. Run on commit `73cf6f28dcf6070a2f7fdba27eefe5075a057e3a`.

## Counts reconciliation

- Loops: 41 rows (matches `docs/arch/generated/loops.md`).
- Ports: 9 rows (matches `docs/arch/generated/ports.md`).
- Phases: 8 rows (matches `docs/standards/factory_operation/README.md`).
- Cell totals: 41 × 7 + 9 × 7 + 8 × 6 = 398.
- ✅ / ⚠️ / ❌ / N/A breakdown: `{'✅': 182, '⚠️': 13, '❌': 161, 'N/A': 18}` sum=374 (symbol-bearing cells only; the remaining 24 cells are prose descriptions in the Phases table's "Loops driving it", "Escalation path", and "HITL trigger" columns, which do not carry ✅/❌ vocabulary).
