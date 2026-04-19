---
id: 0110
topic: architecture
source_issue: 6362
source_phase: plan
created_at: 2026-04-10T07:44:23.400349+00:00
status: active
---

# Context manager protocol for async resource pooling

Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to an existing `close()` method. Follow the exact pattern from `DockerRunner` (src/docker_runner.py:357-361) for type-safe implementation. This enables `async with` syntax and proper cleanup.
