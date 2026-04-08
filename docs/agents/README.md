# docs/agents — Topic-scoped guidance for coding agents

This directory holds the operational knowledge agents need while working on HydraFlow. `CLAUDE.md` at the repo root is a thin table of contents pointing here — agents are expected to load only the topic file relevant to the current task rather than paying the context cost of the full set on every run.

Structure mirrors [`docs/adr/`](../adr/README.md): one topic per file, one-line index entries, tests guard against broken links and regression back to the encyclopedia form (see `tests/test_claude_md_structure.py`).

## Index

| Topic | File | When to read |
|-------|------|--------------|
| Architecture and key files | [`architecture.md`](architecture.md) | Exploring the codebase or placing new code |
| Git worktrees and branch protection | [`worktrees.md`](worktrees.md) | Before any code change |
| Testing is mandatory | [`testing.md`](testing.md) | Before writing or modifying tests |
| Avoided patterns | [`avoided-patterns.md`](avoided-patterns.md) | Before adding Pydantic fields, imports, or mocks — read once per session |
| Quality gates | [`quality-gates.md`](quality-gates.md) | Before committing |
| Background loops | [`background-loops.md`](background-loops.md) | Creating or modifying a `BaseBackgroundLoop` subclass |
| Sentry rules | [`sentry.md`](sentry.md) | Adding logging or exception handling |
| UI standards | [`ui-standards.md`](ui-standards.md) | Touching `ui/src/` |
| Commands reference | [`commands.md`](commands.md) | Looking up a `make` target |

## Related knowledge sources

- **Architecture Decision Records** — [`docs/adr/README.md`](../adr/README.md). Read the relevant ADR before making changes to a documented decision area. Contradicting an Accepted ADR requires a new ADR superseding it.
- **Per-repo wiki** — [`src/repo_wiki.py`](../../src/repo_wiki.py). LLM knowledge base for target repos HydraFlow manages; see [`docs/adr/0032-per-repo-wiki-knowledge-base.md`](../adr/0032-per-repo-wiki-knowledge-base.md).
- **Planning and strategy docs** — [`docs/self-improving-harness.md`](../self-improving-harness.md), [`docs/ops-audit-plan.md`](../ops-audit-plan.md), [`docs/sentry-alerts.md`](../sentry-alerts.md).

## Adding a new topic file

1. Create `docs/agents/<topic>.md`
2. Add a row to the index table above
3. Link the new file from `CLAUDE.md` if it represents a top-level concern
4. Update `tests/test_claude_md_structure.py` if the new file should be covered by a structural invariant
