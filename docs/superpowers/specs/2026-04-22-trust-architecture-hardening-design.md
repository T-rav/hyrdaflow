# Trust Architecture Hardening — testing the tests + attribution

- **Status:** Draft
- **Date:** 2026-04-22
- **Author:** T-rav

## How to read this

This spec establishes the shared framing for a trust-hardening initiative
with three subsystems: an adversarial skill corpus (plus a learning loop
that grows it), contract tests for the `MockWorld` fake adapters, and a
staging-red attribution bisect loop. It fixes scope, fail-mode contracts,
CI placement, and shared infrastructure — but **not** implementation
sequencing. Three separate plans follow in `docs/superpowers/plans/2026-04-22-*.md`,
one per subsystem. When they disagree with the spec, the spec wins and the
plan must be updated.

## 1. Context

HydraFlow's current trust architecture rests on three pillars:

- **Five concentric test rings** — unit, integration, scenario, E2E, regression
  — per `ADR-0044` P3 (`docs/adr/0044-hydraflow-principles.md`) and
  `ADR-0022:MockWorld` (`docs/adr/0022-integration-test-architecture-cross-phase.md`).
- **`MockWorld`-driven scenarios** with stateful fakes
  (`tests/scenarios/fakes/fake_github.py:FakeGitHub`,
  `tests/scenarios/fakes/fake_git.py:FakeGit`,
  `tests/scenarios/fakes/fake_docker.py:FakeDocker`,
  `tests/scenarios/fakes/fake_llm.py:FakeLLM`,
  `tests/scenarios/fakes/fake_hindsight.py:FakeHindsight`). Scenarios are
  release-gating per P3.10.
- **RC promotion gate** per `ADR-0042:StagingPromotionLoop`
  (`docs/adr/0042-two-tier-branch-release-promotion.md`): `staging → rc/* → main`
  only advances on a green RC promotion PR, enforced by
  `.github/workflows/rc-promotion-scenario.yml`.
- **Principles audit** per `ADR-0044:HydraFlow Principles` codifies the
  rules of the shape and makes conformance measurable.

Three gaps remain:

1. **The post-implementation skill chain is LLM-based and has no
   adversarial harness.** `src/diff_sanity.py`, `src/scope_check.py`,
   `src/test_adequacy.py`, and `src/plan_compliance.py` are prompt-driven
   heuristics that catch (or miss) bad diffs. Today nothing verifies that a
   prompt edit, a model swap, or a refactor has not silently regressed any
   of them. A silent regression here degrades every PR the system ships.
2. **`MockWorld` fakes are the foundation of the scenario ring, but
   nothing verifies they still describe real-service behavior.** When
   `gh`, `git`, `docker`, or the Claude CLI change shape, the fakes keep
   passing while production drifts. Contract/cassette drift is undetected.
3. **When a batch of PRs merges to staging and the RC promotion goes red,
   attribution is manual.** The RC PR summary names the failing scenario
   but not the culprit commit from among potentially dozens of PRs merged
   since the last green RC. An operator bisects by hand.

**Stance.** These are not "more test rings." They are tests *of* the
existing rings plus an operational feedback loop. The spec calls the
category "trust-architecture hardening" rather than "a new test tier"
precisely because each subsystem guards an existing capability — the
skill chain, the fake library, and the RC gate — rather than adding a
new one.

## 2. Scope

**In scope.**

- Adversarial skill corpus at `tests/trust/adversarial/` plus a learning
  loop (`CorpusLearningLoop`) that proposes new cases from production
  escapes.
- VCR-style contract tests for `FakeGitHub`, `FakeGit`, `FakeDocker` with
  committed YAML cassettes under `tests/trust/contracts/cassettes/`.
  Stream-replay samples for `FakeLLM` under
  `tests/trust/contracts/claude_streams/`. A `ContractRefreshLoop` that
  re-records cassettes on a weekly cadence.
