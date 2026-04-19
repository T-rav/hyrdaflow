---
id: 0010
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849555+00:00
status: active
---

# Clarity Score Routing: Fast Path vs Multi-Stage Maturation

The discovery phase routes issues in two tracks based on clarity_score: (1) clarity_score >= 7: skip Discover and Shape, go directly from Triage to Plan (fast path); (2) clarity_score < 7: route through Discover → Shape pipeline for multi-turn maturation (slow path). Three-stage pipeline design: Discover gathers product research context, Shape runs multi-turn design conversation and presents options for human selection, Plan begins after direction is chosen. This staged approach separates research, synthesis, and planning concerns with human decision points between stages.
