# Auto-Agent — Default Playbook

{{> _envelope.md}}

## Default sub-label guidance

You're picking up an escalation that doesn't have a specialized playbook. Read
the escalation context (if present), look at what was attempted in previous
attempts, and try the obvious recovery action for whatever phase produced this
escalation.

If the context indicates a CI failure, look at the failing test output, fix the
test or the production code, and push.

If the context indicates a phase failure (review, plan, implement), read what
the phase tried, understand why it failed, and either: (a) make the small
correction the phase needed, or (b) escalate with a specific recommendation.

When in doubt, escalate cleanly with a specific question. A two-sentence
diagnosis a human can act on is more valuable than a sloppy half-fix.
