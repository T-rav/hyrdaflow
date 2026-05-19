# Auto-Agent — triage-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: triage-stuck

The triage runner parked this issue with a `parking_reason` (visible in the
escalation context). No loop currently re-attempts triage on parked issues
(that gap is W2 of ADR-0063); preflight is the first re-entry point.

## Specific guidance

Order of operations:

1. Read the `parking_reason` (in escalation context). It will be one of:
   - `under_specified` — issue body doesn't include enough to triage.
   - `unknown_domain` — issue references a system the triage runner has no
     prior label for.
   - `dependency_conflict` — issue depends on another issue not yet closed.
2. For `under_specified` issues: scan the issue body + comments for any
   recoverable signal (referenced file, error message, sentry event). If
   you find one, post a one-line clarification comment ("auto-triaged as
   `<labels>` based on referenced file `<path>`") and apply the label
   set yourself. Return `resolved`.
3. For `unknown_domain` issues: read the wiki (`docs/wiki/`) for any module
   matching keywords in the issue body. If a match exists, apply
   `area:<module>` plus the most-likely lifecycle label. Return `resolved`.
4. For `dependency_conflict` issues: confirm the blocking issue is still
   open. If closed, re-trigger triage with the dependency-cleared signal
   (post a comment). If still open, return `needs_human` with the explicit
   dependency chain — don't unblock prematurely.

Do NOT:
- Apply broad catchall labels like `bug` or `enhancement` without a specific
  scope signal. The triage runner already rejected the issue once for being
  under-specified; the auto-agent should be no looser.
- Re-open closed issues.
- Modify the triage runner itself — that's covered by the deny-list and
  recursion guard.
