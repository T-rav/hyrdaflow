<p align="center">
  <img src="docs/hydraflow-logo-small.png" alt="HydraFlow" width="200">
</p>

<h1 align="center">HydraFlow</h1>

<p align="center">
  Multi-agent orchestration system that automates the full GitHub issue lifecycle using Claude Code. Label an issue, HydraFlow plans it, implements it, opens a PR, reviews it, waits for CI, and auto-merges.
</p>

## What is HydraFlow?

HydraFlow is a multi-agent orchestration system that turns GitHub issues into merged pull requests — autonomously. You label an issue, and HydraFlow's pipeline of specialized AI agents triages it for completeness, explores the codebase to write an implementation plan, generates code with tests in an isolated worktree, reviews its own work for quality, waits for CI, and auto-merges on success. The entire lifecycle is driven by GitHub labels, with a live dashboard for monitoring and a human-in-the-loop escape hatch when things go sideways.

## How It Works

HydraFlow runs four concurrent async loops that continuously poll for labeled issues:

```
hydraflow-find ──> hydraflow-plan ──> hydraflow-ready ──> hydraflow-review ──> hydraflow-fixed
   │               │               │                │
   │  Triage       │  Plan agent   │  Impl agent    │  Review agent
   │  agent        │  explores     │  creates       │  checks quality
   │  evaluates    │  codebase,    │  worktree,     │  submits review,
   │  readiness,   │  posts plan   │  writes code,  │  waits for CI,
   │  promotes     │  as comment   │  pushes PR     │  auto-merges
   │  to plan      │               │                │
   │               │               │                └──> hydraflow-hitl (CI failure)
```

1. **Triage loop** -- Fetches `hydraflow-find` issues, evaluates readiness (title/body quality), promotes qualified issues to `hydraflow-plan`.
2. **Plan loop** -- Fetches `hydraflow-plan` issues, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts it as a comment, swaps label to `hydraflow-ready`.
3. **Implement loop** -- Fetches `hydraflow-ready` issues, creates git worktrees, runs implementation agents with TDD prompts, pushes branches, creates PRs, swaps to `hydraflow-review`.
4. **Review loop** -- Fetches `hydraflow-review` issues, runs a review agent, submits a formal PR review, waits for CI, and auto-merges. CI failures escalate to `hydraflow-hitl` for human intervention.

## Design Philosophy

HydraFlow's pipeline draws from three open-source spec-driven development frameworks. Some patterns are already implemented; others are on the [roadmap](#roadmap).

### [spec-kit](https://github.com/github/spec-kit)

| Pattern | What it is | Why HydraFlow needs it |
|---|---|---|
| Structured plan schemas | Required sections (Files to Modify, Implementation Steps, Testing Strategy, Acceptance Criteria, Key Considerations) | LLMs produce wildly inconsistent plans without structure — some are 2 lines, some are novels. A schema makes plans machine-parseable and consistently actionable. |
| Phase-gate quality checks | Quality gates (lint, typecheck, security, tests) that block code before it ships | Catches bad code early. Without gates, broken implementations waste an entire review cycle before anyone notices. |
| `[NEEDS CLARIFICATION]` markers *(roadmap)* | When the planner is uncertain, it marks ambiguity instead of guessing | LLMs fabricate plausible-sounding answers to ambiguous requirements. Explicit uncertainty markers route unclear issues to humans instead of building the wrong thing. |
| MVP-first task ordering | Tasks ordered so the first user story is completable end-to-end before starting the next | Prevents half-built features spread across multiple files. If the agent runs out of context or fails mid-task, at least one complete feature exists. |
| Constitutional governance *(roadmap)* | Immutable principles file constraining all agent outputs, with agent-proposed amendments | Agents drift without constraints. A shared constitution prevents the planner from planning one way and the implementer from coding another. Self-amendment lets the system improve its own rules. |

### [OpenSpec](https://github.com/Fission-AI/OpenSpec)

