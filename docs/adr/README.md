# Architecture Decision Records

Lightweight ADRs documenting key design decisions in HydraFlow.

## Format

Each ADR has: **Status**, **Date**, **Context**, **Decision**, **Consequences**,
and optionally **Alternatives considered** and **Related** links.

When referencing source code anywhere in an ADR (Related, Context, Decision,
Consequences), use `module:function_or_class` format (e.g. `src/config.py:HydraFlowConfig`).
**Omit line numbers** — they drift as code evolves and become stale quickly.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-five-concurrent-async-loops.md) | Five Concurrent Async Loops | Accepted |
| [0002](0002-labels-as-state-machine.md) | GitHub Labels as the Pipeline State Machine | Accepted |
| [0003](0003-git-worktrees-for-isolation.md) | Git Worktrees for Issue Isolation | Accepted |
| [0004](0004-agent-cli-as-runtime.md) | CLI-based Agent Runtime (Claude / Codex / Pi.dev) | Accepted |
| [0005](0005-pr-recovery-and-zero-diff-branch-handling.md) | PR Recovery and Zero-Diff Branch Handling in Implement Phase | Accepted |
| [0006](0006-repo-runtime-isolation.md) | RepoRuntime Isolation Architecture | Superseded |
| [0007](0007-dashboard-api-multi-repo-scoping.md) | Dashboard API Architecture for Multi-Repo Scoping | Accepted |
| [0008](0008-multi-repo-dashboard-architecture.md) | Multi-Repo Dashboard Architecture | Accepted |
| [0009](0009-multi-repo-process-per-repo-model.md) | Multi-Repo Process-Per-Repo Model | Accepted |
| [0010](0010-worktree-and-path-isolation.md) | Worktree and Path Isolation Architecture | Accepted |
| [0011](0011-epic-release-creation-architecture.md) | Epic Release Creation Architecture | Accepted |
| [0012](0012-epic-merge-coordination-architecture.md) | Epic Merge Coordination Architecture | Accepted |
| [0013](0013-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Superseded |
| [0014](0014-session-counter-forward-progression-semantics.md) | Session Counter Forward-Progression Semantics | Accepted |
| [0015](0015-protocol-callback-gate-pattern.md) | Protocol-Based Callback Injection Gate Pattern | Proposed |
| [0016](0016-visual-validation-skipped-override-semantics.md) | VisualValidation SKIPPED Override Semantics | Accepted |
| [0017](0017-auto-decompose-triage-counter-exclusion.md) | Auto-Decompose Triage Counter Exclusion | Accepted |
| [0018](0018-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Accepted |
| [0019](0019-background-task-delegation-abstraction-layer.md) | Background Task Delegation Abstraction Layer | Accepted |
| [0020](0020-autoApproveRow-border-context-awareness.md) | autoApproveRow Border Context Awareness | Superseded |
| [0021](0021-persistence-architecture-and-data-layout.md) | Persistence Architecture and Data Layout | Accepted |
| [0022](0022-integration-test-architecture-cross-phase.md) | Integration Test Architecture — Cross-Phase Pipeline Harness | Accepted |
| [0023](0023-dead-class-artifacts-in-mock-based-tests.md) | Require Instantiation Verification for Test-Local Classes | Proposed |
| [0024](0024-implementation-retry-recovery-architecture.md) | Implementation Retry Recovery Architecture | Accepted |
| [0025](0025-symmetric-field-assertion-checklist-shared-return-types.md) | Symmetric Field Assertion Checklist for Shared Return Types | Accepted |
| [0027](0027-duplicate-class-merge-artifact-pattern.md) | Duplicate Class Definitions — Merge-Artifact Pattern | Proposed |
| [0028](0028-event-driven-report-pipeline.md) | Event-Driven Report Pipeline with Extractable Widget | Accepted |
| [0029](0029-caretaker-loop-pattern.md) | Caretaker Background Loop Pattern | Accepted |
| [0030](0030-routes-domain-decomposition.md) | Dashboard Routes Domain Decomposition | Accepted |
| [0031](0031-product-track-architecture.md) | Product Track Architecture — Discover and Shape Phases | Proposed |
| [0032](0032-per-repo-wiki-knowledge-base.md) | Per-Repo Wiki Knowledge Base (Karpathy Pattern) | Accepted |
| [0033](0033-gate-triage-call-not-hitl-fallback.md) | Gate Triage Call on Config Toggle, Not Just HITL Fallback | Superseded |
| [0034](0034-auto-triage-toggle-must-gate-routing.md) | Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking | Accepted |
| [0035](0035-tests-must-match-toggle-state-they-assert.md) | Tests Must Match Toggle State They Assert | Proposed |
| [0036](0036-cli-argparse-config-builder-pattern.md) | CLI Architecture — argparse with Config Builder Pattern | Proposed |
| [0037](0037-supersession-regex-all-verb-forms.md) | Supersession Regex Must Include All Verb Forms | Accepted |
| [0038](0038-multi-repo-architecture-wiring-pattern.md) | Multi-Repo Architecture Wiring Pattern | Proposed |
| [0039](0039-stats-counter-placement-in-delegating-helpers.md) | Stats Counter Placement in Delegating Helpers | Rejected |
| [0040](0040-adr-reviewer-proposed-only-filter.md) | ADR Reviewer Proposed-Only Filter and Validator Scope | Rejected |
| [0041](0041-github-source-of-truth-cache-as-sidecar.md) | GitHub as Source of Truth, Local Cache as Sidecar | Accepted |
| [0042](0042-two-tier-branch-release-promotion.md) | Two-tier branch model with automated release-candidate promotion | Accepted |
| [0043](0043-prompt-structure-standard.md) | Prompt structure standard (XML tags, 8-criterion rubric, mechanical scoring) | Proposed |

## Adding a new ADR

Copy the template, increment the number, fill in the sections.
Mark superseded ADRs by setting `**Status:** Superseded` and adding a `Superseded by: ADR-XXXX` entry in the Related section rather than deleting them.
