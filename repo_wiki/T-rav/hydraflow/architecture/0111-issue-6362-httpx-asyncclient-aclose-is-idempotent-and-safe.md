---
id: 0111
topic: architecture
source_issue: 6362
source_phase: plan
created_at: 2026-04-10T07:44:23.400455+00:00
status: active
---

# httpx.AsyncClient.aclose() is idempotent and safe

httpx clients handle multiple `aclose()` calls gracefully (no-op on already-closed). Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing hindsight). Eliminates need for guard flags or state tracking.
