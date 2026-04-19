---
id: 0034
topic: architecture
source_issue: 6318
source_phase: plan
created_at: 2026-04-10T04:05:05.202950+00:00
status: active
---

# Annotated[str, Validator] pattern for backward-compatible type narrowing

Use `Annotated[str, AfterValidator(...)]` to add runtime validation to string fields while maintaining serialization compatibility. This pattern serializes identically to bare `str` in JSON output, enabling strict validation at construction time without breaking existing JSON schema or client contracts. Useful for retrofitting validation onto existing fields across Pydantic models.
