---
id: 0060
topic: architecture
source_issue: 6296
source_phase: review
created_at: 2026-04-10T05:36:08.671687+00:00
status: active
---

# Validate diagram references point to existing code

Architecture diagrams (e.g., .likec4 files) can reference non-existent test files or code paths, creating confusion about implementation status. Before merging diagram changes, validate that all references (test files, classes, modules) actually exist in the codebase. This caught tests referenced but never created.
