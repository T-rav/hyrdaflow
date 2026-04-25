# CLAUDE.md

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

This file is a table of contents. Operational knowledge lives in the wiki at [`docs/wiki/`](docs/wiki/index.md); architectural decisions live at [`docs/adr/`](docs/adr/README.md). Look up the relevant entry — do not try to hold all of it in context.

## Quick rules (always apply)

- **Never commit to `main`.** The branch is protected; all changes go through a worktree branch and a pull request. No exceptions, not even for one-line fixes. Look up "Worktree" in [`docs/wiki/gotchas.md`](docs/wiki/gotchas.md).
- **Never use `git commit --no-verify`** or `--no-hooks`. Fix code issues first.
- **Always run `make quality`** before declaring work complete. Look up "Quality" in [`docs/wiki/patterns.md`](docs/wiki/patterns.md).
- **Always write unit tests before committing.** See [`docs/wiki/testing.md`](docs/wiki/testing.md).
- **Always read [`docs/wiki/gotchas.md`](docs/wiki/gotchas.md)** before editing Pydantic models, test imports, or mocks — recurring mistakes live there.

## Knowledge Lookup

Before exploring the codebase from scratch, consult existing structured knowledge. Contradicting an Accepted ADR requires a new ADR superseding it — not just a code change.

| Source | Path | What's there |
|--------|------|--------------|
| Architecture Decision Records | [`docs/adr/README.md`](docs/adr/README.md) | 50+ ADRs indexed by status. Load-bearing examples: [0001](docs/adr/0001-five-concurrent-async-loops.md) async loops · [0002](docs/adr/0002-labels-as-state-machine.md) label state machine · [0003](docs/adr/0003-git-worktrees-for-isolation.md) worktrees · [0021](docs/adr/0021-persistence-architecture-and-data-layout.md) persistence · [0029](docs/adr/0029-caretaker-loop-pattern.md) caretaker loops · [0032](docs/adr/0032-per-repo-wiki-knowledge-base.md) repo wiki · [0045](docs/adr/0045-trust-architecture-hardening.md) trust fleet |
| Repo wiki (Karpathy pattern) | [`docs/wiki/`](docs/wiki/index.md) | 240+ entries: architecture, patterns, gotchas, testing, dependencies. Each entry has human-readable prose + a `json:entry` machine block. The `RepoWikiLoop` keeps it fresh from live pipeline events. |
| System topology diagrams | [`docs/architecture/`](docs/architecture/) | `.likec4` diagrams: data flow, orchestrator/plan-phase decomposition, supervision, Sentry flow, health monitor |
| Active design specs/plans | [`docs/superpowers/`](docs/superpowers/) | Working specs + implementation plans for in-flight features (PR-tied; not knowledge) |

When you find a gap in the ADRs or wiki that would have helped you, file a `hydraflow-find` issue so the next run has better context.

## Wiki topic index

Look up the relevant entry in [`docs/wiki/`](docs/wiki/index.md):

| Topic file | Looks like |
|---|---|
| [`architecture.md`](docs/wiki/architecture.md) | Architecture, layers, ports, async patterns, trust fleet, telemetry, deployment |
| [`patterns.md`](docs/wiki/patterns.md) | Kill-switch convention, dedup, escalation, quality gates, sentry, UI standards, commands |
| [`gotchas.md`](docs/wiki/gotchas.md) | Worktree rules, avoided patterns, five-checkpoint loop wiring, recurring footguns |
| [`testing.md`](docs/wiki/testing.md) | Test conventions, scenarios, cassettes, kill-switch tests, benchmarks |
| [`dependencies.md`](docs/wiki/dependencies.md) | Optional services, graceful degradation, dependency boundaries |

## Workflow skills (ADR-0044 P8/P10)

TDD is the default: `superpowers:brainstorming` → `superpowers:writing-plans`
→ `superpowers:test-driven-development` (red/green/refactor) → `superpowers:verification-before-completion` → `superpowers:requesting-code-review`.
Use `superpowers:systematic-debugging` on failures. Bug fixes land with a
regression test in `tests/regressions/`. See [`docs/wiki/testing.md`](docs/wiki/testing.md).

## Ubiquitous language (ADR-0044 P2.9)

Names are load-bearing — don't paraphrase. Look up specific terms in [`docs/wiki/architecture.md`](docs/wiki/architecture.md):

- `HydraFlowConfig`, `StateTracker` / `StateData`, `EventBus`, `SessionLog`, `ReviewResult`
- `BaseBackgroundLoop`, `RepoWikiStore`
- `PRPort` / `WorkspacePort` / `IssueStorePort` — hexagonal boundaries
- `AgentRunner` / `PlannerRunner` / `ReviewRunner`, `WorktreeManager`
