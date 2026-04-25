# ADR-0044: HydraFlow Principles — the audit contract for new and existing repos

- **Status:** Proposed
- **Date:** 2026-04-22
- **Supersedes:** none
- **Superseded by:** none
- **Enforced by:** scripts/hydraflow_audit/* (structural/behavioural checks), tests/test_planner.py::test_build_prompt_includes_principles_checklist, tests/test_reviewer.py::test_build_review_prompt_includes_hydraflow_principles_checks (prompt-level enforcement in plan + review phases)

## Context

HydraFlow's value is not any single agent loop or script — it is the *shape* of
the repository: the documentation contract, the hexagonal split, the scenario
testing harness with `MockWorld`, the quality gates, the CI workflow, the five
concurrent async loops, the label state machine, the Sentry discipline, and
the superpowers skill workflow. Today these live in a scattered set of files:
`CLAUDE.md`, `docs/wiki/*`, and 40+ existing ADRs. A new project that wants
to adopt "the HydraFlow way" has to reverse-engineer the shape from those
documents. An existing project trying to evolve toward the shape has no way to
measure how far along it is.

We want one declarative source of truth that (a) enumerates the principles,
(b) cites the existing documentation for each one, and (c) is machine-parseable
so `make audit` can score a repository against the principles without
duplicating the rules in Python.

## Decision

Define ten principles — P1 through P10 — each corresponding to a load-bearing
facet of HydraFlow. Each principle section contains:

1. A one-line **Rule** stating the intent.
2. A **Why** paragraph naming the failure mode the principle prevents.
3. A **How to apply** paragraph for the greenfield and adoption cases.
4. A **Check table** with columns `check_id | type | source | what | remediation`,
   parsed directly by `scripts/hydraflow_audit/` at runtime.

The `type` column takes one of three values:

- **STRUCTURAL** — a file or directory must exist with a specified shape.
  Audit fails loudly when missing.
- **BEHAVIORAL** — a tool must run clean, or a target must exist and succeed.
  Audit runs the tool and fails on non-zero exit.
- **CULTURAL** — a human workflow rule that the audit cannot verify reliably
  (e.g. branch protection on the remote, "never commit to main"). Audit emits
  a WARN with the ADR citation and a remediation hint; humans confirm in the
  `make init` prompt.

The audit tool (`scripts/hydraflow_audit/`) parses these tables at startup and
dispatches each `check_id` to a Python check function of the same name. If a
table row exists without a matching check function, the audit fails with
"check not implemented" — this keeps the ADR and the script in lockstep.

The prompt tool (`scripts/hydraflow_init/`) reads the audit's JSON output and
templates a superpowers-chained plan (brainstorming → writing-plans → TDD →
verification) scoped to the failing principles only.

**Self-documenting by construction.** Every check row cites either an ADR or
a `docs/wiki/` file as its `source`. The audit report echoes those
citations, and `make init` injects them into the remediation plan. A reader
who sees a FAIL can follow the citation to the decision that motivated the
rule — not a paraphrase, the real thing. The ADR and wiki layers *are* the
documentation; this ADR is the index that makes them executable. When a
principle changes, you edit the ADR; when a check changes, you edit the
table row; the script re-reads both on the next run. There is no
out-of-band spec for what "HydraFlow-shaped" means — this file is the spec.

**Self-observing by construction.** The audit and init tools are themselves
instrumented with the Sentry filter defined in P7, so runtime failures in
the tooling surface as real signal — an audit that silently swallows a
check exception is worse than no audit. Unhandled tool exceptions become
Sentry events (real bugs only; transient errors log at `warning`). Future
backends — OpenTelemetry traces, structured JSONL to a SIEM, a local
observability sidecar — can plug in behind the same port without changing
call sites. The project follows the patterns it enforces.

## The ten principles

### P1. Documentation Contract

**Rule.** A HydraFlow repo has a machine-navigable documentation spine:
`CLAUDE.md` at the root as a table of contents, `docs/wiki/` as the topic
guides, `docs/adr/` as the decision log.

**Why.** Agents and new humans need a stable entry point. Without it, every
session starts by re-reading scattered READMEs, context windows burn on
re-discovery, and ad-hoc docs drift silently out of sync with code.

**How to apply.** Greenfield: scaffold all three locations with the topic
stubs listed below. Adoption: copy the structure from HydraFlow, then fill in
project-specific content — the *shape* matters more than the wording.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | STRUCTURAL | CLAUDE.md | `CLAUDE.md` exists at repo root | `touch CLAUDE.md` and populate from the template |
| P1.2 | STRUCTURAL | docs/wiki/index.md | `docs/wiki/index.md` exists | Copy the topic-index layout from the HydraFlow repo |
| P1.3 | STRUCTURAL | docs/wiki/architecture.md | `docs/wiki/architecture.md` exists | Describe the major components and their boundaries |
| P1.4 | STRUCTURAL | docs/wiki/gotchas.md | `docs/wiki/gotchas.md` exists | Document the branch-protection and worktree workflow |
| P1.5 | STRUCTURAL | docs/wiki/testing.md | `docs/wiki/testing.md` exists | Document coverage floor and test layering |
| P1.6 | STRUCTURAL | docs/wiki/gotchas.md | `docs/wiki/gotchas.md` exists | Seed with Pydantic, test-import, and mocking pitfalls |
| P1.7 | STRUCTURAL | docs/wiki/patterns.md | `docs/wiki/patterns.md` exists | Document the `make quality` sequence |
| P1.8 | STRUCTURAL | docs/wiki/architecture.md | `docs/wiki/architecture.md` exists | Only required if the project has background loops |
| P1.9 | STRUCTURAL | docs/wiki/patterns.md | `docs/wiki/patterns.md` exists | Document the bug-types filter and logging levels |
| P1.10 | STRUCTURAL | docs/wiki/patterns.md | `docs/wiki/patterns.md` exists | List the Makefile targets |
| P1.11 | STRUCTURAL | docs/adr/README.md | `docs/adr/README.md` exists with an index table | Start the ADR index, even if there is only one ADR |
| P1.12 | BEHAVIORAL | CLAUDE.md | `CLAUDE.md` contains a "Quick rules" section | Add the five non-negotiables (no main commits, no `--no-verify`, run `make quality`, write tests, read avoided-patterns) |
| P1.13 | BEHAVIORAL | CLAUDE.md | `CLAUDE.md` contains a knowledge lookup table | List docs/wiki, docs/adr, and any repo-wiki location |
| P1.14 | STRUCTURAL | docs/adr/README.md | Load-bearing ADRs are present and marked Accepted (or project equivalents exist) | For orchestration repos: ADR-0001 (loops), 0002 (labels), 0003 (worktrees), 0021 (persistence), 0022 (MockWorld), 0029 (caretakers), 0032 (wiki). Non-orchestration repos mark N/A with justification in `docs/adr/README.md` |
| P1.15 | BEHAVIORAL | docs/wiki/gotchas.md | File has ≥5 pattern sections with example code blocks | Seed from HydraFlow's 13-section file; an empty stub does not count |
| P1.16 | BEHAVIORAL | docs/adr/README.md | ADR source citations omit line numbers (use `module:function_or_class`) | Grep for `:\d+` in ADR prose and strip; line numbers drift as code evolves |

### P2. Domain-Driven Design, Ports & Adapters, Clean Architecture

**Rule.** Source is organised into four layers — domain, application,
runners, infrastructure — with imports flowing inward only (clean
architecture). Cross-layer coupling is expressed through Protocols in a
single `ports` module (ports & adapters / hexagonal), never direct imports.
The domain layer speaks a *ubiquitous language*: the names in code match
the names in docs and in conversation (DDD). Domain types carry behaviour,
not just data — anaemic Pydantic models that only hold fields belong in
DTOs, not the domain.

**Why.** Without enforced direction, agent code grows into a ball of mud
where a GitHub change breaks the domain model. Protocol boundaries make the
system testable with stateful fakes (see P3) and make each adapter
replaceable (swap Anthropic for Codex, GitHub for Gitea, without touching
the domain). Ubiquitous language collapses translation costs during review —
when `Issue`, `Phase`, `Worktree` mean the same thing in prose and code,
new contributors do not have to translate. The inward-only import rule is
the one invariant that keeps the other three (ports, DDD, testability)
possible; once domain imports infrastructure, all three collapse.

**How to apply.** Greenfield: create the layer directories up front, name
them after bounded contexts you can say out loud, and add
`scripts/check_layer_imports.py` to CI before any domain code is written.
Adoption: introduce `ports.py` first, migrate infrastructure behind
Protocols one at a time, then add the import checker with an allowlist
that shrinks per PR. Rename domain types to match the ubiquitous language
as their first refactor — before anything else changes.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P2.1 | STRUCTURAL | ADR-0003 | `src/` directory exists | Move module code under `src/` to keep test discovery clean |
| P2.2 | STRUCTURAL | docs/wiki/architecture.md | `src/ports.py` exists and defines at least one `Protocol` | Extract the first cross-layer boundary (likely the PR/VCS adapter) |
| P2.2a | STRUCTURAL | docs/wiki/architecture.md | Each infrastructure boundary the project uses has a Protocol in `ports.py` (VCS, workspace, runner, LLM if applicable) | Add a Protocol the first time you reach for `AsyncMock` in a unit test; that is the signal a port is missing |
| P2.3 | STRUCTURAL | docs/wiki/architecture.md | `scripts/check_layer_imports.py` exists | Port the HydraFlow script; configure the layer map for this repo |
| P2.4 | BEHAVIORAL | ADR-0003 | `make layer-check` exits 0 (no upward imports) | Refactor the offending import behind a `ports.py` Protocol |
| P2.5 | STRUCTURAL | docs/wiki/architecture.md | A composition root module (e.g. `service_registry.py`) wires layers | Centralise dependency assembly so tests can swap fakes cleanly |
| P2.6 | STRUCTURAL | docs/wiki/architecture.md | Composition root is the *only* module allowed to import across layer boundaries (explicit ALLOWLIST entry) | Layer checker treats the root as a documented exception, not a blanket escape hatch |
| P2.7 | STRUCTURAL | docs/wiki/architecture.md | Domain layer has no imports from infrastructure, runners, or third-party adapter SDKs | The layer-check must special-case this to a hard failure; domain purity is the load-bearing invariant |
| P2.8 | BEHAVIORAL | docs/wiki/architecture.md | Domain types carry behaviour (methods), not just `@dataclass`/Pydantic fields | Anaemic domain is a sign logic leaked into application or infra; audit samples `src/<domain>/*.py` and warns on files with zero methods on public types |
| P2.9 | CULTURAL | docs/wiki/architecture.md | Ubiquitous language: domain type names appear in `docs/wiki/architecture.md` and in `CLAUDE.md` with matching semantics | When the doc says "Issue" and the code says "Task", translation overhead accumulates; keep one name per concept |

### P3. Testing — MockWorld and Layered Tests

**Rule.** Tests are organised into five concentric rings — unit,
integration, scenario, E2E (smoke + browser), regression — with a stateful
`MockWorld` fixture driving the scenario ring. Coverage floor is 70%.
Scenarios gate release.

**Why.** `AsyncMock`-based tests pass with the wrong call shape; stateful
fakes catch real interaction bugs. Concentric layering means fast tests run
every commit and slow E2E runs in CI. 70% coverage is pragmatic — higher
thresholds drive test-coverage theatre, lower drive regressions. MockWorld's
value comes from *how* it fakes (state you can inspect, time you can
advance, services you can fault-inject) — a `mock_world` fixture that
delegates to `AsyncMock` passes the shape check but defeats the point.

**How to apply.** Greenfield: scaffold `tests/scenarios/` with `conftest.py`,
`fakes/`, and at least one happy/sad/edge scenario on day one. Adoption: add
`MockWorld` alongside existing tests; do not retro-fit old tests, but require
all new pipeline tests to use it. E2E and browser rings are conditional —
only required when a dashboard or UI exists.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P3.1 | STRUCTURAL | ADR-0022 | `tests/scenarios/` directory exists | Create the directory and seed a happy-path scenario |
| P3.2 | STRUCTURAL | ADR-0022 | `tests/scenarios/conftest.py` provides a `mock_world` fixture | Port the fixture wiring from HydraFlow |
| P3.3 | STRUCTURAL | ADR-0022 | `tests/scenarios/fakes/` contains ≥3 stateful fakes (VCS, LLM, workspace at minimum) | Replace `AsyncMock` fakes one boundary at a time |
| P3.4 | STRUCTURAL | docs/wiki/testing.md | `tests/conftest.py` exists with shared fixtures | Centralise env isolation and factory fixtures |
| P3.5 | STRUCTURAL | docs/wiki/testing.md | At least one factory class (e.g. `IssueFactory`) exists under `tests/` | Introduce factories before the third duplicated fixture |
| P3.6 | BEHAVIORAL | docs/wiki/testing.md | Coverage floor of 70% configured in `pyproject.toml` | Add `fail_under = 70` under `[tool.coverage.report]` |
| P3.7 | BEHAVIORAL | docs/wiki/testing.md | `make test` runs the unit tier and exits 0 | Wire `pytest tests/` into `make test` |
| P3.8 | BEHAVIORAL | ADR-0022 | `make scenario` runs the scenario tier and exits 0 | Add the `scenario` pytest marker and a `make` target |
| P3.9 | BEHAVIORAL | docs/wiki/patterns.md | `make smoke` target exists and exits 0 | Smoke is the minimal cross-system path that must pass on every push |
| P3.10 | STRUCTURAL | ADR-0022 | Scenario tests are release-gating (CI blocks release branch promotion on scenario red) | Wire `make scenario` into the release or RC workflow (see ADR-0042 for the promotion model) |
| P3.11 | STRUCTURAL | docs/scenarios/README.md | When `ui/` exists, browser E2E directory (`tests/scenarios/browser/` or equivalent) exists | Add Playwright harness with at least one dashboard smoke test; skip if no UI |
| P3.12 | STRUCTURAL | ADR-0022 | A `ScenarioResult` / `IssueOutcome`-shaped dataclass exists for scenario inspection | Return structured results from `world.run_pipeline()` so assertions read state, not call counts |
| P3.13 | STRUCTURAL | ADR-0022 | `FakeClock` (or equivalent deterministic time fake) exists | Scenarios must not depend on wall-clock time; inject a clock fake |
| P3.14 | BEHAVIORAL | ADR-0022 | Fakes expose stateful inspection (`world.vcs.issue(1).labels` or similar), not just `assert_called_with` | Rebuild the offending fake as a stateful class; `AsyncMock` subclasses do not count |
| P3.15 | STRUCTURAL | ADR-0022 | `MockWorld` exposes fault-injection API (`fail_service` / `heal_service` or equivalent) | Wire fault injection before the first retry/recovery scenario is written |
| P3.16 | STRUCTURAL | docs/wiki/testing.md | `tests/regressions/` directory exists | Add the directory; every bug fix lands with a regression test there |
| P3.17 | STRUCTURAL | docs/wiki/testing.md | `integration` and `scenario` pytest markers registered in `pyproject.toml` | Declare markers under `[tool.pytest.ini_options.markers]` to fail CI on typos |
| P3.18 | BEHAVIORAL | docs/wiki/testing.md | At least one `*_integration.py` test file exists to drive the integration ring | Start with a cross-module wiring test; pure unit tests do not satisfy this |
| P3.19 | BEHAVIORAL | docs/wiki/gotchas.md | No top-level imports of optional dependencies in test files | Move imports inside the test function; top-level imports break collection when deps are absent |

### P4. Quality Gates

**Rule.** `make quality` is the single command a developer runs before
declaring work complete. It composes lint, typecheck, security, test, and
layer-check into one fail-fast pipeline. `make quality-lite` runs the
non-test checks for quick iteration.

**Why.** Quality tools only help when they run. One canonical target removes
the "did I run all of them" ambiguity and gives CI a single command to mirror.

**How to apply.** Greenfield: add all five tools on day one, even with empty
configs — it is cheaper than retrofitting. Adoption: introduce tools one at
a time via `quality-lite` so the first PR that adds `make quality-lite`
is small; `make quality` (which includes tests) follows once coverage is
credible.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P4.1 | BEHAVIORAL | docs/wiki/patterns.md | `make lint-check` target exists and exits 0 | Add `ruff check` + `ruff format --check` behind the target |
| P4.2 | BEHAVIORAL | docs/wiki/patterns.md | `make typecheck` target exists and exits 0 | Add `pyright` with config in `pyproject.toml` |
| P4.3 | BEHAVIORAL | docs/wiki/patterns.md | `make security` target exists and exits 0 | Add `bandit -r src/ --severity-level medium` |
| P4.4 | BEHAVIORAL | docs/wiki/patterns.md | `make test` target exists and exits 0 | Wire pytest behind the target |
| P4.5 | BEHAVIORAL | docs/wiki/patterns.md | `make quality-lite` composes lint + typecheck + security | Add the aggregate target |
| P4.6 | BEHAVIORAL | docs/wiki/patterns.md | `make quality` composes quality-lite + test + layer-check | Add the final gate target |
| P4.7 | STRUCTURAL | docs/wiki/patterns.md | Tool configs live in `pyproject.toml` (not a forest of dotfiles) | Move ruff/pyright/bandit/pytest configs into `pyproject.toml` |

### P5. CI and Branch Protection

**Rule.** CI mirrors `make quality` on every PR and enforces the same exit
codes. `main` is protected and only advances through PRs. Pre-commit and
pre-push hooks run the relevant subset locally.

**Why.** If CI and local gates diverge, one of them lies. Branch protection
on `main` turns the quick rule "never commit to main" into a guarantee the
remote enforces rather than a convention humans remember.

**How to apply.** Greenfield: push the first commit on a branch, set up
branch protection before merging it, and wire the `.github/workflows/ci.yml`
file in the same PR. Adoption: enable branch protection first, then
migrate local `make` commands into CI one at a time to avoid a big-bang
green/red switch.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P5.1 | STRUCTURAL | docs/wiki/patterns.md | `.github/workflows/` directory contains at least one workflow | Port `ci.yml` from HydraFlow as a starting point |
| P5.2 | BEHAVIORAL | docs/wiki/patterns.md | Workflow runs `make quality-lite` or equivalent | Wire the make target into the workflow's steps |
| P5.3 | BEHAVIORAL | docs/wiki/patterns.md | Workflow runs `make test` with the coverage gate | Add a `--cov-fail-under=70` invocation |
| P5.4 | STRUCTURAL | docs/wiki/gotchas.md | `.githooks/pre-commit` exists and is executable | Seed the hook from HydraFlow's template |
| P5.5 | CULTURAL | docs/wiki/gotchas.md | `main` has branch protection with required PR review and CI | Enable via GitHub repo settings; audit cannot verify offline |
| P5.6 | CULTURAL | CLAUDE.md | No direct pushes to `main` in the last 100 commits | Inspect `git log --first-parent main`; audit reports as a warning |
| P5.7 | BEHAVIORAL | docs/wiki/patterns.md | `pytest` treats `RuntimeWarning` and `PytestUnraisableExceptionWarning` as errors | Add `filterwarnings = ["error::RuntimeWarning", "error::pytest.PytestUnraisableExceptionWarning"]` to `pyproject.toml`; warnings-are-errors turns async lifecycle bugs into red CI instead of silent drift |
| P5.8 | STRUCTURAL | docs/wiki/patterns.md | `.githooks/pre-push` exists and runs `make quality-lite` | Pre-commit gates *staged* Python; pre-push gates the *branch* before the remote sees it |
| P5.9 | BEHAVIORAL | docs/wiki/patterns.md | Pre-commit hook implements self-repair (on lint-check failure, run `make lint-fix` and re-stage before escalating) | Agent sessions stall indefinitely on formatting errors otherwise; self-repair keeps the loop moving |
| P5.10 | STRUCTURAL | CLAUDE.md | Pre-commit hook refuses deletion or net content removal of `CLAUDE.md` | Load-bearing file; silent loss of the Quick Rules section would remove the project's guardrails without notice |

### P6. Agents — Loops, Labels, Background Workers

**Rule.** Pipeline work runs as N concurrent async loops (N=5 for HydraFlow)
coordinating on a GitHub label state machine. Auxiliary long-running work
runs as `BaseBackgroundLoop` subclasses wired through a five-checkpoint
registration (service registry, orchestrator dict, UI constants, dashboard
route bounds, config interval).

**Why.** Concurrent loops let the system make progress on independent phases
without queue coordination. Labels as the state machine mean every state
transition is visible on the GitHub timeline — debuggable by reading a PR.
The five-checkpoint wiring is how we avoid "half-registered" loops that run
but don't show up in the UI.

**How to apply.** Greenfield orchestration project: scaffold the
`BaseBackgroundLoop` base class and the wiring test on day one.
Non-orchestration project: this principle is informational; note in the
audit output that P6 is optional for the repo type and skip the failures.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P6.1 | STRUCTURAL | ADR-0001 | `src/orchestrator.py` exists with concurrent loop structure | Only applicable to orchestration-shaped projects; mark N/A otherwise |
| P6.2 | STRUCTURAL | ADR-0002 | Label names are centralised in config (not scattered strings) | Collect labels into a single config module or dataclass |
| P6.3 | STRUCTURAL | ADR-0029 | `BaseBackgroundLoop` base class exists | Port from HydraFlow when the first long-running job appears |
| P6.4 | BEHAVIORAL | docs/wiki/architecture.md | Loop-wiring completeness test covers all five checkpoints (service registry, orchestrator dict, UI constants, dashboard-route bounds, config interval + env override) | Port HydraFlow's `test_loop_wiring_completeness.py`; half-wired loops run but vanish from the dashboard |
| P6.5 | STRUCTURAL | ADR-0002 | Atomic label-swap helper exists (no ad-hoc add/remove call sites) | Add a `swap_pipeline_labels` function and forbid direct calls |

### P7. Observability — Sentry, Structured Logging, Repo Wiki

**Rule.** Sentry events are filtered by a `_BUG_TYPES` gatekeeper so
transient errors never page a human. Logging uses structured levels
(`warning` for expected transient failures, `error` only for real bugs).
Knowledge captured from past runs is stored in a per-repo wiki under
`repo_wiki/<repo_slug>/` and injected into runner prompts.

**Why.** Unfiltered Sentry becomes noise and gets muted. Unstructured logs
mean incident response starts from zero every time. The repo wiki is how the
system compounds learnings rather than re-discovering them every session.

**How to apply.** Greenfield: define `_BUG_TYPES` the first time you wire
Sentry; seed `repo_wiki/` with the first post-mortem. Adoption: introduce
the filter in a dedicated PR so the drop in event volume is visible; migrate
noisy `logger.error` calls to `logger.warning` in a follow-up.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P7.1 | STRUCTURAL | docs/wiki/patterns.md | `_BUG_TYPES` tuple exists where Sentry is initialised | Define the tuple with real-bug exceptions only |
| P7.2 | BEHAVIORAL | docs/wiki/patterns.md | Sentry `before_send` callback uses `_BUG_TYPES` | Wire the filter in the init call |
| P7.3 | STRUCTURAL | ADR-0032 | `repo_wiki/` directory exists (or project-equivalent knowledge base) | Create the directory; seed from post-mortems |
| P7.3a | STRUCTURAL | ADR-0032 | Wiki has the three-layer shape: raw sources, synthesised wiki pages, index/schema | A flat dumping ground of markdown is not a wiki; the compiler/librarian pattern requires all three |
| P7.3b | BEHAVIORAL | ADR-0032 | Wiki store exposes ingest / query / lint operations (or project equivalents) | Port `RepoWikiStore`; without ingest the wiki stagnates, without lint it accumulates stale entries |
| P7.3c | BEHAVIORAL | ADR-0032 | Runner prompts inject relevant wiki content before agent invocation | `_inject_repo_wiki` pattern or equivalent; a wiki that is never read has no value |
| P7.4 | CULTURAL | docs/wiki/patterns.md | No `except: pass` or bare `except:` in `src/` | Audit greps; remediate by logging at `warning` minimum |
| P7.5 | BEHAVIORAL | docs/wiki/patterns.md | No `logger.error(value)` without a format string (audit greps `logger\.error\(\w+\)$`) | Format strings preserve structure for log aggregation; bare-value error calls flatten to opaque strings |
| P7.6 | STRUCTURAL | docs/wiki/patterns.md | The audit and init tooling (`scripts/hydraflow_audit/`, `scripts/hydraflow_init/`) route unhandled exceptions through the P7.1/P7.2 Sentry filter | The tooling must follow its own principle; silent audit failures poison the signal the audit is supposed to provide |
| P7.7 | STRUCTURAL | docs/wiki/patterns.md | Observability is behind a port (`ObservabilityPort` or equivalent) so the Sentry adapter can be swapped for OTLP / structured logs / a sidecar without touching call sites | Preserves future optionality without committing to a second backend today |

### P8. Superpowers / Skills Integration

**Rule.** The repo is wired to the superpowers skill pack so sessions start
with brainstorming for greenfield work, TDD for features, systematic
debugging for bugs, writing-plans for multi-step changes, and
verification-before-completion before commits. Hooks run in `.claude/hooks/`
enforce the guardrails the human-driven skills encode.

**Why.** Skills are the operational playbook. Without them each session
re-litigates how to approach a task. Hooks make the "always" rules in
`CLAUDE.md` actually always-on instead of best-effort.

**How to apply.** Greenfield: seed `.claude/settings.json` and
`.claude/hooks/` from HydraFlow. Adoption: add one hook at a time, starting
with `block-destructive-git` (high value, low controversy).

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P8.1 | STRUCTURAL | CLAUDE.md | `.claude/` directory exists | Seed from HydraFlow's `.claude/` layout |
| P8.2 | STRUCTURAL | CLAUDE.md | `.claude/settings.json` or `settings.local.json` exists | Configure hooks and skill references |
| P8.3 | STRUCTURAL | CLAUDE.md | `.claude/hooks/` contains at least one PreToolUse hook | Start with `block-destructive-git` |
| P8.4 | CULTURAL | CLAUDE.md | CLAUDE.md references the six core superpowers skills by name | Must mention: `brainstorming`, `test-driven-development`, `systematic-debugging`, `writing-plans`, `verification-before-completion`, `requesting-code-review`. A vague "use skills" line does not count |
| P8.5 | STRUCTURAL | CLAUDE.md | `.claude/hooks/` includes at least one hook of each enforced kind: PreToolUse, PostToolUse, Stop | Seed from HydraFlow: `block-destructive-git` (PreToolUse), `auto-lint-after-edit` (PostToolUse), `hf.session-retro` (Stop) |
| P8.6 | STRUCTURAL | docs/self-improving-harness.md | In-process trace collector writes subprocess traces per phase/run | Port `trace_collector.py`; without traces, session retros have nothing to mine |

### P9. Persistence and Data Layout

**Rule.** All run-time state lives under a single configurable root
(`config.data_root`, default `.hydraflow/`), scoped by repo slug. Writes are
atomic. Cross-process coordination goes through named stores
(`StateTracker` for phase state, `DedupStore` for idempotency) rather than
ad-hoc files. Nothing run-time goes in the repo working tree.

**Why.** A single root makes ops trivial — one directory to back up, one to
blow away, one to gitignore. Repo-slug scoping means multiple target repos
coexist without collision. Atomic writes prevent corrupted state from a
killed process becoming permanent. Named stores concentrate the race-prone
logic in one place; ad-hoc JSON files scattered across modules grow
inconsistent invariants.

**How to apply.** Greenfield: define `data_root` in config on day one, even
if the first feature only needs one file. Adoption: introduce `data_root`
and migrate one persisted file at a time; keep backward-compatible reads
until the migration is complete.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P9.1 | STRUCTURAL | ADR-0021 | Config exposes a `data_root` (or equivalent) field with a documented default | Add to the config dataclass; default under the user's home or a repo-gitignored path, not the working tree |
| P9.2 | BEHAVIORAL | ADR-0021 | `data_root` is overridable via environment variable | Wire `HYDRAFLOW_DATA_ROOT` (or project-namespaced equivalent) through config loading |
| P9.3 | STRUCTURAL | ADR-0021 | Persisted state is scoped per repo slug inside `data_root` | Path shape: `<data_root>/<repo_slug>/...` so multi-repo runs never collide |
| P9.4 | STRUCTURAL | ADR-0021 | `StateTracker`-shaped abstraction exists for phase/run state | Centralise state transitions; disallow direct JSON read/write from phase code |
| P9.5 | STRUCTURAL | ADR-0021 | `DedupStore`-shaped abstraction exists for idempotency tracking | Background loops must guard against double-processing across restarts |
| P9.6 | BEHAVIORAL | ADR-0021 | All state writes go through atomic write helper (write-to-temp + rename) | A `kill -9` mid-write must not leave a half-valid file |
| P9.7 | STRUCTURAL | ADR-0021 | `data_root` (default `.hydraflow/`) is in `.gitignore` | Run-time state is never committed; enforce via gitignore |
| P9.8 | STRUCTURAL | ADR-0021 | No run-time state is written inside `src/` or the repo working tree | Grep for `open(.*"w")` with repo-relative paths outside `data_root`; migrate hits to the store abstractions |

### P10. TDD Workflow Discipline

**Rule.** Every feature and bug fix lands through the test-first loop: write
a failing test that names the intended behaviour, make it pass with the
smallest credible change, then refactor. Bug fixes land *with* the
regression test that would have caught them. The `superpowers:test-driven-development`
skill is the default for implementation work.

**Why.** Test-first locks the specification before the implementation can
cheat it; test-after retrofits the spec to whatever the code does. Bug
fixes without regression tests are open invitations for the bug to return.
TDD is also the tightest feedback loop for agent work — a red test makes
the success criterion machine-checkable.

**How to apply.** Greenfield: the first feature's first commit is a failing
test. Adoption: introduce TDD for new features only; do not retro-fit,
but every bug fix from today forward lands with a regression test.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P10.1 | CULTURAL | CLAUDE.md | CLAUDE.md documents test-first as the default workflow and names `superpowers:test-driven-development` | Add a "Workflow" section pointing at the skill |
| P10.2 | BEHAVIORAL | docs/wiki/testing.md | Every directory under `src/` with production code has a corresponding test file (unit ring coverage) | Audit walks `src/` and expects a matching `tests/test_<module>.py` or similar; orphan modules surface in the report |
| P10.3 | CULTURAL | docs/wiki/testing.md | Bug-fix commits land with a regression test in `tests/regressions/` | Audit scans last 50 merged PRs tagged `bug`/`fix`; reports PRs missing a regression-test delta as a warning |
| P10.4 | STRUCTURAL | docs/wiki/testing.md | Test names describe behaviour, not implementation (e.g. `test_merges_when_all_checks_pass` not `test_merge_function`) | Enforce via a test-name linter or review rubric; audit samples names and flags ones matching `test_<funcname>$` |
| P10.5 | BEHAVIORAL | docs/wiki/testing.md | Test files use the Arrange / Act / Assert structure visibly | Prefer factories + one assertion per test; multi-assert tests are a smell |

## Consequences

**Positive**
- New repos get a one-command (`make audit`) readout of their conformance.
- Adoption path is measurable: the audit's pass count moves PR by PR.
- Principles have one home (`ADR-0044`) — no more "is it in CLAUDE.md or
  docs/wiki or an ADR?" ambiguity.
- ADR tables and audit code stay in lockstep because the code reads the ADR
  at runtime; a dangling `check_id` fails the audit.
- Self-documenting: every check cites its source, so remediation hints point
  at the real decision record, not a paraphrase.
- Self-observing: audit/init runtime failures surface through the same
  Sentry filter the principles require, so the tooling eats its own
  dogfood and runtime regressions feed back into the learning loop.

**Negative**
- Any change to a principle now requires an ADR edit, not just a doc tweak.
  This is the intended friction, but it is friction.
- Audit is Python-only today; polyglot repos (e.g. a Node frontend with a
  Python backend) only get the Python-side checks until checks are generalised.
- CULTURAL checks under-cover reality — an audit can say "no main commits in
  the recent log" but cannot verify the remote branch-protection setting.
  The `make init` prompt compensates by asking the user to confirm.

**Neutral**
- P6 (agents/loops/labels) is only meaningful for orchestration-shaped
  projects. Non-orchestration repos will see P6 as "N/A" rather than FAIL.
- The bar is 10 principles today; the list is expected to grow. Adding P11
  is an ADR amendment, not a code refactor.
- Several checks (P2.8 anaemic-type detection, P2.9 ubiquitous-language,
  P10.2 orphan-module coverage) are heuristic — the audit reports them as
  warnings even when the numeric threshold is met, so reviewers apply
  judgement rather than treating a green audit as proof of correctness.

## Alternatives considered

**Inline principles in `CLAUDE.md`.** Rejected because `CLAUDE.md` is a
table of contents, not a decision log. Principles are decisions and belong
in the ADR directory alongside the other architectural commitments.

**YAML sidecar for check tables (`0044-principles.checks.yaml`).**
Rejected because the sidecar splits the rule from its rationale — a reader
of the ADR sees only half the contract. Markdown tables are fiddly to parse
but not prohibitively so, and the audit has a sharp schema: five columns,
first row is headers.

**Generate principles from scanning the HydraFlow repo.** Rejected because
it inverts the direction of authority. Principles should drive the code, not
the other way around. An ADR that merely describes existing code is a
snapshot that rots.

## Related

- [CLAUDE.md](../../CLAUDE.md) — the table of contents this ADR formalises
- [ADR-0001](0001-five-concurrent-async-loops.md) — five concurrent async loops (P6)
- [ADR-0002](0002-labels-as-state-machine.md) — labels as the state machine (P6)
- [ADR-0003](0003-git-worktrees-for-isolation.md) — worktree isolation (P5)
- [ADR-0021](0021-persistence-architecture-and-data-layout.md) — persistence layout (informational)
- [ADR-0022](0022-integration-test-architecture-cross-phase.md) — MockWorld harness (P3)
- [ADR-0029](0029-caretaker-loop-pattern.md) — `BaseBackgroundLoop` (P6)
- [ADR-0032](0032-per-repo-wiki-knowledge-base.md) — repo wiki (P7)
- `scripts/hydraflow_audit/` — the audit tool that reads this ADR's tables
- `scripts/hydraflow_init/` — the prompt emitter that reads the audit's report
