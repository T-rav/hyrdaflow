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
| [0006](0006-repo-runtime-isolation.md) | RepoRuntime Isolation Architecture | Proposed |
| [0007](0007-dashboard-api-multi-repo-scoping.md) | Dashboard API Architecture for Multi-Repo Scoping | Proposed |
| [0008](0008-multi-repo-dashboard-architecture.md) | Multi-Repo Dashboard Architecture | Proposed |
| [0009](0009-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Proposed |

## Adding a new ADR

Copy the template, increment the number, fill in the sections.
Mark superseded ADRs as `Superseded by ADR-XXXX` rather than deleting them.