- `StagingBisectLoop` that attaches to `StagingPromotionLoop`'s RC-red
  event (see prerequisite in §8), runs `git bisect run make scenario`
  in a dedicated worktree, and files a `hydraflow-find` issue naming the
  culprit commit.

**Out of scope — and staying out.**

- **Mutation testing.** User declined; not a goal.
- **Rollback drill workflow.** Deferred; no `tests/trust/drills/` tree.
- **Contract tests for `FakeHindsight`.** The Hindsight API is young and
  in-house; revisit once it stabilizes.
- **Property tests on the label state machine.** Tracked separately.
- **Visual regression on the dashboard UI.** Out of scope for this
  initiative.

## 3. Trust-model constraint

Per-PR CI stays lightweight. New trust gates land on
`.github/workflows/rc-promotion-scenario.yml`, **not**
`.github/workflows/ci.yml`. Rationale: `ADR-0042` gates releases on the
RC promotion PR, so the expensive checks belong at that boundary; PRs to
`staging` must iterate fast because `staging` is the integration branch
and agent PR volume is high.

This is a deliberate rescoping. The current `ci.yml` runs `scenario` and
`regression` on every PR — a holdover from the single-tier branch model
that `ADR-0042` replaced. Realigning those jobs is tracked separately and
is **not** a prerequisite for this spec; the new trust gates respect the
ADR-0042 placement policy from day one regardless of whether the
existing misplacements get cleaned up first.

Per `ADR-0044` P5 (CI and branch protection), CI and local gates must not
diverge. `make trust` runs locally and in `rc-promotion-scenario.yml` with
the same exit codes.

## 4. Subsystems

### 4.1 Adversarial skill corpus (+ learning loop)

**Purpose.** Detect silent regressions in the four post-implementation
skills (`src/diff_sanity.py`, `src/scope_check.py`,
`src/test_adequacy.py`, `src/plan_compliance.py`) whenever prompts, model
settings, or the skill-dispatch path changes. Each case in the corpus is
a diff that a named skill **must** flag; the harness is red if the skill
lets it through.

#### v1 — hand-crafted corpus

Layout:

```
tests/trust/adversarial/
├── __init__.py
├── test_adversarial_corpus.py     # harness (iterates cases/)
└── cases/
    └── <case_name>/
        ├── before/                # pre-diff snapshot subset
        ├── after/                 # post-diff snapshot subset
        ├── expected_catcher.txt   # one of: diff-sanity | scope-check | test-adequacy | plan-compliance
        └── README.md              # human-readable description + keyword
```

- Each `case_name` directory is the *minimum* subset of a repo needed to
  reproduce the bug class — typically 1–4 files in each of `before/` and
  `after/`. Harness synthesizes the diff as `git diff before/ after/`
  equivalent.
- `expected_catcher.txt` contains exactly one of the four skill names,
  newline-terminated.
- `README.md` describes the bug class in one paragraph and names at least
  one **keyword** the skill's RETRY reason must contain (so the assertion
  is stronger than "skill said RETRY"; it also says "skill saw the right
  thing").

**Harness.** `tests/trust/adversarial/test_adversarial_corpus.py`
parameterizes over every directory under `cases/`. For each case:

1. Build the diff from `before/` and `after/`.
2. Invoke the real skill prompt via the production dispatch path
   (`src/base_runner.py`'s skill invocation — or the smallest thin shim
   that calls the same prompt-build + parse functions used in
   production; the plan picks the shim surface).
3. Assert the skill named in `expected_catcher.txt` returns RETRY.
4. Assert the RETRY reason contains the keyword listed in `README.md`
   (case-insensitive substring match).

**v1 seed corpus — minimum coverage.** The implementer seeds ~20–25
cases spanning, at minimum:

- Missing test for a new public function or class (→ `test-adequacy`).
- Renamed symbol without callsite update (→ `diff-sanity`).
- NOT-NULL / required-field violation in a Pydantic model update
  (→ `diff-sanity`).
