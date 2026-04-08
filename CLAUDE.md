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

Before exploring the codebase from scratch, consult existing structured knowledge.

- **Architecture Decision Records** — [`docs/adr/`](docs/adr/README.md) is the authoritative record of key design decisions (40+ entries). Read the relevant ADR before changing a documented decision area. Examples: [`0001-five-concurrent-async-loops.md`](docs/adr/0001-five-concurrent-async-loops.md), [`0002-labels-as-state-machine.md`](docs/adr/0002-labels-as-state-machine.md), [`0003-git-worktrees-for-isolation.md`](docs/adr/0003-git-worktrees-for-isolation.md), [`0021-persistence-architecture-and-data-layout.md`](docs/adr/0021-persistence-architecture-and-data-layout.md), [`0029-caretaker-loop-pattern.md`](docs/adr/0029-caretaker-loop-pattern.md), [`0032-per-repo-wiki-knowledge-base.md`](docs/adr/0032-per-repo-wiki-knowledge-base.md). Contradicting an Accepted ADR requires a new ADR superseding it, not just a code change.
- **Repository wiki** — [`src/repo_wiki.py`](src/repo_wiki.py) implements a per-target-repo LLM knowledge base (Karpathy pattern). Wiki entries are topic-categorized markdown capturing learnings from prior plan/implement/review cycles on managed repos. Query via `RepoWikiStore` when planning or reviewing work on a target repo.
- **Planning docs** — [`docs/`](docs/) contains `self-improving-harness.md`, `ops-audit-plan.md`, `sentry-alerts.md`, and similar strategy documents. Consult these when your task touches the areas they describe.

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
