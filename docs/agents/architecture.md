# Architecture

HydraFlow runs five concurrent async loops from `src/orchestrator.py`:

1. **Triage loop** — Fetches new issues, scores complexity, classifies type, and applies the `hydraflow-plan` label.
2. **Plan loop** — Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.
3. **Implement loop** — Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents, pushes branches, creates PRs, then swaps to `hydraflow-review`.
4. **Review loop** — Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.
5. **HITL loop** — Processes issues labeled `hydraflow-hitl` that need human-in-the-loop correction.

For the authoritative design rationale, see [`docs/adr/0001-five-concurrent-async-loops.md`](../adr/0001-five-concurrent-async-loops.md) and [`docs/adr/0002-labels-as-state-machine.md`](../adr/0002-labels-as-state-machine.md).

## Key Files

### Core infrastructure
- `src/server.py` — Server entry point (`python -m server`)
- `scripts/run_admin_task.py` — Admin task runner (clean, prep, scaffold, ensure-labels)
- `src/orchestrator.py` — Main coordinator (five async polling loops)
- `src/config.py` — `HydraFlowConfig` Pydantic model (50+ env-var overrides)
- `src/models.py` — Pydantic data models (Phase, SessionLog, ReviewResult, etc.)
- `src/service_registry.py` — Composition root (`build_services()`); imports from all layers to wire dependencies
- `src/state.py` — `StateTracker` (JSON-backed crash recovery)
- `src/events.py` — `EventBus` async pub/sub

### Phase implementations
- `src/plan_phase.py` / `src/implement_phase.py` / `src/review_phase.py` / `src/triage_phase.py` / `src/hitl_phase.py`
- `src/phase_utils.py` — Shared phase utilities
- `src/pr_unsticker.py` — Stale PR recovery coordinator

### Agents and runners
- `src/agent.py` — `AgentRunner` (implementation agent)
- `src/planner.py` — `PlannerRunner` (read-only planning agent)
- `src/reviewer.py` — `ReviewRunner` (review + CI fix agent)
- `src/hitl_runner.py` — HITL correction agent
- `src/base_runner.py` — Base runner class

### Git and PR management
- `src/worktree.py` — `WorktreeManager` (git worktree lifecycle) — see [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md)
- `src/pr_manager.py` — `PRManager` (all `gh` CLI operations)
- `src/merge_conflict_resolver.py` — Merge conflict resolution
- `src/post_merge_handler.py` — Post-merge cleanup

### Background loops
- `src/base_background_loop.py` — Base async loop pattern — see [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md)
- `src/manifest_refresh_loop.py` / `src/memory_sync_loop.py` / `src/metrics_sync_loop.py` / `src/pr_unsticker_loop.py` — workers

### Dashboard
- `src/dashboard.py` + `src/dashboard_routes/` — FastAPI + WebSocket backend
- `ui/` — React + Vite frontend — see [`ui-standards.md`](ui-standards.md)

### Repo scaffolding (prep system)
- `src/prep.py` — Repository preparation orchestrator
- `src/ci_scaffold.py` / `src/lint_scaffold.py` / `src/test_scaffold.py` / `src/makefile_scaffold.py`
- `src/polyglot_prep.py` — Language detection

### Persistence
Per-repo state layout is documented in [`docs/adr/0021-persistence-architecture-and-data-layout.md`](../adr/0021-persistence-architecture-and-data-layout.md). Per-target-repo LLM knowledge base: [`src/repo_wiki.py`](../../src/repo_wiki.py) — see [`docs/adr/0032-per-repo-wiki-knowledge-base.md`](../adr/0032-per-repo-wiki-knowledge-base.md).

## Tech stack

- **Python 3.11** with Pydantic, asyncio
- **FastAPI + WebSocket** for dashboard
- **React + Vite** for dashboard UI
- **Ruff** for linting and formatting
- **Pyright** for type checking
- **Bandit** for security scanning
- **pytest + pytest-asyncio + pytest-xdist** for testing
- **uv** for dependency management
