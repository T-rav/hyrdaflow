# Worktrees and Branch Protection

HydraFlow creates isolated git worktrees for each issue. **Always clean up worktrees when their PRs are merged or issues are closed. Always implement issue work on a dedicated git worktree branch; do not implement directly in the primary repo checkout.**

> **CRITICAL:** The `main` branch is protected. Direct commits and pushes to `main` will be rejected. All code changes — including one-line fixes — MUST go through a worktree branch and a pull request. Never stage, commit, or modify files in the primary repo checkout. No exceptions.

Design rationale: [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md) and [`docs/adr/0010-worktree-and-path-isolation.md`](../adr/0010-worktree-and-path-isolation.md).

## Workflow for every code change

1. Create a worktree: `git worktree add ../hydraflow-worktrees/<name> origin/main`
2. Create a branch in the worktree: `git checkout -b <branch-name> origin/main`
3. Make changes, commit, and push the branch
4. Create a PR via `gh pr create`
5. Clean up: `git worktree remove ../hydraflow-worktrees/<name>`

**Do NOT use the `EnterWorktree` tool** — it auto-cleans up and loses work. Use manual `git worktree add` commands.

## Conventions

- **Default location:** `../hydraflow-worktrees/` (sibling to repo root)
- **Naming:** `issue-{issue_number}/` for issue work, descriptive names for other changes
- **Config:** `worktree_base` field in `HydraFlowConfig` (`src/config.py`)
- **Cleanup:** `make clean` removes all worktrees and state
- Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks
- Stale worktrees from merged PRs should be periodically pruned with `git worktree prune`

## Never skip commit hooks

**NEVER** use `git commit --no-verify` or `--no-hooks` flags. If a hook fails, investigate and fix the underlying issue — do not bypass it.
