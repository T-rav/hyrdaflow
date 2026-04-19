---
id: 0039
topic: architecture
source_issue: 6321
source_phase: plan
created_at: 2026-04-10T04:19:28.375241+00:00
status: active
---

# Strict no-circular-import rule for extracted coordinators

Extracted coordinator classes must never import the original ReviewPhase class. Coordinators should only import domain modules, models, config, and phase_utils. Back-references to ReviewPhase methods must flow through callback parameters passed at construction time. Violating this creates circular imports that break the extraction.
