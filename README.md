<p align="center">
  <img src="docs/hydraflow-logo-small.png" alt="HydraFlow" width="200">
</p>

<h1 align="center">HydraFlow</h1>

<p align="center">
  Intent in. Software out.
</p>

Log an issue. Agents handle the rest - triaging, planning, implementing, reviewing, and merging every change.

HydraFlow is built for quality-first scaling: agents execute the work, but guardrails decide what ships.

## What Makes It Different

- Quality-gated pipeline, not "one-shot" agent code generation
- Explicit stage controls (triage, plan, implement, review) before merge
- CI checks and human-in-the-loop escalation when confidence drops
- Coverage policy target across stacks: enforce 50% minimum and drive toward 70%+ on critical paths
- Repeatable standards that keep output consistent as workload grows

## Why Teams Use It

- Label-driven workflow from issue to merged PR
- Built-in planning, implementation, and review stages
- CI-aware automation with human-in-the-loop escalation
- Repo prep that scaffolds missing quality gates
- Live dashboard for visibility into work, agents, and queue state

## How It Works

HydraFlow runs a staged pipeline:

1. Triage: validate issue readiness and queue it for planning.
2. Plan: read-only exploration and concrete implementation plan.
3. Implement: isolated worktree changes with tests.
4. Review: agent review + CI monitoring + merge decision.
5. Escalate when needed: failures and ambiguity route to `hydraflow-hitl`.

See the full product walkthrough and visuals at [hydraflow.ai](https://hydraflow.ai/).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI](https://cli.github.com/) authenticated (`gh auth login`)
- Claude CLI and/or Codex CLI available on PATH
- Node.js 18+ (dashboard only)

## Quick Start

```bash
# in your project root
git submodule add https://github.com/T-rav/hyrda.git hydraflow
git submodule update --init --recursive
cd hydraflow

# install deps + bootstrap target repo hooks/assets/labels
make setup

# scaffold quality gates in the target repo (CI/make/tests/lint where missing)
make prep

# run orchestrator + dashboard (http://localhost:5556)
make run
```

## Core Commands

```bash
make              # command help
make setup        # bootstrap .env, hooks, labels, local assets
make prep         # repo audit + scaffold + hardening loop
make run          # start backend + dashboard
make dry-run      # print actions without executing
make quality-lite # lint + typecheck + security
make quality      # quality-lite + tests
```

## Issue Flow Labels

- `hydraflow-find`
- `hydraflow-plan`
- `hydraflow-ready`
- `hydraflow-review`
- `hydraflow-hitl`
- `hydraflow-hitl-active`
- `hydraflow-fixed`

You can override label names via `.env` (created from `.env.sample` during `make setup`).

## Prep Output and Local Tracking

`make prep` stores local prep artifacts under:

- `.hydraflow/prep/*.md` for local prep issues
- `.hydraflow/prep/runs/<run-id>/` for run logs/transcripts

Each prep run gets one locked run ID at start, and all logs for that run are written under the same run directory.

## Dashboard

When `make run` is active:

- UI: `http://localhost:5556`
- Shows pipeline state, active workers, CI/review progress, and HITL queue

## Development

```bash
make test
make lint
make lint-check
make lint-fix
make typecheck
make security
make quality-lite
make quality
```

## Contributing

- See `CLAUDE.md` for project conventions.
- Open issues in GitHub and use lifecycle labels for pipeline pickup.
- Keep changes green with `make quality` before PR.

## License

[Apache 2.0](LICENSE) © 2026 Travis Frisinger
