---
id: 0082
topic: architecture
source_issue: 6341
source_phase: plan
created_at: 2026-04-10T06:22:03.281124+00:00
status: active
---

# Pydantic Field() accepts module-level int constants safely

Pydantic Field(le=...), Field(default=...), and Field(ge=...) accept plain int constants identically to literals. When extracting magic numbers into module-level constants for config classes, substitution is type-correct and requires no Pydantic-specific handling or adaptation.
