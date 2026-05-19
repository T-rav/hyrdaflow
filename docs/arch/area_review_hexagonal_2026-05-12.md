# Area Review: Hexagonal Boundaries (Ports)

**Slice:** 5.2 of 5  
**Date:** 2026-05-12  
**Reviewer:** automated (Claude Code audit agent)  
**Scope:** 9 Ports — AgentPort, BotPRPort, IssueFetcherPort, IssueStorePort, ObservabilityPort, PRPort, ReviewInsightStorePort, RouteBackCounterPort, WorkspacePort

---

## Summary matrix

| Port | Port quality | Adapter quality | Fake fidelity | Consumer coverage | Wiki/ADR currency |
|------|-------------|----------------|---------------|-------------------|-------------------|
| AgentPort | ⚠️ partial | ✅ clean | ❌ no-fake [bd:hex-01] | ⚠️ thin [bd:hex-02] | ⚠️ sparse [bd:hex-03] |
| BotPRPort | ✅ clean | ✅ clean | ❌ no-fake [bd:hex-04] | ⚠️ thin | ✅ documented |
| IssueFetcherPort | ✅ clean | ✅ clean | ✅ matches-reality | ✅ covered | ✅ documented |
| IssueStorePort | ✅ clean | ✅ clean | ✅ matches-reality | ✅ covered | ✅ documented |
| ObservabilityPort | ⚠️ partial | ❌ no-adapter [bd:hex-05] | ❌ no-fake [bd:hex-06] | ❌ unverified [bd:hex-07] | ⚠️ sparse [bd:hex-08] |
| PRPort | ⚠️ partial [bd:hex-09] | ✅ clean | ✅ matches-reality | ✅ covered | ✅ documented |
| ReviewInsightStorePort | ✅ clean | ✅ clean | ❌ no-fake [bd:hex-10] | ⚠️ thin [bd:hex-11] | ⚠️ sparse [bd:hex-12] |
| RouteBackCounterPort | ✅ clean | ✅ clean | ⚠️ drift-risk [bd:hex-13] | ✅ covered | ⚠️ sparse [bd:hex-14] |
| WorkspacePort | ✅ clean | ✅ clean | ✅ matches-reality | ✅ covered | ✅ documented |

**Counts:** ✅ 27 · ⚠️ 9 · ❌ 9

---

## Per-port notes

### AgentPort

**Port quality: ⚠️ partial**

`AgentPort` exposes three private methods (`_build_command`, `_execute`, `_verify_result`). Prefixed names leak implementation internals through the port boundary — a Port should declare domain operations, not internal runner machinery. The methods are correct as a Protocol surface (structural subtyping works), but the leading underscore signals "private to the class" while they are in fact part of the public hexagonal contract. `merge_conflict_resolver.py` calls them at lines 191–207 and 320–336.

**Adapter quality: ✅ clean**

`AgentRunner` (via `BaseRunner`) satisfies the protocol. `tests/test_ports.py` has `TestAgentPortConformance` and `TestAgentPortMethods` covering all three methods. `TestAgentPortSignatures` covers `_build_command` and `_execute` but not `_verify_result` (gap noted in [bd:hex-02]).

**Fake fidelity: ❌ no-fake** [bd:hex-01]

No fake exists. ADR-0047 requires a fake for every port. Tests in `merge_conflict_resolver` that depend on `AgentPort` use `AsyncMock` / `MagicMock` stubs, which do not enforce the port contract at runtime.

**Consumer coverage: ⚠️ thin** [bd:hex-02]

`merge_conflict_resolver.py` is the sole consumer. The resolver calls private methods directly (not via a domain abstraction), and no scenario test exercises it via a conforming fake. Signature test for `_verify_result` is also missing from `TestAgentPortSignatures._SIGNED_METHODS`.

**Wiki/ADR currency: ⚠️ sparse** [bd:hex-03]

`docs/wiki/terms/agent-runner.md` exists, but AgentPort's contract (why these three methods form the boundary, which callers use it) is not described. No ADR covers the AgentPort hexagonal boundary specifically.

