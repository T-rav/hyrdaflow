---
id: 0090
topic: architecture
source_issue: 6347
source_phase: plan
created_at: 2026-04-10T06:40:05.820990+00:00
status: active
---

# Line number shifts in multi-PR merges break implementation plans

When a plan specifies exact line numbers for edits, document the search pattern (e.g., `def approve_count`) as a fallback. If other PRs merge first, line numbers shift—search-based edits remain valid and reduce merge conflicts.
