# Auto-Agent — revert-conflict Playbook

{{> _envelope.md}}

## Sub-label: revert-conflict

You're cleaning up a staging revert. Goal: get staging green. Don't try to fix
the underlying bug — just complete the revert cleanly and add a regression test
stub for the next person.

## Specific guidance

The staging-bisect loop tried to revert a culprit PR and hit a merge conflict.
Your job is NOT to debug the original bug; it's to land a clean revert.

Order of operations:

1. Read the escalation context to identify the culprit PR and the conflicting files.
2. Resolve the conflicts by preferring the pre-culprit state of those files.
3. Add a regression test stub (skip-marked, with a TODO comment linking to the
   original issue) so the next engineer knows what to write.
4. Push the revert as a new PR; the bisect loop will pick up from there.

Do NOT attempt to fix the underlying bug. That's a separate issue. Your scope
is "make staging buildable again."
