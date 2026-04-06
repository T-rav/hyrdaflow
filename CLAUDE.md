# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

## Architecture

HydraFlow runs five concurrent async loops from `orchestrator.py`:

1. **Triage loop**: Fetches new issues, scores complexity, classifies type, and applies the `hydraflow-plan` label.
2. **Plan loop**: Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.
3. **Implement loop**: Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents, pushes branches, creates PRs, then swaps to `hydraflow-review`.
4. **Review loop**: Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.
5. **HITL loop**: Processes issues labeled `hydraflow-hitl` that need human-in-the-loop correction.

### Key Files

**Core infrastructure:**
- `server.py` — Server entry point (`python -m server`)
- `scripts/run_admin_task.py` — Admin task runner (clean, prep, scaffold, ensure-labels)
- `orchestrator.py` — Main coordinator (five async polling loops)
- `config.py` — `HydraFlowConfig` Pydantic model (50+ env-var overrides)
- `models.py` — Pydantic data models (Phase, SessionLog, ReviewResult, etc.)
- `service_registry.py` — Dependency injection factory (`build_services()`)
- `state.py` — `StateTracker` (JSON-backed crash recovery)
- `events.py` — `EventBus` async pub/sub

**Phase implementations:**
- `plan_phase.py` / `implement_phase.py` / `review_phase.py` / `triage_phase.py` / `hitl_phase.py`
- `phase_utils.py` — Shared phase utilities
- `pr_unsticker.py` — Stale PR recovery coordinator

**Agents/runners:**
- `agent.py` — `AgentRunner` (implementation agent)
- `planner.py` — `PlannerRunner` (read-only planning agent)
- `reviewer.py` — `ReviewRunner` (review + CI fix agent)
- `hitl_runner.py` — HITL correction agent
- `base_runner.py` — Base runner class

**Git & PR management:**
- `worktree.py` — `WorktreeManager` (git worktree lifecycle)
- `pr_manager.py` — `PRManager` (all `gh` CLI operations)
- `merge_conflict_resolver.py` — Merge conflict resolution
- `post_merge_handler.py` — Post-merge cleanup

**Background loops:**
- `base_background_loop.py` — Base async loop pattern
- `manifest_refresh_loop.py` / `memory_sync_loop.py` / `metrics_sync_loop.py` / `pr_unsticker_loop.py`

**Dashboard:**
- `dashboard.py` + `dashboard_routes.py` — FastAPI + WebSocket backend
- `ui/` — React + Vite frontend

**Repo scaffolding (prep system):**
- `prep.py` — Repository preparation orchestrator
- `ci_scaffold.py` / `lint_scaffold.py` / `test_scaffold.py` / `makefile_scaffold.py`
- `polyglot_prep.py` — Language detection

## Worktree Management

HydraFlow creates isolated git worktrees for each issue. **Always clean up worktrees when their PRs are merged or issues are closed. Always implement issue work on a dedicated git worktree branch; do not implement directly in the primary repo checkout.**

**CRITICAL: The `main` branch is protected. Direct commits and pushes to `main` will be rejected.** All code changes — including one-line fixes — MUST go through a worktree branch and a pull request. Never stage, commit, or modify files in the primary repo checkout.

**Workflow for every code change:**
1. Create a worktree: `git worktree add ../hydraflow-worktrees/<name> origin/main`
2. Create a branch in the worktree: `git checkout -b <branch-name> origin/main`
3. Make changes, commit, and push the branch
4. Create a PR via `gh pr create`
5. Clean up: `git worktree remove ../hydraflow-worktrees/<name>`

**Do NOT use `EnterWorktree` tool** — it auto-cleans up and loses work. Use manual `git worktree add` commands.

- **Default location:** `../hydraflow-worktrees/` (sibling to repo root)
- **Naming:** `issue-{issue_number}/` for issue work, descriptive names for other changes
- **Config:** `worktree_base` field in `HydraFlowConfig`
- **Cleanup:** `make clean` removes all worktrees and state
- Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks
- Stale worktrees from merged PRs should be periodically pruned with `git worktree prune`

## Testing is Mandatory

**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.

