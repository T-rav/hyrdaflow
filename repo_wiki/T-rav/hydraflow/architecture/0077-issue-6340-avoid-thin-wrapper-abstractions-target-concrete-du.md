---
id: 0077
topic: architecture
source_issue: 6340
source_phase: plan
created_at: 2026-04-10T06:11:06.699114+00:00
status: active
---

# Avoid thin-wrapper abstractions—target concrete duplication

Rejected a `_build_base_prompt_context()` wrapper returning a tuple, noting it would create coupling without eliminating real duplication. Instead, target specific repeated code: only 4 runners share the memory query context string, only 2 share the dedup pattern. Extract only where there is genuine repeated code, not perceived similarity.
