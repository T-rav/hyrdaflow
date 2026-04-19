---
id: 0092
topic: architecture
source_issue: 6349
source_phase: plan
created_at: 2026-04-10T06:47:04.972424+00:00
status: active
---

# Structured transcript parsing: markers, summaries, and item lists

Transcripts can be parsed via three markers: result key (OK/RETRY status), summary section (captured text), and item list (extracted from bullet points). Case-insensitive matching and whitespace-tolerant list parsing make this pattern robust across variations in formatting and capitalization.
