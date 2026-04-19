---
id: 0075
topic: architecture
source_issue: 6336
source_phase: plan
created_at: 2026-04-10T05:57:03.732536+00:00
status: active
---

# Endpoint path preservation enables test reuse across refactors

When refactoring monolithic route handlers into sub-modules, if endpoint paths remain unchanged, existing test files need no modification—they match endpoints by HTTP path, not by internal function structure. This allows high-confidence refactoring with zero test churn, since `make test` validates the entire endpoint surface area automatically.
