---
id: 0079
topic: architecture
source_issue: 6340
source_phase: plan
created_at: 2026-04-10T06:11:06.699170+00:00
status: active
---

# Document variant patterns; resist premature parameterization

The plan notes that `triage.py` uses a similar memory context pattern but with space separator instead of newline. Rather than force parameterization to handle both, the plan keeps scope narrow and documents the variant for future follow-up. Over-parameterizing early adds complexity without immediate need.
