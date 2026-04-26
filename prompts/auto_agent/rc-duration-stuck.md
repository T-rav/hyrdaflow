# Auto-Agent — rc-duration-stuck Playbook

{{> _envelope.md}}

## Sub-label: rc-duration-stuck

Release-critical work is taking too long. Look at what's blocking — usually a
single PR. Comment on that PR with a specific unblock action; if it's a code
issue, propose a patch.

## Specific guidance

The RC-budget loop detected that release-critical work has exceeded its time
allotment. Find the blocker and act.

Order of operations:

1. Read the RC budget context (escalation context will show the spend metrics
   and the most likely culprit PR).
2. Open the culprit PR. What's blocking it — failing CI, no review, merge
   conflict, scope creep?
3. Take the smallest action that unblocks: post a specific review comment,
   propose a patch, or escalate with "need owner X to review."
4. If you propose a patch, open a small PR against the culprit branch.

Don't try to "fix" RC budget by changing the budget — that's the operator's
call. Your job is to remove the friction on whatever is in flight.
