---
id: "01KQV37D10M06PGF32CF77W6K2"
name: "HydraFlowConfig"
kind: "aggregate"
bounded_context: "shared-kernel"
code_anchor: "src/config.py:HydraFlowConfig"
aliases: ["hydraflow config", "config aggregate", "orchestrator config"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668539+00:00"
updated_at: "2026-05-05T03:35:36.668752+00:00"
---

## Definition

Pydantic-validated runtime configuration aggregate for the HydraFlow orchestrator. Bundles issue selection (ready labels, batch size, repo), per-phase concurrency caps (max_workers, max_planners, max_reviewers, max_triagers, max_hitl_workers), required-plugin manifests, language plugins, and per-phase skill whitelists into a single object passed to every loop and runner. Edited via the dashboard or config JSON file, not environment variables.

## Invariants

- Worker concurrency fields default to 1 and are bounded by ge=1, le=10 (max_hitl_workers le=5).
- batch_size is bounded ge=1, le=50.
- repo is auto-detected from the git remote when left empty.
