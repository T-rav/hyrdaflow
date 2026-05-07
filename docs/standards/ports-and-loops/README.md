# HydraFlow Standard — Ports and Loops

Every hexagonal port and every background loop in HydraFlow follows a
shared structural contract. This document defines that contract so that
new ports and loops are consistent, testable, and observable from day
one — without requiring a reviewer to catch missing pieces.

## Ports

A **port** is a `@runtime_checkable` `Protocol` in `src/ports.py` that
abstracts an I/O boundary. Adapters implement ports; phases and loops
depend on ports, not adapters.

### Per-port requirements

| Requirement | Where | Detail |
|---|---|---|
| **Protocol definition** | `src/ports.py` | `@runtime_checkable` `Protocol`; pure interface, no state. |
| **Production adapter** | `src/<adapter>.py` | Concrete implementation; wired in the service registry. |
| **Fake adapter** | `src/mockworld/fakes/fake_<name>.py` | `Fake<Name>` class used in MockWorld scenarios and unit tests. Must satisfy the Protocol structurally. |
| **Wiki term entry** | `docs/wiki/terms/<kebab-name>.md` | YAML frontmatter + Definition + Invariants. UL lint must pass. |
| **ADR** | `docs/adr/XXXX-<kebab-name>.md` | Documents the decision to introduce the port and its behavioral contract. |
| **Standard entry** | This document, `§ Per-port registry` | One-line row in the table below. |

### Per-port registry

| Port | ADR | Fake | Wiki |
|---|---|---|---|
| `AgentPort` | 0066 (TBD) | `FakeAgent` | agent-port (TBD) |
| `BotPRPort` | 0068 (TBD) | `FakeBotPR` | [bot-pr-port.md](../../wiki/terms/bot-pr-port.md) |
| `IssueFetcherPort` | 0067 (TBD) | `FakeIssueFetcher` | issue-fetcher-port (TBD) |
| `IssueStorePort` | [0041](../../adr/0041-github-source-of-truth-cache-as-sidecar.md) | `FakeIssueStore` | [issue-store-port.md](../../wiki/terms/issue-store-port.md) |
| `ObservabilityPort` | [0055](../../adr/0055-otel-honeycomb-instrumentation.md) | `FakeSentry` | observability-port (TBD) |
| `PRPort` | [0045](../../adr/0045-trust-architecture-hardening.md) | `FakePR` | [pr-port.md](../../wiki/terms/pr-port.md) |
| `ReviewInsightStorePort` | 0070 (TBD) | `FakeReviewInsightStore` | review-insight-store-port (TBD) |
| `RouteBackCounterPort` | 0071 (TBD) | `FakeRouteBackCounter` | route-back-counter-port (TBD) |
| `WorkspacePort` | [0003](../../adr/0003-git-worktrees-for-isolation.md) | `FakeWorkspace` | workspace-port (TBD) |

## Loops

A **loop** is a `BaseBackgroundLoop` subclass that runs on a fixed interval
inside the factory. Loops are the dark factory's autonomous workers —
each is responsible for one caretaking concern.

### Per-loop requirements

| Requirement | Where | Detail |
|---|---|---|
| **Kill-switch** | `_do_work` method | First check: `if not self._enabled_cb(self._worker_name): return {"status": "disabled"}`. ADR-0049 mandates this on every loop. |
| **Config gate** | `_do_work` method | Second check: `if not self._config.<loop>_loop_enabled: return {"status": "config_disabled"}` for static-config-gated loops. |
| **Unit tests** | `tests/test_<loop>.py` | Full coverage including kill-switch path. |
| **MockWorld scenario** | `tests/scenarios/test_<loop>_scenario.py` | Pattern A (catalog) or Pattern B (direct) — see `docs/standards/testing/`. |
| **Wiki term entry** | `docs/wiki/terms/<kebab-loop>.md` | YAML frontmatter + Definition + Invariants. |
| **ADR** | `docs/adr/XXXX-<kebab-loop>.md` | Documents the decision to introduce the loop. |
| **Standard entry** | This document, `§ Per-loop registry` | One-line row in the table below. |

### Per-loop registry

Rows below capture the canonical standard status. Full coverage detail
(unit, scenario, sandbox, generated) lives in `docs/arch/generated/coverage_matrix.md`.

