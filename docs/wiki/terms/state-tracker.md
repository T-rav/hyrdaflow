---
id: "01KQV37D10M06PGF32CF77W6K4"
name: "StateTracker"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/state/__init__.py:StateTracker"
aliases: ["state tracker", "state facade", "state mixin facade"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668771+00:00"
updated_at: "2026-05-05T03:35:36.668772+00:00"
---

## Definition

JSON-file backed state service for crash recovery. Composes ~30 domain mixins (issue, workspace, HITL, review, route-back, epic, session, worker, principles audit, sentry, trust fleet, ...) into a single facade that writes <repo_root>/.hydraflow/state.json after every mutation and rotates timestamped backups so a corrupt primary file can be restored from .bak.

## Invariants

- Every mutating method persists state to disk before returning.
- Issue/PR/epic numbers are stored as string keys; helpers convert to int on read.
- On corrupt primary file, load() falls back to the most recent .bak before defaulting to an empty StateData.
