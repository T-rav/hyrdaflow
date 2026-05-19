---
source: feedback_beads_workflow.md
name: Use beads for issue tracking
description: User wants all work tracked in beads (bd CLI) — claim issues, add notes, close on PR merge
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-03-28'
---

Always use beads (`bd` CLI) for tracking work on hydraflow issues:
1. `beads create` for new issues with labels, external-refs, types
2. `beads update <id> --claim` before starting work
3. `beads note <id> "..."` to log progress and PR numbers
4. `beads update <id> -s closed` when PR merges
5. `beads list` to show status

**Why:** User explicitly requested beads workflow. It's Steve Yegge's tool — installed via `brew install beads`. The `.beads/` dir in the repo holds the Dolt database.

**How to apply:** Every sprint/task should be tracked in beads alongside GitHub issues and PRs.
