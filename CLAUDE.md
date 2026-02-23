# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

## Architecture

HydraFlow runs three concurrent async loops:

1. **Plan loop**: Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.
2. **Implement loop**: Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents with TDD prompts, pushes branches, creates PRs, then swaps to `hydraflow-review`.
3. **Review loop**: Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.

### Key Files

- `cli.py` — CLI entry point
- `orchestrator.py` — Main coordinator (three async polling loops)
- `config.py` — `HydraFlowConfig` Pydantic model
- `agent.py` — `AgentRunner` (implementation agent)
- `planner.py` — `PlannerRunner` (read-only planning agent)
- `reviewer.py` — `ReviewRunner` (review + CI fix agent)
- `worktree.py` — `WorktreeManager` (git worktree lifecycle)
- `pr_manager.py` — `PRManager` (all `gh` CLI operations)
- `dashboard.py` — FastAPI + WebSocket live dashboard
- `events.py` — `EventBus` async pub/sub
- `state.py` — `StateTracker` (JSON-backed crash recovery)
- `models.py` — Pydantic data models
- `stream_parser.py` — Claude CLI stream-json parser
- `ui/` — React dashboard frontend

## Testing is Mandatory

**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.

- New features: Write tests BEFORE committing
- Bug fixes: Add regression tests that reproduce the bug
- Refactoring: Ensure existing tests pass, add tests for new paths
- Never commit untested code

## Never Skip Commit Hooks

**NEVER** use `git commit --no-verify` or `--no-hooks` flags. Always fix code issues first.

## Development Commands

```bash
make run            # Start backend + Vite frontend dev server
make dry-run        # Dry run (log actions without executing)
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
make test           # Run unit tests (parallel)
make test-cov       # Run tests with coverage report
make lint           # Auto-fix linting
make lint-check     # Check linting (no fix)
make typecheck      # Run Pyright type checks
make security       # Run Bandit security scan
make quality        # Lint + typecheck + test (parallel, fast)
make quality-full   # quality + security scan
make setup          # Install git hooks (pre-commit, pre-push)
make ui             # Build React dashboard
make ui-dev         # Start React dashboard dev server
```

### Quick Validation

```bash
# After small changes
make lint && make test

# Before committing
make quality
```

## Tech Stack

- **Python 3.11** with Pydantic, asyncio
- **FastAPI + WebSocket** for dashboard
- **React + Vite** for dashboard UI
- **Ruff** for linting/formatting
- **Pyright** for type checking
- **Bandit** for security scanning
- **pytest + pytest-asyncio** for testing

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