- `AsyncMock` used where a stateful fake in `tests/scenarios/fakes/`
  already exists (→ `test-adequacy`).
- Scope-creep diff: an unrelated module edited alongside the target
  change (→ `scope-check`).
- Plan-divergence diff: implementation contradicts a step in the
  referenced plan (→ `plan-compliance`).

v1 ships first as an RC gate (`make trust-adversarial` → wired into
`rc-promotion-scenario.yml`).

#### v2 — `CorpusLearningLoop`

`src/corpus_learning_loop.py`, a new `BaseBackgroundLoop`, watches for
**escape signals** — bugs that merged to `main` despite the skill gate —
and proposes a new case for each.

**Escape-signal source (default).** `hydraflow-find` issues tagged with
the `skill-escape` label. Alternative sources are listed in §9.

**Per-escape workflow.**

1. Read the escape issue body and the reverted commit (or the fix PR)
   from the linked references.
2. Dispatch a sub-agent prompt that synthesizes a minimal
   `before/after` pair reproducing the class of bug, picks the
   `expected_catcher`, and drafts the `README.md`.
3. Write a new case directory under `tests/trust/adversarial/cases/`
   and open a PR adding it.
4. PR is reviewed and merged by a human — loop does **not** auto-merge.
   An un-reviewed auto-added case would expand the gate without scrutiny
   and erode trust in the corpus itself.

**Five-checkpoint wiring** per `docs/agents/background-loops.md`:

1. `src/service_registry.py` — dataclass field + `build_services()`
   instantiation.
2. `src/orchestrator.py` — entry in `bg_loop_registry` dict.
3. `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`.
4. `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`.
5. `src/config.py` — interval `Field` + `_ENV_INT_OVERRIDES` entry.

LLM model override (per `docs/agents/background-loops.md`): add
`corpus_learning_model` to `src/config.py` with env var
`HYDRAFLOW_CORPUS_LEARNING_MODEL`, default `sonnet` (case synthesis is a
structured summarization task; `opus` is not justified).

**Rollout.** v1 ships first as an RC gate. v2 ships later as a
caretaker loop per `ADR-0029`. The plans split the two subsystems so v2
can slip without blocking v1.

### 4.2 Contract tests for fakes

**Purpose.** Detect drift between `tests/scenarios/fakes/*` and the real
adapters they stand in for. A passing scenario suite means nothing if the
fake speaks a dialect the real service no longer accepts.

#### Cassette layout

```
tests/trust/contracts/
├── __init__.py
├── test_fake_github_contract.py
├── test_fake_git_contract.py
├── test_fake_docker_contract.py
├── test_fake_llm_contract.py
├── cassettes/
│   ├── github/
│   │   └── <interaction>.yaml
│   ├── git/
│   │   └── <interaction>.yaml
│   └── docker/
│       └── <interaction>.yaml
└── claude_streams/
    └── <sample>.jsonl
```

**Cassette schema (shared across `github/`, `git/`, `docker/`).** YAML,
one file per interaction:

```yaml
adapter: github | git | docker
interaction: <short-slug>
recorded_at: 2026-04-22T14:07:03Z
recorder_sha: <git sha of HydraFlow when recording>
fixture_repo: <test-scoped repo or container image pinned for this cassette>
input:
  command: gh pr create ...            # or: git commit -m ..., docker run ...
  args: [...]                          # argv after the command
  stdin: null | "<string>"             # optional
  env: {}                              # only non-default env overrides
output:
  exit_code: 0
  stdout: |
    ...
  stderr: |
    ...
normalizers:                           # fields the replay side skips byte-exact
  - pr_number
  - timestamps.ISO8601
  - sha:short
```

**`normalizers` list** names fields that must match **shape** but not
exact bytes — PR numbers, ISO timestamps, short SHAs. The harness runs
the normalizers on both sides before comparing. Without normalizers the
cassette would rot the moment anything auto-increments.

