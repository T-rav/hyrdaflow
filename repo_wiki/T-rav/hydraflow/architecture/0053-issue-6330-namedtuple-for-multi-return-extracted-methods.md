---
id: 0053
topic: architecture
source_issue: 6330
source_phase: plan
created_at: 2026-04-10T05:17:59.124011+00:00
status: active
---

# NamedTuple for multi-return extracted methods

When an extracted method returns multiple related values (like _build_context_sections returning multiple section strings), use a lightweight NamedTuple instead of creating a dataclass or new class. This avoids test infrastructure breakage while providing named access and self-documenting return types.
