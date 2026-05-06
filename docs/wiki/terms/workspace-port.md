---
id: "01KQV37D10M06PGF32CF77W6K8"
name: "WorkspacePort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:WorkspacePort"
aliases: ["workspace port", "worktree port", "git workspace port"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668789+00:00"
updated_at: "2026-05-05T03:35:36.668790+00:00"
---

## Definition

Hexagonal port for git workspace lifecycle operations — create and destroy isolated worktrees per issue, merge main into a worktree, list conflicting files, hard-reset to origin/main, abort an in-progress merge, and run post-work cleanup. Implemented by workspace.WorkspaceManager; the abstraction is what lets phases stay agnostic to the concrete worktree machinery.

## Invariants

- Pure Protocol — no implementation, no state.
- Each managed worktree is keyed by issue_number; create() returns the worktree path used for subsequent calls.