#### Two-sided assertion harness

Each `test_fake_<adapter>_contract.py` runs two sides per cassette:

**Replay side (every RC gate run).** Feed the cassette's `input` into
the corresponding fake from `tests/scenarios/fakes/`. Assert the fake's
output matches the cassette's `output` field-by-field, after
normalizers. This catches *fake regressions*: the fake no longer
matches the recorded real-service behavior.

**Freshness side (`ContractRefreshLoop`, weekly).** Invoke the **real
adapter** — `gh`, `git`, or `docker run <pinned-image>` — against the
cassette's `fixture_repo` (or scratch container). Diff the real
output against the cassette. **Diffs do not fail the gate.** Instead,
the loop files a `hydraflow-find` issue with label `cassette-drift`
listing each changed field. The cassette remains authoritative until a
human rotates it through the refresh PR (below).

Rationale for non-blocking freshness: `gh` CLI releases, `git`
behavior, and `docker` output are not change-controlled by us. A
third-party version bump must be a signal, not a page.

#### `FakeLLM` is different

The real `claude` CLI is non-deterministic; there is no cassette we can
diff exactly. Instead:

- Record stream samples: `claude ... --output-format stream-json` run
  against a short, stable prompt, saved as `<sample>.jsonl` under
  `tests/trust/contracts/claude_streams/`.
- Replay side asserts that `src/stream_parser.py`'s parser consumes
  every sample without error and emits the expected tool-use /
  text-block boundaries.
- Freshness side is coverage-shaped, not output-shaped: the refresh
  loop re-records a fresh sample; if the parser errors on the new
  sample, that's a hard signal the Claude streaming protocol changed,
  and it files a `hydraflow-find` with label `stream-protocol-drift`.

#### Adapters covered in v1

| Fake | Real adapter | Fixture target |
|---|---|---|
| `FakeGitHub` | `gh` CLI | A disposable test repo (throwaway; not the HydraFlow repo). |
| `FakeGit` | `git` CLI | A fixture repo under `tests/trust/contracts/fixtures/git_sandbox/`. |
| `FakeDocker` | `docker run` | A pinned trivial image (e.g. `alpine:3.19`). |
| `FakeLLM` | `claude` CLI streaming mode | Short prompts; samples committed as `.jsonl`. |

#### `ContractRefreshLoop`

`src/contract_refresh_loop.py`, a new `BaseBackgroundLoop`, weekly
cadence.

- Re-records every cassette and stream sample against live services.
- Commits updates on a branch (`contract-refresh/YYYY-MM-DD`).
- Opens a PR for human review; does **not** auto-merge. Cassettes are
  the contract; rotating them silently would defeat the point.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `contract_refresh_interval`, default `604800` seconds (7 days).
No per-worker LLM model override — the refresh loop does not call the
LLM beyond recording streams.

**Why commit cassettes to the repo.** Cassettes are small (< 10 KB
each); no secrets (everything records against disposable test repos and
pinned images); review-visible via `git diff` on the refresh PR.
Committing them matches the rest of HydraFlow's "state in config,
history in git" stance (`ADR-0044` P1 Documentation Contract — the
wiki/ADR spine as the source of truth for knowledge, and git as the
audit log).

### 4.3 Staging-red attribution bisect

**Purpose.** Close the attribution gap between "RC is red" and "here is
the culprit PR" so the operator sees a commit, not a bisect assignment.

**`StagingBisectLoop`** — `src/staging_bisect_loop.py`, a new
`BaseBackgroundLoop`.

**Trigger.** The loop subscribes to a new `rc_red` event emitted by
`src/staging_promotion_loop.py:StagingPromotionLoop._handle_open_promotion`
when CI fails on an RC PR. See §8 for the prerequisite — today the
method files a `hydraflow-find` issue but does not emit an event; the
plan adds the emission.

