---
source: feedback_auto_merge_not_enabled.md
name: Auto-merge not enabled on this repo — direct-merge via gh pr merge
description: '`gh pr merge --auto` returns "Auto merge is not allowed for this repository" — use `gh pr merge --squash` directly when CI is green'
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-02'
---

`gh pr merge <N> --auto --squash` fails with `GraphQL: Auto merge is not allowed for this repository (enablePullRequestAutoMerge)` on this repo. Auto-merge isn't enabled at the repo level (would require admin to toggle in GitHub settings).

**How to apply:**
- For autonomous PR shipping, set up a Monitor that polls CI and direct-merges when green:
  ```bash
  Monitor with command:
    while true; do
      s=$(gh pr view N --json state,statusCheckRollup ...)
      pending=$(...); failed=$(...)
      if [ "$pending" = "0" ] && [ "$failed" = "0" ]; then
        gh pr merge N --squash
        break
      fi
      sleep 90
    done
  ```
- Or, when CI is already green, just run `gh pr merge <N> --squash --delete-branch`.
- The `--delete-branch` may fail with "branch used by worktree" — that's local cleanup blockage, not a merge failure. The actual merge succeeds.
- Verify with `gh pr view N --json state,mergedAt` — `state == "MERGED"` + `mergedAt != null` confirms.
