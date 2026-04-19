---
id: 0073
topic: architecture
source_issue: 6336
source_phase: plan
created_at: 2026-04-10T05:57:03.732493+00:00
status: active
---

# FastAPI route registration order affects specificity matching

In FastAPI, routes are matched in registration order. Generic routes like `/{path:path}` (SPA catch-all) must be registered last or they shadow more specific routes. When decomposing monolithic route handlers into sub-modules, document the required registration order and verify catch-all placement during refactoring.
