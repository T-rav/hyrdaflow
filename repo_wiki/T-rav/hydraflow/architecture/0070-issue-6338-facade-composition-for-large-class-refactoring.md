---
id: 0070
topic: architecture
source_issue: 6338
source_phase: plan
created_at: 2026-04-10T05:56:11.037220+00:00
status: active
---

# Facade + Composition for Large Class Refactoring

When decomposing a large class (e.g., 947 lines, 37 methods) into focused sub-modules, use a facade + composition pattern: keep the original class as a thin public-facing facade with delegation stubs, move implementation to stateless or single-concern sub-modules. This preserves all import paths, isinstance checks, and mock targets, enabling zero-test-breakage refactors. All existing callers continue working unchanged.
