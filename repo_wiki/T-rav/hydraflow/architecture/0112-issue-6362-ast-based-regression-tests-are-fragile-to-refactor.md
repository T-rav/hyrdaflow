---
id: 0112
topic: architecture
source_issue: 6362
source_phase: plan
created_at: 2026-04-10T07:44:23.400467+00:00
status: active
---

# AST-based regression tests are fragile to refactoring

Tests that walk the AST looking for specific function/variable names and nesting patterns break if code is renamed, wrapped, or restructured. Keep cleanup calls simple and direct—no indirection, no renaming, no extra nesting. Fragility is the cost of catching accidental refactorings.
