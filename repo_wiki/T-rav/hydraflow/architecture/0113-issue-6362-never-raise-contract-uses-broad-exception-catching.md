---
id: 0113
topic: architecture
source_issue: 6362
source_phase: plan
created_at: 2026-04-10T07:44:23.400476+00:00
status: active
---

# Never-raise contract uses broad exception catching

Health checks and diagnostic functions should catch `Exception` (not specific types like `httpx.HTTPError`) and return False/safe default rather than propagate. Matches the `*_safe` pattern used for functions that must not raise (e.g., `retain_safe`, `recall_safe`).