**On fire.**

1. Read `last_green_rc_sha` from `src/state_tracker.py:StateTracker`
   (the plan specifies which key — `staging_promotion_loop` tracker or a
   sibling). Read `current_red_rc_sha` from the RC PR's head.
2. In a dedicated worktree under
   `<data_root>/<repo_slug>/bisect/<rc_ref>/` (`ADR-0021` P9
   persistence):
   - `git bisect start <current_red_rc_sha> <last_green_rc_sha>`
   - `git bisect run make scenario`
3. Parse bisect output. First-bad commit = the culprit.
4. File a `hydraflow-find` issue via
   `src/pr_manager.py:PRManager.create_issue`:
   - Title: `RC-red attribution: PR #{N} introduced scenario regression`
     (where `N` is the PR number containing the culprit commit, resolved
     by `gh api repos/.../commits/<sha>/pulls`).
   - Body: culprit SHA, failing scenario test names (parsed from
     `make scenario` output), the RC PR URL, a `git show <sha> --stat`
     summary, and the bisect log.
   - Labels: `hydraflow-find`, `rc-red-attribution`.
5. Clean up the bisect worktree (`git worktree remove --force`).

**Idempotency.** Use `src/dedup_store.py:DedupStore` keyed by
`(rc_pr_number, current_red_rc_sha)` — a re-fire for the same RC does
not double-file. If the repo has advanced past the bisect range (e.g.
the `last_green_rc_sha` no longer exists because of a rebase), skip
with a warning log — idempotent no-op, do not fail the loop.

**Error handling.** Bisect harness failures (bisect itself errors,
`make scenario` errors for a reason unrelated to the regression) log at
`warning` per `ADR-0044` P7 Sentry rules and file a `hydraflow-find`
with label `bisect-harness-failure`. This keeps genuine scenario
regressions distinguishable from harness bugs in the issue tracker.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `staging_bisect_interval`. The loop is event-driven, not
polling, so the interval acts as a watchdog poll to detect missed
events; default `600` seconds. No per-worker LLM model override (no
LLM call).

## 5. Shared infrastructure

**Directory tree:**

```
tests/trust/
├── __init__.py
├── adversarial/
│   ├── __init__.py
│   ├── test_adversarial_corpus.py
│   └── cases/
│       └── <case_name>/...
└── contracts/
    ├── __init__.py
    ├── test_fake_github_contract.py
    ├── test_fake_git_contract.py
    ├── test_fake_docker_contract.py
    ├── test_fake_llm_contract.py
    ├── cassettes/
    │   └── {github,git,docker}/*.yaml
    ├── claude_streams/*.jsonl
    └── fixtures/
        └── git_sandbox/
```

No `drills/` tree — rollback drills are out of scope (§2).

**`Makefile` targets** (added to the existing file):

- `make trust-adversarial` — runs `pytest tests/trust/adversarial/`.
- `make trust-contracts` — runs `pytest tests/trust/contracts/`.
- `make trust` — runs both, in order. Used by the RC workflow and
  locally.

**CI wiring.** Add a new job `trust` to
`.github/workflows/rc-promotion-scenario.yml` that runs `make trust`.
Failing `trust` fails the RC promotion PR; per ADR-0042 the promotion
loop does not merge on red.

**Issue filing.** All three subsystems file `hydraflow-find` issues via
the existing `src/pr_manager.py:PRManager.create_issue` method. Do not
reinvent issue filing; do not introduce a parallel dedup layer —
`src/dedup_store.py:DedupStore` already provides idempotency.

## 6. Error handling & fail-mode table

