---
source: feedback_skip_adr_after_open_needs_retrigger.md
name: Skip-ADR added after PR open requires empty-commit retrigger
description: The ADR gate workflow reads github.event.pull_request.body at PR-open/sync time — appending Skip-ADR to body via `gh pr edit` doesn't re-run the gate; you need a new commit to trigger CI
status: wontfix
issue: null
promoted_in: null
wontfix_reason: Skip-ADR convention deleted in ADR-0056 (2026-05-06); memory describes obsolete behavior
created: '2026-05-02'
---

The ADR-gate GitHub Actions workflow uses `${{ github.event.pull_request.body }}` to check for the `Skip-ADR:` marker. This value is captured at PR open / synchronize time. **Editing the PR body via `gh pr edit --body ...` does NOT re-run the workflow.**

**Why:** Hit this on PR #8451 (sandbox-tier PR A), PR #8454 (contract_recording fix), and PR #8463 (hotfix). Each time the implementer remembered to add Skip-ADR after PR open, the gate was already FAILED on the first run with the original body. Subsequent runs couldn't see the updated body — only a new commit would re-trigger.

**How to apply:**
- **Best:** Include `Skip-ADR: <reason>` in the PR body at `gh pr create` time. Easier to remember than retrying.
- If you forget: append Skip-ADR via `gh pr edit`, then push an empty commit:
  ```bash
  gh pr edit <N> --body "$(gh pr view <N> --json body --jq .body)\n\nSkip-ADR: <reason>"
  git commit --allow-empty -m "ci: re-trigger ADR-gate after Skip-ADR annotation"
  git push
  ```
- The empty commit triggers a new `synchronize` event, which captures the updated body.
- Note: GitHub treats the failed-then-passed runs as "still has a failed run on record" — `mergeStateStatus` may stay `UNSTABLE`/`DIRTY`. The empty commit creates a fresh CI run that supersedes the old one.
