---
id: 0042
topic: architecture
source_issue: 6323
source_phase: plan
created_at: 2026-04-10T04:47:03.630689+00:00
status: active
---

# Regex-based test parsing creates hard constraints on source structure

`test_loop_wiring_completeness.py` uses regex to parse `orchestrator.py` source for patterns like `('triage', self._triage_loop)` in loop_factories. Refactoring must preserve both the physical location and format of these definitions in orchestrator.py, not just the functionality. Any change to how loop_factories is defined will break the regex match and cause test failures, making this a critical constraint.