- Tests live in `tests/` following the pattern `tests/test_<module>.py`
- New features: Write tests BEFORE committing
- Bug fixes: Add regression tests that reproduce the bug
- Refactoring: Ensure existing tests pass, add tests for new paths
- Never commit untested code
- Coverage threshold: 70%
- **Never write tests for ADR markdown content.** ADRs are documentation, not code. Do not create `test_adr_NNNN_*.py` files that assert on markdown headings, status fields, or prose content — these break whenever the document is edited and provide no value. Only test ADR-related *code* (e.g., `test_adr_reviewer.py` tests the reviewer logic).
- **Never include line numbers in ADR source citations.** Throughout ADR documents (Related, Context, Decision, Consequences sections), cite source files by function or class name only (e.g., `src/config.py:_resolve_base_paths`). Do NOT add `(line 42)` or similar anywhere — line numbers drift as the source file is edited and council reviews will flag them as stale.

## Avoided Patterns

Common mistakes agents make in this codebase — avoid these:

- **Adding a Pydantic model field without updating serialization tests.** When you add a field to any model in `models.py` (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update ALL exact-match serialization tests (`model_dump()` assertions, expected key sets in smoke tests).
- **Top-level imports of optional dependencies in test files.** Never `from hindsight import Bank` at module level in tests — `httpx` is not always available. Use deferred imports inside test methods: `from hindsight import Bank`.
- **Spawning background sleep loops to poll for results.** Never `sleep(N)` in a loop waiting for a test suite or background process. Use `run_in_background` with a single command, or run in foreground.
- **Mocking at the wrong level.** Patch functions at their *import site*, not their *definition site*. If `base_runner.py` does `from hindsight import recall_safe`, patch `hindsight.recall_safe` (the definition module), not `base_runner.recall_safe`.
- **Using `not obj` instead of `obj is None` for optional dependencies.** Falsy checks on optional objects (e.g., `not self._hindsight`) can trigger incorrectly with mock objects. Use `self._hindsight is None` for explicit null checks.

## Reasoning Triggers

For analysis-heavy tasks (architecture decisions, debugging, code review), use explicit reasoning prompts to trigger deeper analysis:

- "Think through the tradeoffs of this approach before implementing"
- "Consider what could go wrong and what edge cases exist"
- "Explain your reasoning before making changes"

Simple mechanical tasks (rename, format, move) don't need these — just do them.

## Quality Before Completion

**Always run lint and tests before declaring work complete or committing.** Do not present implementation as "done" until quality checks pass.

1. After each significant code change: `make lint` (auto-fixes formatting and imports)
2. Before committing: `make quality` (lint + typecheck + security + tests in parallel)
3. If lint auto-fixes files, re-check for type errors introduced by removed imports
4. Track your edits across files — avoid creating duplicate helpers or inconsistent naming when refactoring multiple test files
5. Merge consecutive identical if-conditions so the shared guard is evaluated once. When you see redundant chains like `if A and B: ... elif A and not B: ...`, restructure them as `if A: if B: ... else: ...` to keep the shared condition centralized and avoid logic drift.

The `/hf.quality-gate` command runs a structured quality check sequence. Use it before presenting work as complete.

## Background Loop Guidelines

When creating a new background loop (`BaseBackgroundLoop` subclass):

1. **Use `make scaffold-loop`** to generate boilerplate — it handles all wiring
2. **Restart safety**: Any `self._` state that affects behavior across cycles must either:
   - Be persisted via `StateTracker` or `DedupStore` (survives restart)
   - Be rehydrated from an external source (GitHub API) on first `_do_work()` cycle
   - Be explicitly documented as ephemeral with `# ephemeral: lost on restart` comment
3. **Wiring checklist** (automated by `tests/test_loop_wiring_completeness.py`):
   - `src/service_registry.py` — dataclass field + `build_services()` instantiation
   - `src/orchestrator.py` — entry in `bg_loop_registry` dict
   - `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`
   - `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`
   - `src/config.py` — interval Field + `_ENV_INT_OVERRIDES` entry

## Never Skip Commit Hooks

**NEVER** use `git commit --no-verify` or `--no-hooks` flags. Always fix code issues first.

## Never Commit to Main

**NEVER** commit directly to `main`. The branch is protected and pushes will be rejected. All changes go through worktree branches and PRs — no exceptions, not even for one-line fixes.

## Development Commands

```bash
make run            # Start backend + Vite frontend dev server
make dry-run        # Dry run (log actions without executing)
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
make test           # Run unit tests (fail-fast)
make test-fast      # Quick test run (-x --tb=short)
make test-cov       # Run tests with coverage report (70% threshold)
make lint           # Auto-fix linting
make lint-check     # Check linting (no fix)
make typecheck      # Run Pyright type checks
make security       # Run Bandit security scan
make layer-check    # Static import-direction checker (layer boundaries)
make quality        # Lint + typecheck + security + test + layer-check (parallel)
make quality-lite   # Lint + typecheck + security (no tests)
make setup          # Install hooks, assets, config, labels
make prep           # Sync agent assets + run full repo prep (labels, audit, CI/tests)
make scaffold       # Generate baseline tests and CI configuration only (no asset sync)
make ensure-labels  # Create HydraFlow lifecycle labels
make integration    # Run integration tests
make soak           # Run soak/load tests
make hot            # Send config update to running instance
make ui             # Build React dashboard
make ui-dev         # Start React dashboard dev server
make deps           # Sync dependencies via uv
```

### Quick Validation

```bash
# After small changes
make lint && make test

# Before committing
make quality
```

## Sentry Error Tracking

HydraFlow uses **Sentry** (`sentry_sdk`) for error monitoring. Follow these rules to keep Sentry signal-to-noise high:

### What Goes to Sentry
- **Real code bugs only**: `TypeError`, `KeyError`, `AttributeError`, `ValueError`, `IndexError`, `NotImplementedError`
- The `before_send` filter in `server.py` drops all exceptions that are NOT in the bug-types tuple
- `LoggingIntegration` captures `logger.error()` calls — these also go through the `before_send` filter

### What Does NOT Go to Sentry
- **Transient errors**: network timeouts, auth failures, rate limits, subprocess crashes — these are operational, not bugs
- **Handled exceptions**: if you catch an error and handle it, use `logger.warning()` not `logger.error()` / `logger.exception()`
- **Test mock exceptions**: never let test mocks raise through code paths that log at `error` level when `SENTRY_DSN` is set

### Rules for New Code
1. Use `logger.warning()` for expected/transient failures (network, auth, rate limit)
2. Use `logger.error()` or `logger.exception()` ONLY for unexpected code bugs you want Sentry to capture
3. Never use bare `except: pass` — always log at `warning` level minimum
4. When adding a new background loop, catch operational errors and log at `warning`; let real bugs propagate to the base class error handler which logs at `error`
5. The `_before_send` callback in `server.py` is the gatekeeper — if you add new exception types that indicate real bugs, add them to `_BUG_TYPES`
6. The `SentryIngestLoop` in `sentry_loop.py` polls Sentry for unresolved issues and files them as GitHub issues — avoid creating noise that feeds back into this loop

### Key Files
- `src/server.py` — Sentry init, `_before_send` filter, `_BUG_TYPES` tuple
- `src/sentry_loop.py` — Background loop that ingests Sentry issues into GitHub

## Tech Stack

- **Python 3.11** with Pydantic, asyncio
- **FastAPI + WebSocket** for dashboard
- **React + Vite** for dashboard UI
- **Ruff** for linting/formatting
- **Pyright** for type checking
- **Bandit** for security scanning
- **pytest + pytest-asyncio + pytest-xdist** for testing
- **uv** for dependency management

## UI Development Standards

The React dashboard (`ui/`) uses inline styles in JSX. Follow these conventions.

### Layout
- **CSS Grid** for page-level layout (`App.jsx`), **Flexbox** for component internals
- Sidebar is fixed at `280px`; set `flexShrink: 0` on fixed-width panels/connectors
- Set `minWidth` on containers to prevent content overlap at narrow viewports

### DRY Principle
- Shared constants (`ACTIVE_STATUSES`, `PIPELINE_STAGES`) live in `ui/src/constants.js` — never duplicate
- Type definitions in `ui/src/types.js`
- Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js` — always use `theme.*` tokens, never raw hex/rgb values
- Extract shared styles to reusable objects when used 3+ times

### Style Consistency
- Define `const styles = {}` at file bottom; pre-compute variants (active/inactive, lit/dim) outside the component to avoid object spread in render loops (see `Header.jsx` `pillStyles`)
- Spacing scale: multiples of 4px (4, 8, 12, 16, 20, 24, 32)
- Font size scale: 9, 10, 11, 12, 13, 14, 16, 18
- New colors must be added to both `ui/index.html` `:root` and `ui/src/theme.js`

### Component Patterns
- Check for existing components before creating new ones (pill badges in `Header.jsx`, status badges in `StreamCard.jsx`, tables in `ReviewTable.jsx`)
- Prefer extending existing components over parallel implementations
- Interactive elements need hover/focus states (`cursor: 'pointer'`, `transition`)
- Derive stage-related UI from `PIPELINE_STAGES` in `constants.js`
