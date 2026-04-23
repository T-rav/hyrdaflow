# CLAUDE.md

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

This file is a table of contents. Operational guidance lives in [`docs/agents/`](docs/agents/README.md) and architectural rationale lives in [`docs/adr/`](docs/adr/README.md). Load the topic file relevant to your task — do not try to hold all of it in context.

## Quick rules (always apply)

- **Never commit to `main`.** The branch is protected; all changes go through a worktree branch and a pull request. No exceptions, not even for one-line fixes. See [`docs/agents/worktrees.md`](docs/agents/worktrees.md).
- **Never use `git commit --no-verify`** or `--no-hooks`. Fix code issues first.
- **Always run `make quality`** before declaring work complete. See [`docs/agents/quality-gates.md`](docs/agents/quality-gates.md).
- **Always write unit tests before committing.** See [`docs/agents/testing.md`](docs/agents/testing.md).
- **Always read [`docs/agents/avoided-patterns.md`](docs/agents/avoided-patterns.md)** before editing Pydantic models, test imports, or mocks — these are the recurring mistakes.

## Knowledge Lookup

Before exploring the codebase from scratch, consult existing structured knowledge. Contradicting an Accepted ADR requires a new ADR superseding it — not just a code change.

| Source | Path | What's there |
|--------|------|--------------|
| Architecture Decision Records | [`docs/adr/README.md`](docs/adr/README.md) | 40+ ADRs indexed by status. Load-bearing examples: [0001](docs/adr/0001-five-concurrent-async-loops.md) async loops · [0002](docs/adr/0002-labels-as-state-machine.md) label state machine · [0003](docs/adr/0003-git-worktrees-for-isolation.md) worktrees · [0021](docs/adr/0021-persistence-architecture-and-data-layout.md) persistence · [0029](docs/adr/0029-caretaker-loop-pattern.md) caretaker loops · [0032](docs/adr/0032-per-repo-wiki-knowledge-base.md) repo wiki |
| Topic guides for agents | [`docs/agents/README.md`](docs/agents/README.md) | Operational how-tos — see Topic index below |
| System topology diagrams | [`docs/architecture/`](docs/architecture/) | `.likec4` diagrams: data flow, orchestrator/plan-phase decomposition, supervision, Sentry flow, health monitor |
| Scenario testing framework | [`docs/scenarios/README.md`](docs/scenarios/README.md) | Release-gating scenario tests + `MockWorld` fixture |
| Deployment | [`docs/deployment/ec2.md`](docs/deployment/ec2.md) | EC2 deployment steps |
| Strategy docs | [`docs/`](docs/) | `self-improving-harness.md`, `ops-audit-plan.md`, `sentry-alerts.md`, `pi-backend-integration-plan.md`, `rpi-adoption-plan.md` |
| Per-target-repo wiki | [`src/repo_wiki.py`](src/repo_wiki.py) | LLM knowledge base (Karpathy pattern); query via `RepoWikiStore` when planning or reviewing work on a managed repo |

When you find a gap in the ADRs or wiki that would have helped you, file a `hydraflow-find` issue so the next run has better context.

## Topic index

Load the file relevant to your task before acting.

| Topic | File | When to read |
|-------|------|--------------|
| Architecture and key files | [`docs/agents/architecture.md`](docs/agents/architecture.md) | Exploring the codebase or placing new code |
| Git worktrees and branch protection | [`docs/agents/worktrees.md`](docs/agents/worktrees.md) | Before any code change |
| Testing is mandatory | [`docs/agents/testing.md`](docs/agents/testing.md) | Before writing or modifying tests |
| Avoided patterns | [`docs/agents/avoided-patterns.md`](docs/agents/avoided-patterns.md) | Before adding Pydantic fields, imports, or mocks |
| Quality gates | [`docs/agents/quality-gates.md`](docs/agents/quality-gates.md) | Before committing |
| Background loops | [`docs/agents/background-loops.md`](docs/agents/background-loops.md) | Creating or modifying a `BaseBackgroundLoop` subclass |
| Sentry rules | [`docs/agents/sentry.md`](docs/agents/sentry.md) | Adding logging or exception handling |
| UI standards | [`docs/agents/ui-standards.md`](docs/agents/ui-standards.md) | Touching `ui/src/` |
| Commands reference | [`docs/agents/commands.md`](docs/agents/commands.md) | Looking up a `make` target |
| Architecture decisions | [`docs/adr/README.md`](docs/adr/README.md) | Understanding *why* something is the way it is |

## Workflow skills (ADR-0044 P8/P10)

TDD is the default: `superpowers:brainstorming` → `superpowers:writing-plans`
→ `superpowers:test-driven-development` (red/green/refactor) → `superpowers:verification-before-completion` → `superpowers:requesting-code-review`.
Use `superpowers:systematic-debugging` on failures. Bug fixes land with a
regression test in `tests/regressions/`. See [`docs/agents/testing.md`](docs/agents/testing.md).

## Ubiquitous language (ADR-0044 P2.9)

Names are load-bearing — don't paraphrase. Full catalog in [`docs/agents/architecture.md`](docs/agents/architecture.md).

- `HydraFlowConfig`, `StateTracker` / `StateData`, `EventBus`, `SessionLog`, `ReviewResult`
- `BaseBackgroundLoop`, `RepoWikiStore`
- `PRPort` / `WorkspacePort` / `IssueStorePort` — hexagonal boundaries
- `AgentRunner` / `PlannerRunner` / `ReviewRunner`, `WorktreeManager`

