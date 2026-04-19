---
id: 0022
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.852290+00:00
status: active
---

# Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle

When adding async support to sync I/O code, keep all sync methods unchanged and add a-prefixed async wrappers that delegate to sync methods via asyncio.to_thread(). This pattern (established in events.py) centralizes blocking-operation wrapping and preserves backward compatibility—existing sync callers continue unchanged while new async callers gradually migrate. Implement async context managers by adding `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. This pattern (established in DockerRunner) ensures clean resource shutdown semantics when wrapping clients that need guaranteed cleanup. When extracting async helpers, shared resources (like background tasks) may be awaited on the happy path but must be cancelled in the coordinator's error handler. Design the helper to handle its portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block to ensure it runs regardless of how the helper exits. For done callbacks, follow the events.py pattern of defining module-level callback functions (e.g., _log_task_failure) rather than methods. This keeps callback logic portable, testable in isolation, and consistent across the codebase. Document expected signature and side effects clearly. See also: Orchestrator/Sequencer Design for coordinating async stages.