| Gate | Failure mode | Blocks RC? | Files issue? | Label |
|---|---|---|---|---|
| `adversarial` corpus | A skill fails to flag a case | Yes | Only on CI-red retry exhaustion (standard path) | `hydraflow-find`, `skill-regression` |
| `contracts` replay | Fake output diverges from cassette | Yes | Yes (on CI-red retry exhaustion) | `hydraflow-find`, `fake-drift` |
| `contracts` freshness (refresh loop) | Real adapter output diverges from cassette | No | Yes | `hydraflow-find`, `cassette-drift` |
| `contracts` freshness (stream parser) | Parser errors on a fresh Claude stream | No | Yes | `hydraflow-find`, `stream-protocol-drift` |
| `StagingBisectLoop` | Bisect succeeds, culprit found | N/A (after the fact) | Yes | `hydraflow-find`, `rc-red-attribution` |
| `StagingBisectLoop` | Bisect harness itself errors | N/A | Yes | `hydraflow-find`, `bisect-harness-failure` |
| `StagingBisectLoop` | Bisect range invalid (repo moved on) | N/A | No — warning log only | — |

## 7. Testing — how we test the trust-hardening itself

The harnesses under `tests/trust/` are the *gate runners*. They need
their own unit tests, separately, so a bug in a gate runner surfaces
through the normal `make test` path rather than through a silent
false-negative on the RC.

**Unit tests (under `tests/`, not `tests/trust/`):**

- `tests/test_adversarial_corpus_harness.py` — harness parameterization,
  case-directory parsing, `expected_catcher.txt` validation, keyword
  assertion. Run against synthetic fake cases, not the real corpus.
- `tests/test_contract_cassette_schema.py` — cassette YAML schema
  validation, normalizer application.
- `tests/test_contract_replay_harness.py` — replay harness behavior on
  synthetic cassette + synthetic fake.
- `tests/test_staging_bisect_loop.py` — loop behavior with a `FakeGit`
  that fakes the bisect process; covers the idempotency path, the
  invalid-range skip, and the harness-failure path.
- `tests/test_corpus_learning_loop.py` — escape-signal detection,
  sub-agent dispatch (mocked), PR opening (mocked).
- `tests/test_contract_refresh_loop.py` — refresh-and-PR flow (mocked
  external CLIs).

**Loop-wiring completeness.** `tests/test_loop_wiring_completeness.py`
(existing) must gain entries for `CorpusLearningLoop`,
`ContractRefreshLoop`, and `StagingBisectLoop`. All five checkpoints
per loop; missing any entry is a hard test failure per
`docs/agents/background-loops.md`.

**End-to-end per subsystem.**

- `tests/trust/adversarial/test_adversarial_corpus.py` runs against the
  committed seed corpus. Synthetic **good** inputs — a case deliberately
  designed **not** to trip any skill — live alongside the regular cases,
  flagged in `expected_catcher.txt` with the sentinel `none`, and are
  asserted to pass through all four skills without a RETRY.
- `tests/trust/contracts/` includes at least one cassette per adapter in
  the initial commit, so the replay path is exercised from day one.
- `tests/test_staging_bisect_loop.py` includes an E2E variant that
  drives a three-commit fixture repo end-to-end through the bisect,
  asserting the correct culprit is identified and the issue title
  matches.

## 8. Dependencies / prerequisites

**Existing, already in the tree.**

- `src/base_background_loop.py:BaseBackgroundLoop` — loop base class.
- `src/staging_promotion_loop.py:StagingPromotionLoop` — subsystem §4.3
  hooks here.
- `src/pr_manager.py:PRManager.create_issue` — issue filing.
- `src/dedup_store.py:DedupStore` — idempotency.
- `src/state_tracker.py:StateTracker` — `last_green_rc_sha` read
  (subsystem §4.3).
- `src/base_runner.py` — skill dispatch path (subsystem §4.1 harness).
- `src/diff_sanity.py`, `src/scope_check.py`, `src/test_adequacy.py`,
  `src/plan_compliance.py` — the four post-impl skills under test.
- `src/stream_parser.py` — Claude-stream parser (subsystem §4.2
  replay side for `FakeLLM`).
