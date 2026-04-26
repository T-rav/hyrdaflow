# Auto-Agent — fake-drift-stuck Playbook

{{> _envelope.md}}

## Sub-label: fake-drift-stuck

An adapter cassette has drifted. Re-record from a real fixture if available,
otherwise update the fake to match observed behavior + leave a comment
explaining the drift.

## Specific guidance

The contract-refresh loop detected that a fake adapter's recorded responses no
longer match the real adapter's behavior. Either the third-party API changed,
or our fake calcified.

Order of operations:

1. Read the contract test that's failing — it tells you which fixture drifted.
2. If the upstream service has a sandbox/staging endpoint, re-record from real
   traffic. Otherwise, update the fake to match the new shape.
3. Add an inline comment in the fake noting WHEN the drift was observed (date)
   and WHY (one-line explanation if known).
4. Run the contract tests and confirm green.

Don't update fakes silently. The comment is the audit trail.
