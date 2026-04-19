---
id: 0001
topic: dependencies
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T06:57:24.154748+00:00
status: active
---

# Circular Dependencies & Import Management

Use TYPE_CHECKING guards and deferred imports (PEP 563) to break circular dependencies at the import level. For runtime circular references between extracted classes, inject callback functions instead of class references (e.g., `get_progress=epic_reporter.get_progress`) to avoid circular imports and make dependency direction explicit in constructor signatures.

Manage optional dependencies through three-level degradation, structural typing with Protocols, and explicit API composition via optional parameters. When a helper feeds data into a pipeline (e.g., memory injection), wrap the entire body in `except Exception: # noqa: BLE001` with no re-raise—return a safe default instead. Failures in optional data collection must not interrupt the pipeline itself; this is especially important for optional features like Hindsight recall that degrade gracefully. Use modern generic syntax with `from __future__ import annotations` on Python 3.9+.

When extracting multiple coordinators from a god class, identify those with zero cross-dependencies and extract in parallel phases. Dependencies between extracted classes (e.g., 'ReviewVerdictHandler uses CIFixCoordinator') create phase ordering constraints. Map this as a task graph to prevent parallel work from being blocked.

After extracting duplicated code and removing unused imports, verify extraction completeness through two-stage verification: (1) check function signatures, return type hints, and other locations across the file to confirm imports are truly unused; (2) use targeted grep across the codebase for old names in imports, documentation, comments, dynamic imports, and test fixtures to prevent false positives. Deferred imports become cleanup signals when removing code—look for these as dead code markers.

Apply the single update point pattern: define artifacts once and import everywhere to prevent divergence. For FastAPI, register catch-all `/{path:path}` route last.

See also: Type Signatures as Backward-Compatibility Contracts — for communicating contract changes before implementation changes.
