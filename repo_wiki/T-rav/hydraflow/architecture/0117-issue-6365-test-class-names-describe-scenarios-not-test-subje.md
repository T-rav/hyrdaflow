---
id: 0117
topic: architecture
source_issue: 6365
source_phase: plan
created_at: 2026-04-10T07:59:04.461043+00:00
status: active
---

# Test class names describe scenarios, not test subjects

Test class names like `TestGCLoopNoCircuitBreaker` describe the scenario being tested (GC loop behavior without circuit breaking) rather than the code under test. When removing a module, check whether test classes with that name actually import or test it, or are simply documenting a test scenario.
