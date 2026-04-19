---
id: 0085
topic: architecture
source_issue: 6342
source_phase: plan
created_at: 2026-04-10T06:32:57.301525+00:00
status: active
---

# Design extracted methods for future integration without implementing it

Accept parameters that aren't currently used (e.g., `release_url` in `_build_close_comment()` is always passed as empty string) if they enable future feature work without forcing changes later. This is the inverse of premature abstraction: you're adding a seam, not a full feature.
