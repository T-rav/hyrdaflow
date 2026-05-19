---
source: feedback_no_destructive_git.md
name: No destructive git commands
description: Git hooks block destructive commands (reset --hard, push --force, etc.) — never attempt them, ask the user to run manually
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-03-18'
---

Never run destructive git commands — a pre-tool hook blocks them and errors out.

Blocked commands: `git reset --hard`, `git push --force/-f`, `git checkout .`, `git restore .`, `git clean -f`, `git branch -D`.

**Why:** Project has `.claude/hooks/hf.block-destructive-git.sh` that prevents these. The user must run them manually.

**How to apply:** If you accidentally commit to the wrong branch, tell the user the exact command to run instead of attempting it yourself.
