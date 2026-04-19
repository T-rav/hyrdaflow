---
id: 0071
topic: architecture
source_issue: 6338
source_phase: plan
created_at: 2026-04-10T05:56:11.037241+00:00
status: active
---

# Acceptance Criteria: Distinguish Public Facades from Implementation

When refactoring with a facade pattern, acceptance criteria like "no class exceeds N public methods" should apply to *implementation classes*, not the facade. The facade may have many public methods (e.g., 12+) as delegation stubs—each stub is 1-2 lines. Implementation classes extracted into sub-modules stay under 7-8 public methods and 230 lines. Clarify this distinction upfront to avoid criteria conflicts.
