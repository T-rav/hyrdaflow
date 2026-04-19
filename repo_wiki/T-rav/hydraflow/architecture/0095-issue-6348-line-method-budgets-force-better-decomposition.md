---
id: 0095
topic: architecture
source_issue: 6348
source_phase: plan
created_at: 2026-04-10T06:49:24.638893+00:00
status: active
---

# Line/method budgets force better decomposition

Hard constraints (≤200 lines, ~7 public methods per class) push better architectural decisions than soft targets. During this refactor, the large query methods didn't fit in a single 200-line `PRQueryClient`, forcing a split into `PRQueryClient` and `DashboardQueryClient`. The constraint prevented a bloated compromise class and revealed natural subdomain boundaries.
