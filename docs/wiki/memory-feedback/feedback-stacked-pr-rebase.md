---
source: feedback_stacked_pr_rebase.md
name: Stacked PRs (cut from previous PR's branch) need `git rebase --onto` after parent merges
description: When PR B was branched from PR A's branch (not from main), after PR A merges via squash, rebasing PR B onto fresh main needs `git rebase --onto origin/main <PR_A_TIP>` to skip the now-redundant PR-A commits
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-02'
---

When stacking PRs (cut PR C's branch from PR B's branch instead of from main, e.g. to start work before parent merges), after the parent PR squash-merges, a plain `git rebase origin/main` re-applies the PR-A commits as cherry-picks on top of main — which conflicts because main already has the squashed equivalent.

**Pattern hit during sandbox-tier:** PR C (`sandbox-tier-pr3`) was cut from `sandbox-tier-pr2`. After PR B merged via squash, `git rebase origin/main` failed with conflicts on every PR-B file because git tried to re-apply each PR-B commit on top of the squashed merge.

**Fix:** Use `git rebase --onto`:
```bash
PR_B_TIP=$(git rev-parse <parent-branch>)  # or the SHA before your PR's commits
git rebase --onto origin/main $PR_B_TIP
```

This says "take commits from `$PR_B_TIP..HEAD` (your PR's commits only) and replay them on top of `origin/main`". Skips the parent's commits entirely.

**How to avoid:** Cut new PR branches from `origin/main` whenever possible, even if work in another branch isn't merged yet. Stack only when there's a real dependency (e.g., new code calls a function the parent PR adds). For PRs that touch unrelated files, parallel branches off main are simpler.

**Generated-file conflicts hint:** If the rebase has conflicts only in `docs/arch/generated/*` files, use `git rebase -X theirs origin/main` then run `make arch-regen` after — those files are auto-regenerated and the conflict markers are noise.
