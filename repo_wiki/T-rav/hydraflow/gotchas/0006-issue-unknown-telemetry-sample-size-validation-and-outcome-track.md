---
id: 0006
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674498+00:00
status: active
---

# Telemetry — Sample Size Validation and Outcome Tracking

Minimum sample sizes prevent statistical misleading and enable reliable recommendations. For telemetry, use thresholds like 10 for regressions and window_size for rolling averages; for memory quality assessment, return empty results when recall data is insufficient. Always expose sample_size alongside metrics (fp_rate, recall quality) to flag sparse data—1/2=50% is noisy with high over-interpretation risk.

Record each retry attempt separately to capture timing and retry patterns, but aggregate using (skill_name, issue_number) with only final attempt's outcome for pass-rate calculations. Naive per-attempt counting inflates failure rates. In retry loops with state accumulators, pass current-attempt to telemetry (not accumulator) to avoid contaminating aggregates with stale failure signals from previous attempts.

Outcomes attach to digest snapshots, not individual recalled items. Cap issue_ids per recall hit at 50 entries to bridge outcomes with actual recall events. Blocking skill failures trigger agent retries until they pass, so passed=False records are rare; non-blocking skills are primary false-positive candidates.

See also: Exception Classification — classify failures to distinguish bugs from transient errors.
