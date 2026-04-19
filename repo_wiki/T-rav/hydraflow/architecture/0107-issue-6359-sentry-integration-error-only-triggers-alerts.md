---
id: 0107
topic: architecture
source_issue: 6359
source_phase: plan
created_at: 2026-04-10T07:33:04.050924+00:00
status: active
---

# Sentry integration: ERROR+ only triggers alerts

LoggingIntegration(event_level=logging.ERROR) in server.py means only ERROR and above are sent to Sentry. WARNING-level records bypass Sentry entirely. Use this configuration pattern to prevent false-positive alerts from transient/handled errors while preserving them in structured logs.