| Pattern | What it is | Why HydraFlow needs it |
|---|---|---|
| Delta semantics *(roadmap)* | Each task tagged ADDED/MODIFIED/REMOVED/RENAMED | Replaces fuzzy "file referenced but not modified" heuristics with certain post-implementation verification. An ADDED file that doesn't exist is a guaranteed miss, not a guess. |
| Progressive rigor | Lite plans for bug fixes, full plans for features | A typo fix doesn't need a 6-section plan with Key Considerations. Scale-adaptive planning saves planner tokens and reduces noise. |
| Three-dimensional review | Separate checks for Completeness, Correctness, and Quality | LLM reviewers tend to rubber-stamp. Forcing three explicit dimensions means the reviewer can't skip "did the implementation address ALL requirements?" — the most common silent failure. |
| RFC 2119 keywords *(roadmap)* | MUST/SHOULD/MAY formal requirement language | Makes constitutional principles machine-parseable and unambiguous. "Agents MUST NOT expand scope" is clearer than "agents should try to avoid scope creep." |

### [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)

| Pattern | What it is | Why HydraFlow needs it |
|---|---|---|
| Adversarial review *(roadmap)* | Minimum finding threshold (default 3 issues) before APPROVE is accepted | Without a floor, LLM reviewers approve everything with a generic "looks good." Requiring N findings or explicit justification for each empty category forces genuine code examination. |
| Formalized persona constraints | Explicit behavioral boundaries per agent role | Prevents role bleed — the planner writing code, the implementer creating PRs, the reviewer rubber-stamping. Each agent has a focused prompt with explicit boundaries (e.g., planner is read-only, implementer cannot push). |
| Pre-mortem risk analysis *(roadmap)* | "Assume this plan failed — what went wrong?" added to planner prompt | LLMs are optimistic planners. A pre-mortem surfaces edge cases and risks that the planner would otherwise silently skip. |
| Scope escalation detection *(roadmap)* | Constitutional principle: agents must flag files not in the plan | LLM agents silently expand scope (touching files the plan didn't mention). An explicit "stop and declare" rule catches scope creep during implementation, not after review. |
| Quality fix retry loops | Implementation agents retry `make quality` failures up to N times before escalating | Agents often produce code that fails lint or tests on the first pass. Automated retries fix the majority of issues without human intervention. |

## Prerequisites

- **Python 3.11**
- **[uv](https://docs.astral.sh/uv/)** -- Python package manager
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** -- `claude` must be available on PATH
- **[GitHub CLI](https://cli.github.com/)** -- `gh` must be authenticated (`gh auth login`)
- **Node.js 18+** -- for the dashboard UI (optional)

## Quick Start (Your Own Repo)

### 1. Add HydraFlow as a git submodule

```bash
cd your-project
git submodule add https://github.com/T-rav/hydra.git hydraflow
git submodule update --init
```

### 2. Set up the Python environment

```bash
cd hydraflow
make deps
```

This creates a `.venv/`, installs all dependencies (test, dev, dashboard, docker), and stamps the result so subsequent runs are instant. You can also install manually:

```bash
uv venv .venv --python 3.11
uv pip install -e ".[test,dev,dashboard,docker]" --python .venv/bin/python
```

### 3. Configure environment

```bash
cp .env.example .env
```

The `.env` file is auto-loaded by the Makefile. Defaults are the standard HydraFlow labels — edit only if you need custom label names:

```bash
# .env
HYDRAFLOW_LABEL_FIND=hydraflow-find
HYDRAFLOW_LABEL_PLAN=hydraflow-plan
HYDRAFLOW_LABEL_READY=hydraflow-ready
HYDRAFLOW_LABEL_REVIEW=hydraflow-review
HYDRAFLOW_LABEL_HITL=hydraflow-hitl
HYDRAFLOW_LABEL_HITL_ACTIVE=hydraflow-hitl-active
HYDRAFLOW_LABEL_FIXED=hydraflow-fixed
```

### 4. Create GitHub labels

HydraFlow uses 7 lifecycle labels. Create them in your repo (reads label names from `.env`):

```bash
# From the hydraflow directory (auto-detects your repo from git remote)
make ensure-labels
```

Or set `HYDRAFLOW_GITHUB_REPO` to target a different repo:

```bash
HYDRAFLOW_GITHUB_REPO=owner/other-repo make ensure-labels
```

### 5. Install the slash commands

Copy HydraFlow's Claude Code slash commands into your project so you can use `/gh-issue`, `/audit-tests`, and the other audit commands from Claude Code in your own repo:

```bash
# From your project root
mkdir -p .claude/commands

# Copy the commands you want
cp hydraflow/.claude/commands/gh-issue.md .claude/commands/
cp hydraflow/.claude/commands/audit-tests.md .claude/commands/
cp hydraflow/.claude/commands/audit-integration-tests.md .claude/commands/
cp hydraflow/.claude/commands/audit-hooks.md .claude/commands/
```

These commands auto-detect your repo from `git remote` and default to the `hydraflow-plan` label, so created issues feed directly into HydraFlow's pipeline.

Override the label or repo via environment variables:

```bash
export HYDRAFLOW_LABEL_PLAN=hydraflow-plan        # default
export HYDRAFLOW_GITHUB_REPO=owner/repo       # auto-detected if unset
export HYDRAFLOW_GITHUB_ASSIGNEE=username     # repo owner if unset
```

### 6. Install Claude Code hooks (optional)

HydraFlow ships with Claude Code hooks that enforce quality gates during development. To use them in your project:

```bash
# From your project root
mkdir -p .claude/hooks
cp hydraflow/.claude/hooks/*.sh .claude/hooks/
chmod +x .claude/hooks/*.sh
```

Then merge HydraFlow's hook configuration into your `.claude/settings.json`. The hooks provide:

| Hook | Trigger | What it does |
|------|---------|--------------|
| `block-destructive-git.sh` | PreToolUse(Bash) | Blocks `git push --force`, `reset --hard`, etc. |
| `validate-tests-before-commit.sh` | PreToolUse(Bash) | Runs lint + tests before `git commit` |
| `scan-secrets-before-commit.sh` | PreToolUse(Bash) | Scans staged files for secrets |
| `enforce-plan-and-explore.sh` | PreToolUse(Write/Edit) | Ensures agent explored before writing code |
| `check-test-counterpart.sh` | PreToolUse(Write) | Warns when writing source without tests |
| `enforce-migrations.sh` | PreToolUse(Write/Edit) | Checks for direct DB schema changes |
| `check-cross-service-impact.sh` | PreToolUse(Edit) | Flags cross-service shared/ changes |
| `check-reindex-needed.sh` | PreToolUse(claude-context) | Checks if claude-context index is stale |
| `track-exploration.sh` | PostToolUse(Read/claude-context/cclsp) | Tracks codebase exploration progress |
| `track-code-changes.sh` | PostToolUse(Write/Edit) | Tracks which files were modified |
| `track-planning.sh` | PostToolUse(TaskCreate) | Tracks planning activity |
| `track-indexed.sh` | PostToolUse(claude-context) | Tracks indexed files |
| `track-reindex-needed.sh` | PostToolUse(Bash) | Tracks when reindexing may be needed |
| `warn-new-file-creation.sh` | PostToolUse(Write) | Warns on new file creation |
| `cleanup-code-change-marker.sh` | Stop | Cleans up code change tracking markers |

### 7. Install git hooks (optional)

```bash
cd hydraflow
make setup
```

This configures:
- **pre-commit**: Ruff lint check on staged Python files
- **pre-push**: Full quality gate (lint + typecheck + security + tests)

### 8. Run HydraFlow

```bash
cd hydraflow

# Start with dashboard (opens http://localhost:5556)
make run

# Or dry-run to see what it would do
make dry-run
```

## Usage

### Creating issues for HydraFlow

Label a GitHub issue with `hydraflow-plan` and HydraFlow picks it up automatically:

```bash
# Via GitHub CLI
gh issue create --label hydraflow-plan --title "Add retry logic to API client" --body "..."

# Via Claude Code slash command (researches codebase first)
# In Claude Code, type:
/gh-issue add retry logic to the API client
```

### Slash commands

| Command | Description |
|---------|-------------|
| `/gh-issue <description>` | Research codebase and create a well-structured GitHub issue |
| `/audit-tests` | Unit test coverage and quality audit |
| `/audit-integration-tests` | Integration test coverage gap analysis |
| `/audit-hooks` | Audit Claude Code hooks for correctness and efficiency |

### Label lifecycle

| Label | Meaning | What happens next |
|-------|---------|-------------------|
| `hydraflow-find` | New issue discovered | Triage agent evaluates readiness, promotes to `hydraflow-plan` |
| `hydraflow-plan` | Issue needs a plan | Plan agent explores, posts plan comment, swaps to `hydraflow-ready` |
| `hydraflow-ready` | Ready for implementation | Impl agent creates worktree, writes code + tests, opens PR, swaps to `hydraflow-review` |
| `hydraflow-review` | PR under review | Review agent checks quality, waits for CI, auto-merges, swaps to `hydraflow-fixed` |
| `hydraflow-hitl` | Needs human help | CI failed after retries -- human intervention required |
| `hydraflow-hitl-active` | HITL in progress | Being processed by HITL correction agent |
| `hydraflow-fixed` | Done | PR merged successfully |

Labels can be overridden via CLI flags or environment variables:

```bash
# CLI flags
make run READY_LABEL=custom-ready PLANNER_LABEL=custom-plan

# Environment variables
export HYDRAFLOW_LABEL_FIND=custom-find
export HYDRAFLOW_LABEL_PLAN=custom-plan
export HYDRAFLOW_LABEL_READY=custom-ready
export HYDRAFLOW_LABEL_REVIEW=custom-review
export HYDRAFLOW_LABEL_HITL=custom-hitl
export HYDRAFLOW_LABEL_HITL_ACTIVE=custom-hitl-active
export HYDRAFLOW_LABEL_FIXED=custom-fixed
```

## Configuration

All configuration is via CLI flags or environment variables. Defaults are sensible for most repos.

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--find-label` | `HYDRAFLOW_LABEL_FIND` | `hydraflow-find` | Label for discovery/triage queue |
| `--planner-label` | `HYDRAFLOW_LABEL_PLAN` | `hydraflow-plan` | Label for planning queue |
| `--ready-label` | `HYDRAFLOW_LABEL_READY` | `hydraflow-ready` | Label for implementation queue |
| `--review-label` | `HYDRAFLOW_LABEL_REVIEW` | `hydraflow-review` | Label for review queue |
| `--hitl-label` | `HYDRAFLOW_LABEL_HITL` | `hydraflow-hitl` | Label for human escalation |
| `--hitl-active-label` | `HYDRAFLOW_LABEL_HITL_ACTIVE` | `hydraflow-hitl-active` | Label for HITL items being actively processed |
| `--fixed-label` | `HYDRAFLOW_LABEL_FIXED` | `hydraflow-fixed` | Label for completed issues |
| `--max-workers` | -- | `2` | Concurrent implementation agents |
| `--max-planners` | -- | `1` | Concurrent planning agents |
| `--max-reviewers` | -- | `1` | Concurrent review agents |
| `--model` | -- | `sonnet` | Model for implementation agents |
| `--planner-model` | -- | `opus` | Model for planning agents |
| `--review-model` | -- | `opus` | Model for review agents |
| `--max-budget-usd` | -- | `0` (unlimited) | USD cap per implementation agent |
| `--planner-budget-usd` | -- | `0` (unlimited) | USD cap per planning agent |
| `--review-budget-usd` | -- | `0` (unlimited) | USD cap per review agent |
| `--ci-check-timeout` | -- | `600` | Seconds to wait for CI checks |
| `--ci-poll-interval` | -- | `30` | Seconds between CI status polls |
| `--max-ci-fix-attempts` | -- | `2` | Max CI fix-and-retry cycles (0 disables CI wait) |
| `--main-branch` | -- | `main` | Base branch name |
| `--repo` | `HYDRAFLOW_GITHUB_REPO` | auto-detected | GitHub `owner/repo` slug |
| `--gh-token` | `HYDRAFLOW_GH_TOKEN` | -- | GitHub token override |
| `--dashboard-port` | -- | `5555` | Dashboard API port |
| `--no-dashboard` | -- | -- | Disable the web dashboard |
| `--dry-run` | -- | -- | Log actions without executing |
| `--verbose` | -- | -- | Enable debug logging |
| `--clean` | -- | -- | Remove all worktrees and state, then exit |

## Dashboard

HydraFlow includes a live web dashboard (React + Vite) served alongside the backend:

- **Pipeline view** — see issues flowing through triage → plan → implement → review → merged
- **Worker status** — real-time status of all active agents (planner, implementer, reviewer)
- **Live transcripts** — stream agent output as it happens via WebSocket
- **HITL queue** — view and respond to issues that need human intervention
- **PR tracking** — monitor open PRs with links to GitHub
- **Controls** — start/stop the orchestrator from the UI

Access the dashboard at `http://localhost:5556` when running `make run`.

## Development

```bash
make test           # Run unit tests
make lint           # Auto-fix linting (ruff)
make lint-check     # Check linting without fixing
make typecheck      # Run Pyright type checks
make security       # Run Bandit security scan
make quality        # All of the above
make ensure-labels  # Create HydraFlow labels in GitHub repo
make setup          # Install git hooks
make ui             # Build React dashboard
make ui-dev         # Start dashboard dev server
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
```

## Architecture

```
cli.py                 CLI entry point
orchestrator.py        Main coordinator (4 async polling loops)
config.py              HydraFlowConfig (Pydantic model)
triage.py              TriageRunner (issue readiness evaluation)
agent.py               AgentRunner (implementation agent)
planner.py             PlannerRunner (read-only planning agent)
reviewer.py            ReviewRunner (review + CI fix agent)
worktree.py            WorktreeManager (git worktree lifecycle)
pr_manager.py          PRManager (all gh CLI operations + label enforcement)
dashboard.py           FastAPI + WebSocket live dashboard
events.py              EventBus (async pub/sub)
state.py               StateTracker (JSON-backed crash recovery)
models.py              Pydantic data models
stream_parser.py       Claude CLI stream-json parser
log.py                 Logging configuration (structured JSON)
ui/                    React dashboard frontend
.claude/commands/      Claude Code slash commands
.claude/hooks/         Claude Code quality gate hooks
.claude/agents/        Agent definitions (code-quality-enforcer, test-audit)
.githooks/             Git pre-commit and pre-push hooks
```

## Tech Stack

- **Python 3.11** with Pydantic, asyncio
- **FastAPI + WebSocket** for the live dashboard
- **React + Vite** for dashboard UI
- **Ruff** for linting/formatting
- **Pyright** for type checking
- **Bandit** for security scanning
- **pytest + pytest-asyncio** for testing

## Roadmap

HydraFlow's development is tracked in two epics:

- **[#207 — Spec-Driven Planning Pipeline](https://github.com/T-rav/hydra/issues/207)** — structured plan schemas, delta semantics, progressive rigor, `[NEEDS CLARIFICATION]` markers, RFC 2119 keywords
- **[#222 — Self-Improving Agent Pipeline](https://github.com/T-rav/hydra/issues/222)** — memory digest, retrospectives, review insight aggregation, constitution amendments, performance tracking

Planned self-improvement capabilities:

- **Memory digest** — agents aggregate learnings across runs into persistent memory
- **Retrospectives** — automated post-mortem analysis of failed or slow implementations
- **Review insight aggregation** — patterns from review feedback inform future implementation prompts
- **Constitution amendments** — agents propose changes to CLAUDE.md conventions based on observed patterns

## Contributing

- **For AI agents** — see [CLAUDE.md](CLAUDE.md) for project conventions, architecture, and development commands
- **For humans** — check the [roadmap epics](#roadmap) above, pick an issue, and submit a PR
- **Issue format** — HydraFlow processes its own issues: label with `hydraflow-find` and the pipeline picks it up automatically
- **Quality gates** — all PRs must pass `make quality` (lint + typecheck + security + tests)

## License

[MIT](LICENSE) © 2026 Travis Frisinger
