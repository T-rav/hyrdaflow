---
id: 0114
topic: architecture
source_issue: 6362
source_phase: plan
created_at: 2026-04-10T07:44:23.400484+00:00
status: active
---

# Service composition root needs async cleanup method

ServiceRegistry (composition root) should have an `async def aclose()` method that closes owned resources like `self.hindsight`. Keep it as the first method on the dataclass. Enables caller to clean up composition root in one call.
