---
id: 0096
topic: architecture
source_issue: 6348
source_phase: plan
created_at: 2026-04-10T06:49:24.638897+00:00
status: active
---

# Selective EventBus threading by behavioral side effects

Not all sub-clients need the same dependencies. Only sub-clients with behavioral side effects (publishing events: `PRLifecycle`, `IssueClient`, `CIStatusClient`) receive `EventBus` in `__init__`. Pure query clients (`PRQueryClient`, `MetricsClient`) don't. This selective dependency injection pattern avoids threading unnecessary dependencies through constructors and signals intent about what each component does.
