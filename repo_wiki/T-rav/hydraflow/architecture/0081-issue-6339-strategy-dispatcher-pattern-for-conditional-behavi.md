---
id: 0081
topic: architecture
source_issue: 6339
source_phase: plan
created_at: 2026-04-10T06:19:03.788199+00:00
status: active
---

# Strategy dispatcher pattern for conditional behavior branches

For methods with conditional logic based on an enum (e.g., release strategy: BUNDLED vs ORDERED vs HITL), create a single dispatcher method (`handle_ready(strategy)`) that routes to private strategy handlers. This centralizes the branching logic and makes it testable without exposing individual handlers.
