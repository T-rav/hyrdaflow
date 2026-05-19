---
source: feedback_skip_adr_format_must_be_literal.md
name: 'Skip-ADR must be literal `Skip-ADR: <reason>` line, not `## Skip-ADR` heading'
description: ADR gate regex is `^[[:space:]]*Skip-ADR:[[:space:]]*\S+` — requires the literal "Skip-ADR:" prefix on a single line. A markdown heading "## Skip-ADR" followed by a paragraph does NOT match
status: wontfix
issue: null
promoted_in: null
wontfix_reason: Skip-ADR convention deleted in ADR-0056 (2026-05-06); memory describes obsolete behavior
created: '2026-05-02'
---

The ADR gate workflow's bash check is:

```bash
echo "$PR_BODY" | grep -qE '^[[:space:]]*Skip-ADR:[[:space:]]*\S+'
```

The regex requires `Skip-ADR:` followed by whitespace and a non-empty reason on the SAME line.

**What FAILS the gate:**
```markdown
## Skip-ADR

Removing a tactical workaround now that the underlying fix is enforced.
```

**What PASSES the gate:**
```markdown
Skip-ADR: Removing a tactical workaround now that the underlying fix is enforced.
```

**Why:** Hit this on PR #8470 (sandbox carve-out removal). PR body had `## Skip-ADR` markdown heading + paragraph, which the regex rejects. Required an empty commit + body fix to re-trigger.

**How to apply:**
- Always include the literal `Skip-ADR: <reason>` line in the PR body at `gh pr create` time, NOT a markdown heading.
- The line can be at the bottom of the body — just needs to start with optional whitespace then `Skip-ADR:` then the reason on the same line.
- Both PR-body styles work for the gate's regex; the heading style is human-readable but doesn't satisfy the gate.
- Combine with `feedback_skip_adr_after_open_needs_retrigger.md` rule when you need to add Skip-ADR post-open: `gh pr edit --body` + empty commit + `git push`.
