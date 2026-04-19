---
id: 0115
topic: architecture
source_issue: 6363
source_phase: plan
created_at: 2026-04-10T07:48:21.129667+00:00
status: active
---

# exc_info=True parameter preserves full tracebacks at lower levels

logger.warning(..., exc_info=True) captures the full exception traceback in logs (visible in structured logs and observability tools) while downgrading the severity level. This enables post-incident debugging without triggering alerting systems designed for ERROR-level events.
