---
id: 0001
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849500+00:00
status: active
---

# Deferred Imports, Type Checking, and Testing

Import optional or circular-dependent modules inside function bodies rather than at module level to break circular import chains. Use `from __future__ import annotations` globally to enable TYPE_CHECKING guards for import-time-only types without runtime overhead. Use Protocol types in TYPE_CHECKING blocks while concrete implementations are imported normally. Keep deferred imports inside the specific method that uses them—do not hoist to module level, even if multiple methods use the same import (annotate with `# noqa: PLC0415` to suppress linting). Exception classification functions import specific exception types in the function body to prevent circular imports while keeping type-checking available. In tests, patch at the source module level where the deferred import happens. Use pytest monkeypatch.delitem() with raising=False for sys.modules manipulation to handle both existing and missing keys safely. Never import optional dependencies at test module level; use deferred imports inside test methods. Critical for optional services (hindsight, docker, file_util) and cross-module utilities, avoiding import-time side effects and enabling graceful degradation. See also: Layer Architecture for module organization, Optional Dependencies for service handling.
