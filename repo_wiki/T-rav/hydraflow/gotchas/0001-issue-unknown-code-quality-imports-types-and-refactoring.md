---
id: 0001
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674355+00:00
status: active
---

# Code Quality, Imports, Types, and Refactoring

Verify imports are present and not circular before adding type annotations. Use TYPE_CHECKING guards with `from __future__ import annotations` for forward references. Before removing imports, grep for runtime references (isinstance, assignments) to prevent NameError. Run ruff to auto-fix import ordering.

Import ordering follows isort rules: stdlib (alphabetically, including pathlib), then third-party, then local. Use `is None` and `is not None` for optional objects, especially callables and stores. Type ignore comments can hide real bugs—investigate before suppressing.

Protocol conformance: method signatures must exactly match protocol definitions. When updating port signatures, sync all implementations simultaneously—one task, not staggered. When refactoring classes, enforce acceptance criteria of ≤400 lines and ≤15 public methods. Count carefully: remaining non-delegated methods + delegation stubs can exceed budget even after extraction.

Preserve edge cases like label ordering and removal order semantics. When removing multiple code blocks from same file, delete bottom-to-top (highest line numbers first) to avoid line-number shifting.

See also: Testing — validate type changes with ruff and typecheck; Infrastructure — type-checking applies to parser signatures.
