# ADR-0003: Git Worktrees for Issue Isolation

**Status:** Accepted
**Date:** 2026-02-26

## Context

Each issue is implemented by an agent that writes code, runs tests, and commits
changes. Multiple issues may be in the implement stage simultaneously. The agent
must not interfere with:
- The primary checkout (used by the orchestrator and planner).
- Other in-flight issue implementations.
- The main branch.

Options:
1. Implement directly on the main checkout (one at a time).
2. Clone the repository per issue.
3. Use `git worktree` to create lightweight linked checkouts.

## Decision

Use `git worktree add` to create an isolated working tree per issue at
`../hydraflow-worktrees/issue-{number}/`. Each worktree:
- Shares the git object store with the primary repo (no full clone overhead).
- Has its own working directory and `HEAD` (pointing to a dedicated branch).
- Gets an independent Python venv (`uv sync`), symlinked `.env`, and pre-commit
  hooks installed.
- Is destroyed after the PR is merged or the issue is closed.

The worktree base path is configurable via `worktree_base` in `HydraFlowConfig`.
Default is a sibling directory to the repo root (e.g., `../hydraflow-worktrees/`).

## Consequences

**Positive:**
- True filesystem isolation: agent writes to a completely separate directory tree.
- Lightweight: git worktrees share object storage; no redundant `.git` packing.
- Parallelism: `max_implementers` worktrees can exist simultaneously with no
  contention.
- Branch-per-issue: each worktree has its own branch, making PRs and code review
  natural.
- CI/quality gates run in the worktree context, not the primary repo.

**Negative / Trade-offs:**
- Worktrees must be cleaned up explicitly. Stale worktrees from abandoned issues
  accumulate disk space. `make clean` removes all worktrees; `git worktree prune`
  removes orphaned metadata.
- The `../hydraflow-worktrees/` convention means HydraFlow expects write access to
  the parent directory of the repo root.
- Long-running implementations hold open file handles in the worktree, which
  prevents `git worktree remove` from succeeding mid-run.
- Docker mode requires additional setup to mount the worktree path into the
  container.

## Related

- `src/worktree.py:WorktreeManager` — full lifecycle implementation
- `src/ports.py:WorktreePort` — formal interface
- `CLAUDE.md` — "Always implement issue work on a dedicated git worktree branch"
- ADR-0001 for the concurrency model that makes parallel worktrees necessary
