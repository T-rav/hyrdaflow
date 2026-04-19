---
id: 0064
topic: architecture
source_issue: 6334
source_phase: plan
created_at: 2026-04-10T05:40:10.652297+00:00
status: active
---

# Sub-factory coordination via intermediate frozen dataclass

When decomposing a large factory function, bundle frequently-shared infrastructure (10+) into a frozen dataclass (e.g., `_CoreDeps`) and pass it to downstream sub-factories. This pattern, inherited from `LoopDeps` in `base_background_loop.py`, reduces parameter explosion and makes dependency ownership explicit without requiring typed classes for every service group.
