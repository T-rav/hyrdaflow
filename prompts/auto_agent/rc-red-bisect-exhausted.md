# Auto-Agent — rc-red-bisect-exhausted Playbook

{{> _envelope.md}}

## Sub-label: rc-red-bisect-exhausted

Same family as revert-conflict. Specific guidance on what bisect output reveals.

## Specific guidance

The bisect loop ran out of attempts. The escalation context will show what was
tried — typically: revert candidate A, conflict; revert candidate B, conflict;
verify timeout.

Read the bisect log. If two consecutive reverts both conflict, the right move
is usually to revert further back (a parent commit of both candidates) to clear
the conflict surface. If verify keeps timing out, the issue may be a long-lived
test rather than a culprit at all — in that case, escalate with the diagnosis.

Don't try to fix the bug. Land a clean revert or escalate with the bisect map.
