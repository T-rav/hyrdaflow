---
id: "01KQZR9QW4RJ5Q7TB2220V3JZN"
name: "BotPRPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/term_proposer_loop.py:BotPRPort"
aliases: ["bot pr port"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-06T22:59:51.300957+00:00"
updated_at: "2026-05-06T22:59:51.301155+00:00"
---

## Definition

Hexagonal port used by caretaker loops (TermProposerLoop, others) to open auto-merging bot PRs without coupling to the GitHub-specific PR adapter. Production wiring composes push_branch + create_pr + add_pr_labels behind this Protocol.

## Invariants

- Pure Protocol — no implementation; tests use a fake; production uses a thin adapter.
- open_bot_pr is the only method; one PR per call; success returns the PR number.
