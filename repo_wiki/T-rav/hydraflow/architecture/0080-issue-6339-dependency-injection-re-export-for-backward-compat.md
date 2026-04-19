---
id: 0080
topic: architecture
source_issue: 6339
source_phase: plan
created_at: 2026-04-10T06:19:03.788137+00:00
status: active
---

# Dependency injection + re-export for backward-compatible class splits

When splitting a large class into focused subclasses, inject the new dependencies into the parent constructor and re-export the new classes from the original module. This maintains API compatibility (`from epic import EpicStatusReporter` works) while separating concerns. Wiring happens in `ServiceRegistry`, not in the class constructors.
