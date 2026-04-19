---
id: 0038
topic: architecture
source_issue: 6321
source_phase: plan
created_at: 2026-04-10T04:19:28.375232+00:00
status: active
---

# Import-site patch targets must migrate with extracted functions

When tests patch functions at import sites (e.g., `patch('review_phase.analyze_patterns')`), extracting those functions to new modules breaks the patch. Update test patches to target the new module where the function is now imported: `patch('review_insight_recorder.analyze_patterns')`. Attribute mocking via instance assignment (e.g., `phase.attr = Mock()`) continues to work unchanged.
