---
id: 0046
topic: architecture
source_issue: 6326
source_phase: plan
created_at: 2026-04-10T04:56:50.953037+00:00
status: active
---

# TYPE_CHECKING guard pattern for type-only imports

Use TYPE_CHECKING-guarded imports to avoid circular dependencies and runtime costs for type annotations. When a type is only needed for annotations (enabled by PEP 563 via `from __future__ import annotations`), import it under `if TYPE_CHECKING:` to prevent runtime import. This pattern is used consistently across 8+ files in the codebase and prevents the annotated name from triggering an actual import at runtime.
