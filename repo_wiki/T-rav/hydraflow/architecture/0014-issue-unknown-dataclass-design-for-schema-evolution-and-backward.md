---
id: 0014
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849570+00:00
status: active
---

# Dataclass Design for Schema Evolution and Backward Compatibility

Use TypedDict with total=False or Pydantic dataclasses with optional fields for backward-compatible schema evolution. Missing fields handled gracefully with .get(key, default). Use frozen dataclasses (`@dataclass(frozen=True, slots=True)`) to bundle context parameters that won't change at runtime. Include optional fields with empty string defaults for fields not yet populated, preventing accidental mutation and making contracts explicit. Placeholder fields anticipate feature extension points: add fields for planned features even if data sources don't exist yet, defaulting to empty strings with docstring notes. Model fields should include optional metadata that can be populated opportunistically, avoiding breaking changes later. Ensure all fields have non-empty defaults if parametrized tests override individual fields. String annotations and `from __future__ import annotations` enable Literal and forward references without runtime overhead. For JSONL records, add new fields as optional with sensible defaults; existing consumers tolerate extra keys automatically. Legacy records without new fields remain valid via fallback logic.
