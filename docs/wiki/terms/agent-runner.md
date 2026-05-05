---
id: "01KQV37D10M06PGF32CF77W6KA"
name: "AgentRunner"
kind: "runner"
bounded_context: "builder"
code_anchor: "src/agent.py:AgentRunner"
aliases: ["agent runner", "implement runner", "claude agent runner"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668798+00:00"
updated_at: "2026-05-05T03:35:36.668799+00:00"
---

## Definition

Subprocess runner for the implement phase: launches a `claude -p` process inside an isolated git worktree to implement a GitHub issue. Builds the agent's self-check checklist (extended by recent review escalations), spec-match guidance, and requirements-gap context, then commits the agent's changes locally. Pushing the branch and creating the PR are deliberately left to other phases.

## Invariants

- Phase name is fixed: _phase_name == 'implement'.
- The runner commits inside the worktree but never pushes or opens a PR — that work belongs to downstream phases.
- Self-check checklist is dynamically extended with checklist items from recurring review escalations.
