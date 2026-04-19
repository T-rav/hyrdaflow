---
id: 0093
topic: architecture
source_issue: 6349
source_phase: plan
created_at: 2026-04-10T06:47:04.972432+00:00
status: active
---

# Separate parsing utilities from subprocess and streaming concerns

Create new utility modules with clear, single responsibilities. Transcript parsing belongs in its own module, distinct from runner_utils which handles subprocess/streaming. This boundary prevents utility modules from becoming dumping grounds and keeps dependencies focused.
