<p align="center">
  <img src="docs/hydraflow-logo-small.png" alt="HydraFlow" width="200">
</p>

<h1 align="center">HydraFlow</h1>

<p align="center">
  Intent in. Software out.
</p>

Log an issue. Agents handle the rest - triaging, planning, implementing, reviewing, and merging every change.

HydraFlow is a delivery kernel for GitHub repositories: it accepts intent, compiles it through a staged pipeline, enforces quality gates, and produces merged software changes.

It scales your workflow, not just your output, turning your repository into a programmable delivery engine powered by your hooks and skills. This is __Harness engineering__ at scale.

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
- Node.js 20.19+ or 22.12+ (dashboard only)

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
make smoke        # critical cross-system smoke tests
make quality-lite # lint + typecheck + security
make quality      # quality-lite + tests
```

## CLI Installation

HydraFlow now exposes an `hf` console script so you can run `hf init`, `hf prep`, `hf run`, etc.

```bash
# install locally from pyproject.toml (including configured extras)
uv sync --all-extras

# show available commands
hf --help

# copy hf assets (.claude, .codex, .pi, .githooks) into the current repo
hf init

# run the standard quick prep/scaffold flow without invoking make
hf prep

# ensure lifecycle labels exist (equivalent to make ensure-labels)
hf ensure-labels

# optional explicit alias for quick prep/scaffold
hf scaffold

# register the current repo (or an explicit path) with the background supervisor
hf run              # uses cwd
hf run /path/to/repo

# list/stop registered repos (state lives under ~/.hydraflow/<repo-slug>)
hf status                   # show every repo with RUNNING/STOPPED status
hf status repo-slug         # show a single slug
hf stop                     # stop repo in cwd
hf stop repo-slug           # or stop by slug
hf stop /path/to/repo
```

> HydraFlow still writes prep logs, memory, manifests, and run artifacts to
> `.hydraflow/` by default when you run `make` commands directly inside a repo.
> When you use `hf run`, the supervisor sets `HYDRAFLOW_HOME=~/.hydraflow/<repo-slug>`
> so all of those artifacts move under `~/.hydraflow/<repo-slug>/...` instead of
> cluttering your working tree.

### Generating release assets

If you modify `.claude`, `.codex`, or `.githooks`, run `make bundle-assets` to generate
`dist/hf_cli-assets.tar.gz` for release/build artifact workflows.
The repository no longer tracks a committed `src/hf_cli/assets.tar.gz`.

### Self-improving harness

This repo includes a harnessed self-improvement loop (observation + session retro + memory candidate artifacts).
See [docs/self-improving-harness.md](docs/self-improving-harness.md) for imported skills and runtime behavior.

### Publishing the hf CLI

When you're ready to publish `hydraflow` to PyPI:

1. `make cli-release` – runs `embed-assets`, the test suite, and `uv build`.
2. `uv publish` (or your release automation) – uploads the artifacts in `dist/`.

This flow guarantees the pip-installed CLI has a fresh copy of the asset bundle
and includes all runtime dependencies by default.

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

When `HYDRAFLOW_HOME` is set (the default under `hf run`), the same structure
lives under `~/.hydraflow/<repo-slug>/prep/...` so every repo can share a single
machine-wide HydraFlow home.

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

## Docker Execution Mode

HydraFlow can run agents inside Docker containers for isolation. This requires building the agent image and configuring authentication.

### 1. Build the agent image

```bash
docker build -f Dockerfile.agent -t ghcr.io/t-rav/hydraflow-agent:latest .
```

### 2. Enable Docker mode

Add to your `.env`:

```env
HYDRAFLOW_EXECUTION_MODE=docker
```

### 3. Configure agent authentication

Agents running inside containers cannot access your host's OAuth session or macOS keychain. You must provide API credentials via environment variables.

**Claude (subscription via Claude Max/Pro):**

```bash
# Generate a headless auth token
claude setup-token

# Add the token to .env
CLAUDE_CODE_OAUTH_TOKEN=<token-from-setup-token>
```

**Claude (API key):**

```env
ANTHROPIC_API_KEY=sk-ant-...
```

**Codex:**

Codex credentials are mounted automatically from `~/.codex/` on your host. No extra `.env` configuration is needed.

**Other supported providers** (set in `.env` as needed):

`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `GROQ_API_KEY`

### 4. Verify

```bash
make run
# Create a test issue — check logs for successful agent output instead of
# "authentication_failed" or empty transcripts.
```

## EC2 Deployment

Running HydraFlow as a 24/7 EC2 service is supported out-of-the-box:

- `deploy/ec2/deploy-hydraflow.sh` bootstraps dependencies, syncs code, and restarts the orchestrator.
- `deploy/ec2/deploy-hydraflow.sh doctor` runs a readiness check (git repo present, `.env` seeded, log/home dirs created, required binaries installed) before your first deploy.
- `deploy/ec2/hydraflow.service` keeps the process alive under systemd; the `install` helper renders it with `SERVICE_USER`, `SERVICE_GROUP`, `SERVICE_WORK_DIR`, and `SERVICE_LOG_FILE` overrides so non-/opt installs work without manual edits.
- FastAPI exposes `GET /healthz` with a `ready` flag plus per-component `checks` (orchestrator/worker/dashboard) so load balancers or monitors can make decisions without extra parsing.
- `deploy/ec2/deploy-hydraflow.sh health [URL]` curls `/healthz` using the host/port from `/etc/hydraflow.env` (or your override) and exits non-zero when `HEALTHCHECK_REQUIRE_READY=1` but `ready=false`, which makes it easy to wire into cron, ALB checks, or pager hooks.
- `deploy/ec2/deploy-hydraflow.sh wait-ready` (or `HEALTHCHECK_WAIT_FOR_READY=1 deploy ... deploy`) polls `/healthz` until `ready=true`; tune the gating with `HEALTHCHECK_WAIT_TIMEOUT_SECONDS` and `HEALTHCHECK_WAIT_INTERVAL_SECONDS`.
- `/etc/hydraflow.env` (override with `RUNTIME_ENV_FILE`) is sourced automatically so manual `run` commands and systemd share credentials/config.
- `deploy/ec2/deploy-hydraflow.sh install` copies the unit into `/etc/systemd/system` (or your custom `SYSTEMD_DIR`) and runs the required `systemctl enable --now` incantations.

See [docs/deployment/ec2.md](docs/deployment/ec2.md) for the full playbook, including how to bind the dashboard to `0.0.0.0` using the new `HYDRAFLOW_DASHBOARD_HOST` config knob and how to scope your EC2 security group safely.

## Contributing

- Fork it.
- Run HydraFlow on HydraFlow. (via `make run` in the repo)
- /gh-issue "thing to change"
- PR it back.
- See `CLAUDE.md` for project conventions and lifecycle labels.

## License

[Apache 2.0](LICENSE) © 2026 Travis Frisinger
