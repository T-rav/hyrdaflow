---
id: 0005
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849534+00:00
status: active
---

# Backward Compatibility and Refactoring via Facades and Re-Exports

When splitting large classes or moving code, preserve backward compatibility using three strategies: (1) **Re-exports**: move implementation to canonical location, re-export from original module, ensuring `isinstance()` checks and existing imports work unchanged. Test re-exports with identity checks (`assert Class1 is Class2`). (2) **Optional parameters with None defaults**: add new functionality as optional kwargs, allowing callers to omit them with fallback behavior matching the old implementation. (3) **Facade + composition for large classes**: when splitting classes with 20+ importing modules and 50+ test mock targets, keep delegation stubs on original class so all existing import paths, isinstance checks, and mock targets continue working. Extract to sub-clients inheriting a shared base class. Fix encapsulation violations by defining proper public API methods on the base class. These patterns enable incremental migration and prevent breaking 40+ existing import sites across the codebase. See also: Consolidation Patterns for handling multiple refactoring scenarios.
