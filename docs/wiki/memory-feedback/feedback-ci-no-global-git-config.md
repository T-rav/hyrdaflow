---
source: feedback_ci_no_global_git_config.md
name: CI has no global git config — fixtures must persist identity
description: GitHub Actions runners have no global git user.email/user.name. Tests
  that run real `git commit` without explicit `-c user.*` overrides must persist identity
  in the repo-local config via `git config`.
status: issue-open
issue: 28
promoted_in: null
wontfix_reason: null
created: '2026-04-21'
---

Tests that exercise "ambient git config fallback" behavior (e.g., helpers that intentionally omit `-c user.email` / `-c user.name` so git uses its fallback chain) fail on GitHub Actions with `Author identity unknown` — the runner has no global config.

**Why:** PR #8354 added tests that called `open_automated_pr_async(commit_author_name="", commit_author_email="")` to verify the fallback path. Locally they passed because the developer's global `~/.gitconfig` supplied identity. CI had nothing, so `git commit` failed with the exact error the code path is meant to avoid.

**How to apply:** In any pytest fixture that sets up a git repo used by code that may commit without explicit `-c` overrides, run `git -C <repo> config user.email <x>` and `git -C <repo> config user.name <y>` once at setup — do NOT rely solely on inline `-c user.email=...` on a specific commit, since that doesn't persist for subsequent commits (including commits made in worktrees derived from that repo). Worktrees inherit the repo's common `.git/config`, so persisting once covers all downstream commits.
