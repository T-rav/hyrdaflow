---
source: feedback_never_commit_main.md
name: Never commit directly to main
description: Main is protected — always use worktree branches and PRs, never commit to main
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-03-27'
---

Never commit directly to main. It has branch protection and pushes will be rejected.

**Why:** Branch protection rules reject direct pushes to main. Committing locally to main creates a diverged state that requires manual cleanup.

**How to apply:** Always create a worktree branch (`git worktree add`) for any code changes, then create a PR. Even one-line fixes must go through a PR.
