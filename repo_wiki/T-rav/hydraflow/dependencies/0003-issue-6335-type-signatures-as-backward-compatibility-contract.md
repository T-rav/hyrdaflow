---
id: 0003
topic: dependencies
source_issue: 6335
source_phase: review
created_at: 2026-04-10T06:57:24.154767+00:00
status: active
---

# Type Signatures as Backward-Compatibility Contracts

Update function signatures to reflect new stricter types (e.g., `phase: PipelineStage | Literal[""]`) before modifying callers. Existing call sites with hardcoded string literals continue working via StrEnum coercion, making the signature change the primary integration point. Type signatures communicate contract changes to callers before implementation changes are made.
