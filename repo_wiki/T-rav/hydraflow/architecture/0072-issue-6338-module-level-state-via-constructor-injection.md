---
id: 0072
topic: architecture
source_issue: 6338
source_phase: plan
created_at: 2026-04-10T05:56:11.037248+00:00
status: active
---

# Module-Level State via Constructor Injection

When extracted classes need access to module-level state (e.g., `_FETCH_LOCKS` dict for regression test patching), pass it via constructor injection (e.g., `fetch_lock_fn: Callable[[], asyncio.Lock]`) rather than direct imports. This avoids circular dependencies between the facade and extracted modules while preserving the ability to patch module-level state in tests.
