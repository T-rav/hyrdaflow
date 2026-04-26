# Auto-Agent — trust-loop-anomaly Playbook

{{> _envelope.md}}

## Sub-label: trust-loop-anomaly

A trust-fleet anomaly fired. Read the anomaly type, the loop's recent telemetry.
Most anomalies are runtime drift, not bugs — propose a config tune or note that
the anomaly is expected. Don't modify the loop code itself.

## Specific guidance

The trust-fleet sanity loop detected one of: issues-per-hour spike, repair
failure ratio, tick error ratio, staleness, or cost spike.

Order of operations:

1. Read the anomaly type from the escalation context. Each anomaly type has a
   different "is this real" check:
   - **issues-per-hour:** is there a real burst (incident, deploy)? Note it
     and close. Otherwise: tighten dedup or escalate to operator.
   - **repair ratio:** the loop is trying things that don't work. Read recent
     repair attempts; the diagnosis usually surfaces a wrong assumption.
   - **tick error ratio:** the loop is crashing. Read the Sentry trace.
   - **staleness:** the loop is hung. Read the heartbeat history.
   - **cost spike:** check for runaway prompt or unexpected workload.
2. Most resolutions are: post a comment with the diagnosis + propose a config
   tune (interval, threshold), then return `resolved`.
3. Modify the loop's CODE only if the diagnosis is a clear bug AND the fix is
   small. Otherwise escalate with the diagnosis for the operator.

You may NOT modify `src/trust_fleet_sanity_loop.py` itself, or any of the
ten trust loops, beyond the operator-tunable config knobs. The recursion guard
is enforced at the tool layer.
