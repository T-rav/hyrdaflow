---
id: 0121
topic: architecture
source_issue: 6366
source_phase: plan
created_at: 2026-04-10T08:02:02.177061+00:00
status: active
---

# Audit __all__ exports when removing public functions

When removing public functions, check for stale __all__ exports or module re-exports that might still reference the removed symbols. This prevents subtle import errors and keeps the public API surface clean and explicit.
