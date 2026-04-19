---
id: 0078
topic: architecture
source_issue: 6340
source_phase: plan
created_at: 2026-04-10T06:11:06.699159+00:00
status: active
---

# Preserve lazy imports to avoid module-level coupling

When extracting a helper that imports heavy or optional dependencies like `PromptDeduplicator`, keep the import lazy inside the method body, not at module level. This matches existing patterns in the codebase and avoids import-time coupling to utilities that may not be needed on every execution path.