---

### BotPRPort

**Port quality: ✅ clean**

Single-method protocol (`open_bot_pr`) with a well-bounded signature. Defined in `src/term_proposer_loop.py`. Clear documentation of intent ("Minimal interface for opening bot PRs. Subset of PRPort."). Domain-facing name.

**Adapter quality: ✅ clean**

`OpenAutoPRBotPRPort` in `src/term_proposer_runtime.py` implements the protocol cleanly. Delegates to `auto_pr.open_automated_pr_async`, handles failure, parses the PR URL to return a typed number. Short and self-contained.

**Fake fidelity: ❌ no-fake** [bd:hex-04]

No fake exists. Tests in `test_term_proposer_pr_opener.py` and `test_term_pruner_loop.py` use `AsyncMock` stubs or monkeypatching. Three consumers (`TermProposerLoop`, `TermPrunerLoop`, `EdgeProposerLoop`) cannot be tested via a conforming fake that enforces the protocol.

**Consumer coverage: ⚠️ thin**

Three loops consume `BotPRPort`: `TermProposerLoop`, `TermPrunerLoop`, `EdgeProposerLoop`. Tests exist for each loop, but they use `AsyncMock` stubs that do not enforce the port contract. No scenario uses a `FakeBotPRPort`.

**Wiki/ADR currency: ✅ documented**

`docs/wiki/terms/bot-pr-port.md` exists. ADR-0054 covers the TermProposer pattern that introduced this port.

---

### IssueFetcherPort

**Port quality: ✅ clean**

Two methods, clear names (`fetch_issue_by_number`, `fetch_issues_by_labels`). Defined in `src/ports.py` alongside the other core ports. Signatures stable. Single responsibility.

**Adapter quality: ✅ clean**

`IssueFetcher` in `src/issue_fetcher.py` satisfies the protocol; `tests/test_ports.py` has `TestIssueFetcherPortConformance`, `TestIssueFetcherPortMethods`, and `TestIssueFetcherPortSignatures`.

**Fake fidelity: ✅ matches-reality**

`FakeIssueFetcher` in `mockworld/fakes/fake_issue_fetcher.py` implements both port methods with semantically correct behavior (open-state filter, label intersection, exclude_labels, limit). The `require_complete` no-op is explicitly documented. The fake also provides concrete-only methods (`fetch_all_hydraflow_issues`, `fetch_issue_comments`, `fetch_reviewable_prs`) for duck-typed orchestrator paths, documented clearly.

**Consumer coverage: ✅ covered**

`HitlPhase`, `EpicSweeperLoop`, `PrUnsticker` all consume via the port. 2 scenario test files exercise the fake directly; `FakeIssueFetcher` is also used in the orchestrator integration tests (via `sandbox_main.py`).

**Wiki/ADR currency: ✅ documented**

No dedicated wiki term entry for IssueFetcherPort (unlike the others), but it is covered in `docs/wiki/architecture-layers.md` and the generated ports doc is fresh.

---

### IssueStorePort

**Port quality: ✅ clean**

11 methods with clear domain semantics. `enrich_with_comments` is the only async method; the rest are synchronous queue operations. Single responsibility. The docstring correctly identifies which callers are in scope ("Only the methods consumed by domain code").

**Adapter quality: ✅ clean**

Two adapters: `IssueStore` (primary) and `CachingIssueStore` (decorator). Both implement the full port. `CachingIssueStore` delegates all writes pass-through and adds a read-through enrichment cache — clean decorator pattern. `service_registry.py` notes the cast workaround (`cast(IssueStore, store)` for orchestrator-only methods) and promises it will be removed once the port is widened; this is a tracked known gap, not a silent leak.

**Fake fidelity: ✅ matches-reality**

`FakeIssueStore` implements all 11 port methods. Labels serve as source-of-truth (intentional simplification, documented). Active/in-flight tracking mirrors the real store's semantics adequately for scenario assertions on end-state outcomes. Concrete-only orchestrator methods (`start`, `get_queue_stats`, `get_pipeline_snapshot`) are also present.

