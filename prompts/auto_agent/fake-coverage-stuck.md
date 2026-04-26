# Auto-Agent — fake-coverage-stuck Playbook

{{> _envelope.md}}

## Sub-label: fake-coverage-stuck

Same family as fake-drift-stuck; focuses on coverage holes specifically.

## Specific guidance

The fake-coverage auditor found that some real-adapter codepaths have no
corresponding fake-adapter coverage. Your job is to add the missing
fake-adapter shape.

Order of operations:

1. Read the fake-coverage report (in escalation context if present, otherwise
   re-run the auditor).
2. For each uncovered codepath, write the minimal fake-adapter response that
   matches the real adapter's contract. Add a contract test asserting the new
   shape.
3. Run `make test-fakes` to confirm new coverage.

Don't add fake responses you can't justify against a real adapter sample.
Better to escalate with "need a sample of the X endpoint" than to fabricate.