- `tests/test_loop_wiring_completeness.py` — existing wiring enforcer.

**Prerequisite the plan must add.**

- `src/staging_promotion_loop.py:StagingPromotionLoop` does not today
  emit an `rc_red` event — it files a `hydraflow-find` issue directly
  in `_handle_open_promotion`. The subsystem §4.3 plan must add an
  event emission (the plan picks the mechanism: new method on the loop
  that `StagingBisectLoop` can subscribe to, a shared event bus, or —
  simplest — a state-tracker field `last_rc_red_sha` that
  `StagingBisectLoop` polls). This is a small surface addition, not a
  refactor; call it out as a prerequisite in the subsystem §4.3 plan's
  first task.
- `last_green_rc_sha` is not persisted today. The subsystem §4.3 plan
  must add a write to `StateTracker` from `StagingPromotionLoop` on
  each successful promotion (the `"status": "promoted"` return path in
  `_handle_open_promotion`).

**Out-of-tree dependencies.**

- `gh` CLI, `git`, `docker` must be available in the RC workflow
  environment (already true — the existing scenario job uses `gh` and
  `git`; `docker` is present on GitHub-hosted runners).
- Test-scoped GitHub repo for `FakeGitHub` cassettes. The refresh loop
  requires a throwaway repo. The subsystem §4.2 plan must specify
  which (options: a dedicated `hydraflow-contracts-sandbox` repo
  under the HydraFlow GitHub org, or an ephemeral fork spun up by the
  loop).

## 9. Open questions / deferred decisions

1. **Cassette rotation cadence.** Weekly default in §4.2. `gh` CLI is
   stable enough that weekly may be noisy; monthly is plausible.
   Revisit after the first two refresh cycles.
2. **Learning-loop v2 escape-signal source.** Three options:
   - **Default:** a dedicated `skill-escape` label added to
     `hydraflow-find` issues when a human identifies a PR bug that
     should have been caught. Explicit, low false-positive.
   - Generic `hydraflow-find` label without `skill-escape`. Too noisy
     — catches non-skill issues.
   - Reverted-commit detection (watch for `Revert "..."` merges to
     `main`). Catches cases humans forget to label but false-positives
     on intentional reverts.
   Ship with `skill-escape` as the default; leave a config knob
   `corpus_learning_signal_label` so the decision can flip without a
   code change.
3. **Corpus size budget.** When do we prune old cases that a skill has
   never regressed on? TBD. Default: **grow forever in v1**. Revisit
   if the corpus crosses 200 cases or the gate runtime crosses 5
   minutes.
4. **Stream-sample prompt stability.** The Claude stream sample uses a
   short, stable prompt so repeated recordings compare. The subsystem
   §4.2 plan picks the exact prompt. Revisit if Anthropic changes
   stream-json schema in a way that invalidates committed samples.
5. **Bisect runtime cap.** `make scenario` currently takes ~5 minutes.
   A bisect over 16 commits is ~20 minutes. Above some threshold the
   bisect is more disruptive than useful. TBD — the plan specifies a
   runtime cap (default suggestion: 45 minutes; skip with a warning
   beyond that).

## 10. Related

- `ADR-0001` — Five concurrent async loops (context for existing loop
  count; the three new loops here are `BaseBackgroundLoop` auxiliaries,
  not pipeline loops).
- `ADR-0022` — MockWorld integration-test architecture. Subsystem §4.2
  guards the fakes this ADR introduced.
- `ADR-0029` — Caretaker loop pattern. All three new loops follow it.
- `ADR-0042` — Two-tier branch model + RC promotion. The promotion PR
  is where §4.1 v1 and §4.2 replay gates land.
- `ADR-0044` — HydraFlow Principles. P3 (testing rings, MockWorld), P5
  (CI and branch protection), P8 (superpowers skills) are load-bearing
  here; the audit table rows these checks map to live in that ADR.