**Consumer coverage: ✅ covered**

`ImplementPhase`, `PlanPhase`, `PhaseUtils`, `CachingIssueStore` all consume via the port. 7 scenario files exercise `FakeIssueStore`.

**Wiki/ADR currency: ✅ documented**

`docs/wiki/terms/issue-store-port.md` exists. ADR-0021 covers the persistence architecture.

---

### ObservabilityPort

**Port quality: ⚠️ partial**

`ObservabilityPort` in `src/ports.py` is well-designed (3 methods, minimal surface, clear intent). The docstring correctly identifies the purpose and future-proofing rationale. However, the port is **never injected anywhere** — zero production call sites use `ObservabilityPort` as a type annotation; Sentry is called directly throughout the codebase via `sentry_sdk.capture_exception`, `sentry_sdk.add_breadcrumb`, and `import sentry_sdk as _sentry` at the call site. The port exists as dead architecture.

**Adapter quality: ❌ no-adapter** [bd:hex-05]

No concrete `ObservabilityPort` adapter class exists. `FakeSentry` in `mockworld/fakes/fake_sentry.py` has overlapping methods (`add_breadcrumb`, `capture_exception`) but does not claim to implement `ObservabilityPort` and its method signatures differ (`add_breadcrumb(**kwargs)` vs the Port's `breadcrumb(category, message, **data)`).

**Fake fidelity: ❌ no-fake** [bd:hex-06]

No fake implementing `ObservabilityPort` exists. `FakeSentry` is not aligned to the port interface.

**Consumer coverage: ❌ unverified** [bd:hex-07]

No code injects `ObservabilityPort`. The Sentry SDK is imported directly at 10+ call sites (`exception_classify.py`, `triage.py`, `log_ingestion.py`, `health_monitor_loop.py`, `review_insights.py`, `troubleshooting_store.py`, `retrospective.py`, `harness_insights.py`, `stale_issue_loop.py`). No scenario test can swap in a `FakeObservability` to assert on breadcrumb/exception calls because the port is not wired.

**Wiki/ADR currency: ⚠️ sparse** [bd:hex-08]

Not covered in the wiki terms directory. The `ports.py` docstring describes intent, and the generated ports.md documents it as lacking a fake, but no wiki entry explains the intended wiring or the gap between the port definition and the actual sentry-direct pattern.

---

### PRPort

**Port quality: ⚠️ partial** [bd:hex-09]

`PRPort` contains **52 methods** — the largest port by a wide margin. Mixed domains are present in a single interface:

1. Branch/PR lifecycle (push, create, merge, delete — 12 methods)
2. Label management (add/remove labels on issues and PRs — 5 methods)
3. Comments and reviews (3 methods)
4. CI/checks (3 methods)
5. Issue management (close, find, create, list, update — 10 methods)
6. RC/promotion workflow (create_rc_branch, push_synthetic_commit, create_promotion_pr — 7 methods)
7. HITL query (1 method)
8. TaskTransitioner compatibility shim (transition, close_task, create_task — 3 methods, documented as compatibility)

The TaskTransitioner compat section explicitly documents why it is here ("PRManager satisfies both PRPort and TaskTransitioner"). The issue management group mixes GitHub issue operations with PR operations in one port; `IssuePort` could logically separate them, but the current grouping is intentional convenience — acknowledged rather than accidental. Not a blocking concern but worth tracking.

**Adapter quality: ✅ clean**

`PRManager` at 3135 lines with 101 methods. All 52 PRPort methods are present and covered by `TestPRPortConformance`. However, `TestPRPortSignatures._SIGNED_METHODS` only covers 31 of 52 methods — 20 PRPort methods (including all RC/staging promotion methods and label drift) have no signature conformance test.

**Fake fidelity: ✅ matches-reality**

`FakeGitHub` implements all 52 PRPort methods. Comparison via `python3 -c` confirms zero gaps. The fake faithfully models: rate limiting, CI scripting, draft/merged state, label management, RC branch operations, promotion PRs, label drift detection, and conflicting PRs. 30 scenario test files exercise the fake.

**Consumer coverage: ✅ covered**

`ImplementPhase`, `PlanPhase`, `HitlPhase`, `WorkspaceGCLoop`, `MergeStateWatcherLoop`, `DependabotMergeLoop`, `HealthMonitorLoop`, `StagingBisectLoop`, `SandboxFailureFixerLoop`, `DiagramLoop`, and `MergeConflictResolver` all consume via the port.

**Wiki/ADR currency: ✅ documented**

`docs/wiki/terms/pr-port.md` exists. Multiple ADRs reference PRPort (ADR-0002, ADR-0042, ADR-0056).

---

### ReviewInsightStorePort

**Port quality: ✅ clean**

7 methods, all synchronous, domain-facing names. Single responsibility: review insight persistence. The docstring identifies the sole consumer (`ReviewPhase`) and the concrete adapter (`ReviewInsightStore`).

**Adapter quality: ✅ clean**

`ReviewInsightStore` in `src/review_insights.py` implements all 7 methods. Tests in `tests/test_review_insights.py` exercise the concrete class directly with `tmp_path`-backed instances.

**Fake fidelity: ❌ no-fake** [bd:hex-10]

No fake implementing `ReviewInsightStorePort` exists. Tests for `ReviewPhase` that need insight tracking create `ReviewInsightStore` instances directly against `tmp_path`. This is functional but bypasses the port boundary and makes scenario-level testing of insight accumulation impossible without filesystem I/O.

**Consumer coverage: ⚠️ thin** [bd:hex-11]

`ReviewPhase._phase.py` is the only consumer (line 158: `review_insights: ReviewInsightStorePort | None = None`). Tests inject the concrete class directly rather than through a fake. `review_insights.py` itself also accepts `ReviewInsightStore | ReviewInsightStorePort` at line 523, a union that suggests the port type annotation is not consistently used.

**Wiki/ADR currency: ⚠️ sparse** [bd:hex-12]

No wiki terms entry for `ReviewInsightStorePort`. The port purpose and its relationship to `ReviewPhase` and the insight aggregation pipeline are undocumented beyond the code.

---

### RouteBackCounterPort

**Port quality: ✅ clean**

3 methods, all synchronous, domain-facing names. The decrement method includes a clear rollback rationale in its docstring (counter undo on label-swap failure). Defined in `src/route_back.py` alongside `RouteBackCoordinator`.

**Adapter quality: ✅ clean**

`RouteBackStateMixin` in `src/state/_route_back.py` implements all 3 methods plus `reset_route_back_count` (a concrete-only helper). The mixin depends on `StateTracker._data.route_back_counts` and `self.save()`, documented with `...` stubs for what `CoreMixin`/`StateTracker` supply. Clean, focused implementation.

**Fake fidelity: ⚠️ drift-risk** [bd:hex-13]

`InMemoryRouteBackCounter` in `tests/helpers.py` is a test-only helper implementing the port, not a first-class mockworld fake. It lives in `tests/helpers.py` (not `mockworld/fakes/`) and is not discoverable for scenario use. The implementation is correct and well-documented, but its location means it could drift from the `RouteBackStateMixin` semantics without the mockworld conformance machinery catching it. ADR-0047 requires a proper `mockworld/fakes/` fake.

**Consumer coverage: ✅ covered**

`RouteBackCoordinator` is the sole consumer. `tests/test_route_back.py` uses `InMemoryRouteBackCounter` throughout, covering increment, decrement, rollback, escalation, and per-issue independence. `tests/test_precondition_gate.py` also uses it. `service_registry.py` wires `StateTracker` (which includes `RouteBackStateMixin`) as the production adapter.

**Wiki/ADR currency: ⚠️ sparse** [bd:hex-14]

No wiki terms entry for `RouteBackCounterPort`. The broader `route-back` pattern is documented (issue #6423), but the port's hexagonal role and the `StateTracker` wiring are not described in the wiki.

---

### WorkspacePort

**Port quality: ✅ clean**

10 methods, clear domain-facing names (create, destroy, merge_main, reset_to_main, abort_merge, start_merge_main, post_work_cleanup). Single responsibility: git workspace lifecycle. Clean separation from PR operations.

**Adapter quality: ✅ clean**

`WorkspaceManager` in `src/workspace.py` implements all 10 methods. `tests/test_ports.py` has full conformance, method existence, and signature tests. `service_registry.py` documents the `cast(WorkspaceManager, workspaces)` workaround for orchestrator-only methods (`enable_rerere`, `sanitize_repo`) that are not on the port — a tracked known gap with a clear remediation path.

**Fake fidelity: ✅ matches-reality**

`FakeWorkspace` implements all 10 WorkspacePort methods. Extra methods (`enable_rerere`, `sanitize_repo`, `fail_next_create`) are concrete additions for orchestrator boot and fault injection. `FakeWorkspace.merge_main` always returns `True`; `start_merge_main` always returns `True`. This is documented intent for scenario testing (end-state assertions, not conflict simulation). For conflict scenarios, `fail_next_create` provides fault injection at the `create` level.

**Consumer coverage: ✅ covered**

`ImplementPhase`, `WorkspaceGCLoop`, `MergeConflictResolver`, `HitlPhase` all consume via the port. 6 scenario files exercise `FakeWorkspace`.

**Wiki/ADR currency: ✅ documented**

`docs/wiki/terms/workspace-port.md` exists. ADR-0003 covers the worktree pattern.

---

## Headline findings

### Finding 1: ObservabilityPort is dead architecture — the port exists but is never wired

`ObservabilityPort` is defined in `ports.py`, documented with a forward-looking rationale, but **no production code injects it**. Sentry is called directly at 10+ sites via `import sentry_sdk as _sentry`. The `FakeSentry` in `mockworld/fakes/` has mismatched method signatures from the port. This means the port provides zero isolation value today and scenario tests cannot observe breadcrumb/exception calls without adding `sentry_sdk` monkey-patching. The intent was right; the wiring was never completed.

### Finding 2: PRPort carries 52 methods — it is a God interface

52 methods across 7 logical domains. The port grew by accretion as new features (RC promotion, label drift, HITL, Dependabot) each added methods. The `transition`, `close_task`, `create_task` compatibility shim is explicitly documented but adds 3 non-PR methods. The practical cost: `FakeGitHub` is 900+ lines, the `TestPRPortSignatures` check only covers 31/52 methods, and 20 new methods since the original port design have no signature conformance tests. The port works, but drift risk is proportional to its surface area.

### Finding 3: AgentPort exposes private methods as the port contract

All three `AgentPort` methods carry leading underscores (`_build_command`, `_execute`, `_verify_result`). In Python convention, `_` means "private to this class." The port has formalized internal runner machinery as a hexagonal boundary. This is semantically confusing and causes type checkers to flag callers as accessing private members. A refactor to `run(prompt, worktree_path, ...)` returning a result object would be cleaner.

### Finding 4: RouteBackCounterPort fake lives in tests/helpers.py, not mockworld/fakes/

`InMemoryRouteBackCounter` is a correct implementation of `RouteBackCounterPort` but sits in `tests/helpers.py` rather than `mockworld/fakes/`. This puts it outside the mockworld conformance machinery (the `_is_fake_adapter` marker, `from_seed` convention, scenario harness discovery). It functions correctly for unit tests but is invisible to scenario tests and the fake coverage auditor.

---

## 3 + 3 sampling

### 3 things working well

1. **IssueFetcherPort / IssueStorePort / WorkspacePort fake fidelity** — all three fakes correctly implement the full port surface, are discoverable from `mockworld/fakes/`, carry `_is_fake_adapter = True`, and are used in 2, 7, and 6 scenario files respectively. The port + fake + conformance test triangle is complete for these three ports.

2. **PRPort fake completeness** — `FakeGitHub` implements all 52 PRPort methods with zero gaps (confirmed by AST comparison). The fake is exercised in 30 scenario files. The method-to-method alignment is a genuine achievement given the port's size.

3. **RouteBackCoordinator test depth** — `tests/test_route_back.py` covers increment, rollback on label-swap failure, per-issue independence, and HITL escalation with explicit counter assertions. This is thorough coverage of the invariants that matter.

### 3 things needing work

1. **ObservabilityPort requires a complete wiring pass** — define a `SentryObservabilityAdapter`, inject `ObservabilityPort` at the call sites that today do `import sentry_sdk`, and build a `FakeObservability` in `mockworld/fakes/`. The port is defined; none of the connective tissue exists.

2. **PRPort signature coverage gap** — `TestPRPortSignatures._SIGNED_METHODS` covers 31/52 methods. Add the 20 uncovered methods (all RC promotion, label-drift, listing, and TaskTransitioner compat methods) to the signature test to catch future drift.

3. **AgentPort, BotPRPort, ReviewInsightStorePort, RouteBackCounterPort all lack first-class mockworld fakes** — all four should follow the `mockworld/fakes/` convention. The `InMemoryRouteBackCounter` can be promoted as-is; the others need new fakes.

---

## Bead index

| ID | Cell | Labels | Title |
|----|------|--------|-------|
| bd:hex-01 | AgentPort / fake | area-review-gap, area:hexagonal_boundaries, kind:fake | AgentPort has no mockworld fake — ADR-0047 requirement unmet |
| bd:hex-02 | AgentPort / consumer | area-review-gap, area:hexagonal_boundaries, kind:tests | AgentPort `_verify_result` missing from signature conformance test |
| bd:hex-03 | AgentPort / docs | area-review-gap, area:hexagonal_boundaries, kind:docs | AgentPort port contract undocumented in wiki |
| bd:hex-04 | BotPRPort / fake | area-review-gap, area:hexagonal_boundaries, kind:fake | BotPRPort has no mockworld fake — ADR-0047 requirement unmet |
| bd:hex-05 | ObservabilityPort / adapter | area-review-gap, area:hexagonal_boundaries, kind:adapter | ObservabilityPort has no concrete adapter — Sentry called directly |
| bd:hex-06 | ObservabilityPort / fake | area-review-gap, area:hexagonal_boundaries, kind:fake | ObservabilityPort has no fake and FakeSentry interface does not match port |
| bd:hex-07 | ObservabilityPort / consumer | area-review-gap, area:hexagonal_boundaries, kind:consumer | ObservabilityPort never injected — 10+ sites bypass port with direct sentry_sdk calls |
| bd:hex-08 | ObservabilityPort / docs | area-review-gap, area:hexagonal_boundaries, kind:docs | ObservabilityPort missing wiki entry |
| bd:hex-09 | PRPort / port | area-review-gap, area:hexagonal_boundaries, kind:port | PRPort 52-method God interface — 20 methods lack signature conformance tests |
| bd:hex-10 | ReviewInsightStorePort / fake | area-review-gap, area:hexagonal_boundaries, kind:fake | ReviewInsightStorePort has no mockworld fake — ADR-0047 requirement unmet |
| bd:hex-11 | ReviewInsightStorePort / consumer | area-review-gap, area:hexagonal_boundaries, kind:consumer | ReviewInsightStorePort union type `ReviewInsightStore \| ReviewInsightStorePort` undermines port discipline |
| bd:hex-12 | ReviewInsightStorePort / docs | area-review-gap, area:hexagonal_boundaries, kind:docs | ReviewInsightStorePort missing wiki entry |
| bd:hex-13 | RouteBackCounterPort / fake | area-review-gap, area:hexagonal_boundaries, kind:fake | RouteBackCounterPort InMemoryRouteBackCounter is in tests/helpers.py not mockworld/fakes/ |
| bd:hex-14 | RouteBackCounterPort / docs | area-review-gap, area:hexagonal_boundaries, kind:docs | RouteBackCounterPort missing wiki entry |
