# CLAUDE.md

**HydraFlow** — Intent in. Software out. A multi-agent orchestration system that automates the full GitHub issue lifecycle via git issues and labels.

This file is a table of contents. Operational knowledge lives in the wiki at [`docs/wiki/`](docs/wiki/index.md); architectural decisions live at [`docs/adr/`](docs/adr/README.md). Look up the relevant entry — do not try to hold all of it in context.

## Quick rules (always apply)

- **Never commit to `main`.** The branch is protected; all changes go through a worktree branch and a pull request. No exceptions, not even for one-line fixes. Look up "Worktree" in [`docs/wiki/gotchas.md`](docs/wiki/gotchas.md).
- **Never use `git commit --no-verify`** or `--no-hooks`. Fix code issues first.
- **Always run `make quality`** before declaring work complete. Look up "Quality" in [`docs/wiki/patterns.md`](docs/wiki/patterns.md).
- **Always write unit tests before committing.** See [`docs/wiki/testing.md`](docs/wiki/testing.md).
- **Always read [`docs/wiki/gotchas.md`](docs/wiki/gotchas.md)** before editing Pydantic models, test imports, or mocks — recurring mistakes live there.
- **Look at the [System Map](https://t-rav.github.io/hydraflow/system-map/) before exploring code blind.** The Functional Area Map shows what every loop and Port belongs to; click through to ADRs from there.
- **Always verify subagent DONE claims** with `git status --porcelain` and `git log -1 --stat`. Subagents sometimes report DONE with edits applied but not committed.
- **Subprocess-spawning runners MUST call `reraise_on_credit_or_bug(exc)`** in their broad `except` block. Without it, `CreditExhaustedError` is silently eaten and the loop burns attempt budget against an exhausted billing signal. See [`docs/wiki/dark-factory.md`](docs/wiki/dark-factory.md) §2.2.
- **For substantial features, plan for 2–3 fresh-eyes review iterations** before merge. Convergence = next pass finds nothing material. See [`docs/wiki/dark-factory.md`](docs/wiki/dark-factory.md) §3.
- **Code-cleanup PRs (defensive-guard removal, dead-code drops) MUST be verified with full `make quality`**, not file-targeted test subsets. PR #8460 over-pruned `getattr(self, "_X", None)` checks where `_X` was set conditionally in subclasses or `__new__`-bypassed test scaffolding; the implementer ran 211 tests in three targeted files (all green) and shipped — but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed. Hotfix PR #8463 followed. Cleanup work has higher blast radius than its diff suggests.

## Knowledge Lookup

Before exploring the codebase from scratch, consult existing structured knowledge. Contradicting an Accepted ADR requires a new ADR superseding it — not just a code change.

| Source | Path | What's there |
|--------|------|--------------|
| Architecture Decision Records | [`docs/adr/README.md`](docs/adr/README.md) | 50+ ADRs indexed by status. Load-bearing examples: [0001](docs/adr/0001-five-concurrent-async-loops.md) async loops · [0002](docs/adr/0002-labels-as-state-machine.md) label state machine · [0003](docs/adr/0003-git-worktrees-for-isolation.md) worktrees · [0021](docs/adr/0021-persistence-architecture-and-data-layout.md) persistence · [0029](docs/adr/0029-caretaker-loop-pattern.md) caretaker loops · [0032](docs/adr/0032-per-repo-wiki-knowledge-base.md) repo wiki · [0045](docs/adr/0045-trust-architecture-hardening.md) trust fleet |
| Repo wiki (Karpathy pattern) | [`docs/wiki/`](docs/wiki/index.md) | 240+ entries: architecture, patterns, gotchas, testing, dependencies. Each entry has human-readable prose + a `json:entry` machine block. The `RepoWikiLoop` keeps it fresh from live pipeline events. |
| System topology (live) | [`docs/arch/generated/`](docs/arch/generated/) + [Pages site](https://t-rav.github.io/hydraflow/) | Auto-regenerated Markdown+Mermaid: loop registry, port map, label state machine, module graph, event bus, ADR cross-reference, MockWorld map, functional area map. Refreshed every PR by `arch-regen.yml` and every 4h by `DiagramLoop` (L24, ADR-0029). Hand-curated narrative lives in ADRs and the wiki. |
| Active design specs/plans | [`docs/superpowers/`](docs/superpowers/) | Working specs + implementation plans for in-flight features (PR-tied; not knowledge) |
| Methodology playbooks | [`docs/methodology/`](docs/methodology/) | Reusable playbooks behind HydraFlow's load-bearing patterns. Read before designing new docs/architecture machinery: [`self-documenting-architecture.md`](docs/methodology/self-documenting-architecture.md) — three-layer doc model, two-writers/one-set, freshness, drift exemptions, ADR discipline. |

When you find a gap in the ADRs or wiki that would have helped you, file a `hydraflow-find` issue so the next run has better context.

## Wiki topic index

Look up the relevant entry in [`docs/wiki/`](docs/wiki/index.md):

| Topic file | Looks like |
|---|---|
| [`architecture.md`](docs/wiki/architecture.md) | Cross-cutting architecture entries that don't fit a sub-topic (residual after the May-2026 split). Prefer the focused files below first. |
| [`architecture-layers.md`](docs/wiki/architecture-layers.md) | Four-layer model, facades, coordinator/orchestrator decomposition, module-level state |
| [`architecture-async-control.md`](docs/wiki/architecture-async-control.md) | Async patterns, background loops, label routing, callbacks, idempotency, error hierarchy |
| [`architecture-imports-types.md`](docs/wiki/architecture-imports-types.md) | Deferred imports, TYPE_CHECKING, type narrowing, optional dependencies, circular-import rules |
| [`architecture-state-persistence.md`](docs/wiki/architecture-state-persistence.md) | State persistence, schema evolution, Pydantic patterns, FastAPI route registration |
| [`architecture-refactoring.md`](docs/wiki/architecture-refactoring.md) | Dead-code removal, extraction, scope discipline, line-number-vs-pattern, multi-PR drift |
| [`architecture-patterns-practices.md`](docs/wiki/architecture-patterns-practices.md) | Coordinator + parameter threading, transcript parsing, EventBus threading, dispatcher patterns |
| [`patterns.md`](docs/wiki/patterns.md) | Kill-switch convention, dedup, escalation, quality gates, sentry, UI standards, commands |
| [`gotchas.md`](docs/wiki/gotchas.md) | Worktree rules, avoided patterns, five-checkpoint loop wiring, recurring footguns |
| [`testing.md`](docs/wiki/testing.md) | Test conventions, scenarios, cassettes, kill-switch tests, benchmarks |
| [`dependencies.md`](docs/wiki/dependencies.md) | Optional services, graceful degradation, dependency boundaries |
| [`dark-factory.md`](docs/wiki/dark-factory.md) | Lights-off operating contract, load-bearing conventions for new loops/runners, the 3-pass production-readiness convergence loop, recurring footguns |

## Workflow skills (ADR-0044 P8/P10)

TDD is the default: `superpowers:brainstorming` → `superpowers:writing-plans`
→ `superpowers:test-driven-development` (red/green/refactor) → `superpowers:verification-before-completion` → `superpowers:requesting-code-review`.
Use `superpowers:systematic-debugging` on failures. Bug fixes land with a
regression test in `tests/regressions/`. See [`docs/wiki/testing.md`](docs/wiki/testing.md).

For substantial features (new loop, new runner, spec → multi-task work), end with **2–3 fresh-eyes review iterations** until convergence per [ADR-0051](docs/adr/0051-iterative-production-readiness-review.md) — convergence = next pass finds nothing material.

## Ubiquitous language (ADR-0053)

Names are load-bearing — don't paraphrase. The canonical glossary lives at
[`docs/wiki/terms/`](docs/wiki/terms/) (one file per term) and is rendered to
[`docs/arch/generated/ubiquitous-language.md`](docs/arch/generated/ubiquitous-language.md)
on every PR. Drift between term anchors and live code is a CI failure; see
[ADR-0053](docs/adr/0053-ubiquitous-language-as-living-artifact.md).
