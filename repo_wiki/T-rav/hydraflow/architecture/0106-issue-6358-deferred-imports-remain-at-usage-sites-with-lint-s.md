---
id: 0106
topic: architecture
source_issue: 6358
source_phase: plan
created_at: 2026-04-10T07:30:03.436784+00:00
status: active
---

# Deferred imports remain at usage sites with lint suppression

Deferred imports (MemoryScorer, CompletedTimeline, json) must stay inside method bodies where used, not hoisted to module level. Annotate with `# noqa: PLC0415` to suppress linting warnings. This keeps import coupling local to method scope and avoids unintended module-level dependencies.
