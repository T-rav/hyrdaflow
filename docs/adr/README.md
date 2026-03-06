# Architecture Decision Records

Lightweight ADRs documenting key design decisions in HydraFlow.

## Format

Each ADR has: **Status**, **Date**, **Context**, **Decision**, **Consequences**,
and optionally **Alternatives considered** and **Related** links.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-five-concurrent-async-loops.md) | Five Concurrent Async Loops | Accepted |
| [0002](0002-labels-as-state-machine.md) | GitHub Labels as the Pipeline State Machine | Accepted |
| [0003](0003-git-worktrees-for-isolation.md) | Git Worktrees for Issue Isolation | Accepted |
| [0004](0004-agent-cli-as-runtime.md) | CLI-based Agent Runtime (Claude / Codex / Pi.dev) | Accepted |
| [0005](0005-pr-recovery-and-zero-diff-branch-handling.md) | PR Recovery and Zero-Diff Branch Handling in Implement Phase | Accepted |
| [0006](0006-repo-runtime-isolation.md) | RepoRuntime Isolation Architecture | Superseded by ADR-0009 |
| [0007](0007-dashboard-api-multi-repo-scoping.md) | Dashboard API Architecture for Multi-Repo Scoping | Accepted |
| [0008](0008-multi-repo-dashboard-architecture.md) | Multi-Repo Dashboard Architecture | Proposed |
| [0009](0009-multi-repo-process-per-repo-model.md) | Multi-Repo Process-Per-Repo Model | Accepted |
| [0010](0010-worktree-and-path-isolation.md) | Worktree and Path Isolation Architecture | Proposed |
| [0011](0011-epic-release-creation-architecture.md) | Epic Release Creation Architecture | Proposed |
| [0012](0012-epic-merge-coordination-architecture.md) | Epic Merge Coordination Architecture | Proposed |
| [0013](0013-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Superseded by ADR-0018 |
| [0014](0014-session-counter-forward-progression-semantics.md) | Session Counter Forward-Progression Semantics | Accepted |
| [0015](0015-protocol-callback-gate-pattern.md) | Protocol-Based Callback Injection Gate Pattern | Proposed |
| [0016](0016-visual-validation-skipped-override-semantics.md) | VisualValidation SKIPPED Override Semantics | Accepted |
| [0017](0017-auto-decompose-triage-counter-exclusion.md) | Auto-Decompose Triage Counter Exclusion | Accepted |
| [0018](0018-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Accepted |
| [0019](0019-background-task-delegation-abstraction-layer.md) | Background Task Delegation Abstraction Layer | Accepted |
| [0020](0020-autoApproveRow-border-context-awareness.md) | autoApproveRow Border Context Awareness | Proposed |
| [0021](0021-persistence-architecture-and-data-layout.md) | Persistence Architecture and Data Layout | Proposed |

## Adding a new ADR

Copy the template, increment the number, fill in the sections.
Mark superseded ADRs as `Superseded by ADR-XXXX` rather than deleting them.
