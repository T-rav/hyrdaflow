---
id: 0065
topic: architecture
source_issue: 6334
source_phase: plan
created_at: 2026-04-10T05:40:10.652318+00:00
status: active
---

# Distinguish local wiring from cross-group wiring at architecture boundary

Post-construction mutations fall into two categories: local (both objects created in same sub-factory, e.g., `shape_phase._council = ExpertCouncil(...)`) and cross-group (objects from different sub-factories, e.g., `agents._insights = review_insights`). Local wiring stays in the sub-factory; cross-group wiring moves to the thin orchestrator. This boundary clarifies dependency coupling.
