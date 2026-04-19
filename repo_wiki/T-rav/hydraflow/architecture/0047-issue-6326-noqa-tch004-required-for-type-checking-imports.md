---
id: 0047
topic: architecture
source_issue: 6326
source_phase: plan
created_at: 2026-04-10T04:56:50.953061+00:00
status: active
---

# noqa: TCH004 required for TYPE_CHECKING imports

When using TYPE_CHECKING imports, always append `# noqa: TCH004` to suppress ruff's rule about imports appearing only in type checking. This is intentional and required for the pattern to work correctly. Omitting this comment will cause lint failures in the quality gates.