| Loop | ADR | Wiki | Notes |
|---|---|---|---|
| `ADRReviewerLoop` | (none) | [adr-reviewer-loop.md](../../wiki/terms/adr-reviewer-loop.md) | Caretaker loop |
| `AdrTouchpointAuditorLoop` | [0056, 0057] | [adr-touchpoint-auditor-loop.md](../../wiki/terms/adr-touchpoint-auditor-loop.md) | Trust fleet |
| `AutoAgentPreflightLoop` | [0050, 0063] | dark-factory.md | Phase gap mitigation |
| `CIMonitorLoop` | [0029, 0065] | [ci-monitor-loop.md](../../wiki/terms/ci-monitor-loop.md) | Caretaker loop |
| `ContractRefreshLoop` | [0045, 0047] | [contract-refresh-loop.md](../../wiki/terms/contract-refresh-loop.md) | Trust fleet |
| `CorpusLearningLoop` | [0045] | [corpus-learning-loop.md](../../wiki/terms/corpus-learning-loop.md) | Trust fleet |
| `CostBudgetWatcherLoop` | [0054] | architecture.md | Caretaker loop |
| `DependabotMergeLoop` | [0054, 0057, 0058] | [dependabot-merge-loop.md](../../wiki/terms/dependabot-merge-loop.md) | Caretaker loop |
| `DiagnosticLoop` | [0050] | [diagnostic-loop.md](../../wiki/terms/diagnostic-loop.md) | Caretaker loop |
| `DiagramLoop` | [0001] | [diagram-loop.md](../../wiki/terms/diagram-loop.md) | Caretaker loop |
| `EdgeProposerLoop` | [0058, 0060, 0062] | [edge-proposer-loop.md](../../wiki/terms/edge-proposer-loop.md) | Caretaker loop |
| `EntryEvidenceLoop` | [0062] | [entry-evidence-loop.md](../../wiki/terms/entry-evidence-loop.md) | Caretaker loop |
| `EpicMonitorLoop` | [0080](../../adr/0080-epic-monitor-loop.md) | architecture-async-control.md | Caretaker loop |
| `EpicSweeperLoop` | [0081](../../adr/0081-epic-sweeper-loop.md) | architecture-async-control.md | Caretaker loop |
| `FakeCoverageAuditorLoop` | [0045, 0056, 0057] | [fake-coverage-auditor-loop.md](../../wiki/terms/fake-coverage-auditor-loop.md) | Trust fleet |
| `FlakeTrackerLoop` | [0045, 0056, 0057, 0065] | [flake-tracker-loop.md](../../wiki/terms/flake-tracker-loop.md) | Trust fleet |
| `GitHubCacheLoop` | (none) | [github-cache-loop.md](../../wiki/terms/github-cache-loop.md) | Caretaker loop |
| `HealthMonitorLoop` | [0045, 0046] | testing.md | Caretaker loop |
| `LabelDriftWatcherLoop` | [0056] | (none) | Caretaker loop |
| `MemoryBacklogLoop` | [0057] | README.md | Caretaker loop |
| `MergeStateWatcherLoop` | (none) | [merge-state-watcher-loop.md](../../wiki/terms/merge-state-watcher-loop.md) | Caretaker loop |
| `PRUnstickerLoop` | (none) | [pr-unsticker-loop.md](../../wiki/terms/pr-unsticker-loop.md) | Caretaker loop |
| `PricingRefreshLoop` | (none) | [pricing-refresh-loop.md](../../wiki/terms/pricing-refresh-loop.md) | Caretaker loop |
| `PrinciplesAuditLoop` | [0045, 0056] | dark-factory.md | Trust fleet |
| `RCBudgetLoop` | [0045] | [rc-budget-loop.md](../../wiki/terms/rc-budget-loop.md) | Trust fleet |
| `RepoWikiLoop` | [0032, 0053, 0061, 0062, 0064] | dark-factory.md | Caretaker loop |
| `ReportIssueLoop` | [0013, 0018, 0028] | [report-issue-loop.md](../../wiki/terms/report-issue-loop.md) | Caretaker loop |
| `RetrospectiveLoop` | (none) | architecture-async-control.md | Caretaker loop |
| `RunsGCLoop` | (none) | architecture-async-control.md | Caretaker loop |
| `SandboxFailureFixerLoop` | [0052, 0063] | dark-factory.md | Caretaker loop |
| `SecurityPatchLoop` | [0029, 0065] | architecture-async-control.md | Caretaker loop |
| `SentryLoop` | [0055] | [sentry-loop.md](../../wiki/terms/sentry-loop.md) | Caretaker loop |
| `SkillPromptEvalLoop` | [0045] | [skill-prompt-eval-loop.md](../../wiki/terms/skill-prompt-eval-loop.md) | Trust fleet |
| `StagingBisectLoop` | [0045, 0048, 0063] | architecture.md | Trust fleet |
| `StagingPromotionLoop` | [0042] | patterns.md | Caretaker loop |
| `StaleIssueGCLoop` | [0029] | [stale-issue-gc-loop.md](../../wiki/terms/stale-issue-gc-loop.md) | Caretaker loop |
| `StaleIssueLoop` | (none) | gotchas.md | Caretaker loop |
| `TermProposerLoop` | [0054, 0057, 0060, 0061, 0062] | bot-pr-port.md | Caretaker loop |
| `TermPrunerLoop` | [0057, 0060, 0062] | (none) | Caretaker loop |
| `TriageRetryLoop` | [0063] | (none) | Caretaker loop |
| `TrustFleetSanityLoop` | [0045, 0046] | testing.md | Trust fleet |
| `WikiRotDetectorLoop` | [0045, 0056, 0057] | (none) | Trust fleet |
| `WorkspaceGCLoop` | (none) | (none) | Caretaker loop |

## Discoverability

This standard is referenced from:

- `docs/standards/factory_operation/README.md` — kernel standards table
- `docs/wiki/gotchas.md` — "Background loop wiring: synchronize 5 locations"
- `docs/arch/generated/coverage_matrix.md` — Standard column for each loop and port
