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

## 3. Constraints

### 3.1 Trust-model constraint (CI placement)

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

### 3.2 Autonomy stance (load-bearing)

Every loop in this initiative terminates in one of two outcomes: **a fix
lands automatically**, or **the system escalates to a human**. There is
no "waits for human review" default on the happy path.

- **Happy path = no humans.** Self-validation, agent review, quality
  gates, and auto-merge run in sequence. A human sees results through
  the normal factory channels (dashboard, merged PR list) — not through
  an inbox of pending approvals.
- **Failure path = escalation, not pause.** When a loop cannot close its
  own workflow within a bounded retry budget (default 3 attempts per
  cycle), it files a `hitl-escalation` issue labeled with the failure
  class. The loop records the escalation and moves on — it does not
  spin waiting.
- **"Fire" criteria for HITL.** Only true safety trips pull a human in:
  - A guardrail breached (e.g., a second auto-revert in one RC cycle —
    see §4.3).
  - Self-validation fails unrecoverably (e.g., a synthesized corpus
    case won't even parse).
  - A primary repair attempt created a *new* red the loop cannot
    resolve.
- **Review is not bypassed — humans are.** Refresh-loop PRs,
  corpus-learning PRs, and auto-revert PRs all flow through the
  standard agent-reviewer + quality-gate path. `src/reviewer.py`
  enforces rigor; `make quality` enforces correctness; auto-merge
  happens only on green. This stance skips *human approval*, not
  *review itself*.

This stance overrides individual subsystem descriptions. If §4.1–§4.3
appear to describe a human gate anywhere on the happy path, that is a
drafting bug — treat §3.2 as authoritative and auto-merge with
guardrails.

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
- `expected_catcher.txt` contains exactly one registered post-impl skill
  name (read from the live skill registry at harness start —
  `src/skill_registry.py` or equivalent), newline-terminated, plus the
  sentinel `none` for pass-through cases (see §7 "End-to-end per
  subsystem"). Adding a new post-impl skill does not require a spec
  edit; the harness validates against whatever the registry returns.
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
the `skill-escape` label. The label is not hard-coded: a config knob
`corpus_learning_signal_label` (default `skill-escape`) lets operators
flip to a different label without a code change. Alternative source
mechanisms are listed in §9.

**Per-escape workflow.**

1. Read the escape issue body and the reverted commit (or the fix PR)
   from the linked references.
2. Synthesize a minimal `before/after` pair reproducing the class of
   bug, pick the `expected_catcher`, and draft the `README.md`. **The
   plan picks the synthesis mechanism** — two viable options: (a) the
   loop dispatches an LLM call in-process through `src/base_runner.py`
   (lower latency, self-contained), or (b) the loop files a routing
   issue with label `corpus-synthesis-task` and lets the standard
   implement phase handle it (higher latency, reuses existing
   infrastructure). Either is consistent with §3.2.
3. **Self-validation gate.** Before opening a PR, the loop verifies:
   1. The synthesized `before/` + `after/` parses (Python syntax, no
      import errors).
   2. Lint passes on the synthesized files (`make lint-check` scoped
      to the new case directory).
   3. The named `expected_catcher` skill **actually returns RETRY** on
      the synthesized diff with the claimed keyword. A case the loop
      cannot prove flags the right thing is rejected as a
      self-validation failure — the loop does not propose cases it
      cannot stand behind.
4. **Open PR and auto-merge per §3.2.** Cases that pass
   self-validation flow through the standard agent-reviewer +
   quality-gate + auto-merge path. No human approval on the happy
   path.
5. **Escalation.** Self-validation failure 3× on the same escape
   issue → label it `hitl-escalation`, `corpus-learning-stuck`,
   record the three rejected attempts in the issue body, move on.

Rationale for auto-merge: a new corpus case is a new test, not a
production-code change. The self-validation gate proves the case
actually catches what it claims to catch; `make quality` enforces the
usual quality bar. The risk profile is low; holding these PRs for
human review contradicts §3.2.

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

**Freshness side (`ContractRefreshLoop`, weekly).** The refresh loop
is the freshness monitor — see the `ContractRefreshLoop` section below
for the full flow. Summary: it invokes the **real adapter** — `gh`,
`git`, or `docker run <pinned-image>` — against the cassette's
`fixture_repo` (or scratch container) and diffs the real output against
the committed cassette. Diffs do not fail the RC gate; they trigger the
autonomous refresh workflow below. Per §3.2, refresh PRs auto-merge
when the replay side still passes with the new cassette; when it
doesn't, a companion `fake-drift` issue routes repair through the
factory. No human approval on the happy path.

Rationale for non-blocking freshness: `gh` CLI releases, `git`
behavior, and `docker` output are not change-controlled by us. A
third-party version bump is a signal that triggers the autonomous
refresh, not a page that blocks the RC.

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

#### `ContractRefreshLoop` — full caretaker (refresh + auto-repair)

`src/contract_refresh_loop.py`, a new `BaseBackgroundLoop`, weekly
cadence. Per §3.2, the loop is autonomous end-to-end: it detects drift,
repairs both sides of the contract (cassettes and fakes), and merges
the fix. Humans enter only on escalation.

**On fire (weekly).**

1. Re-record every cassette and stream sample against live services.
2. Diff new recordings against committed cassettes. **No diff →
   no-op**, return.
3. **Diff detected.** Commit refreshed cassettes to a branch
   `contract-refresh/YYYY-MM-DD` and open a PR against `staging`.
4. Run contract replay tests against the new cassettes:
   - **Replay passes** → fakes still speak the dialect. This is a
     "cassette-only drift" refresh. PR flows through standard
     agent-reviewer + quality-gate + auto-merge per §3.2.
   - **Replay fails** → a fake diverged. The loop files a companion
     `hydraflow-find` issue with label `fake-drift` naming which
     adapter, which method, which field moved. The factory picks up
     the issue and routes it through the standard implement phase
     (`src/implement_phase.py`); the implementer agent edits
     `tests/scenarios/fakes/fake_*.py` to match the new cassette,
     re-runs contract tests, and lands a fix PR on `staging` that
     auto-merges on green.
5. **Stream-protocol drift.** If `src/stream_parser.py` errors on a
   newly-recorded `claude` stream sample, file a `hydraflow-find`
   with label `stream-protocol-drift`; the factory routes the repair
   through the standard implement phase against
   `src/stream_parser.py` itself.
6. **Escalation.** If the implementer loop fails to close a
   `fake-drift` or `stream-protocol-drift` issue after 3 attempts
   (governed by the existing factory retry budget — the plan picks
   the correct config field, likely `max_issue_attempts` or a
   dedicated `max_fake_repair_attempts`), the issue gets labeled
   `hitl-escalation`, `fake-repair-stuck` (or `stream-parser-stuck`)
   and the `ContractRefreshLoop` stops opening new refresh PRs for
   that adapter until the escalation closes.

**Rationale for auto-repair both sides.** A passing cassette with a
divergent fake is still a red gate — the scenario ring would silently
trust a wrong fake. The loop's responsibility is the full contract
(real output ↔ cassette ↔ fake output); it must close drift on
whichever side broke. Test-infrastructure code (fakes) is lower risk
than production code and fits the §3.2 happy path.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `contract_refresh_interval`, default `604800` seconds (7 days).
No per-worker LLM model override — the loop itself does not call the
LLM; the dispatched implementer uses the standard implementer model.

**Why commit cassettes to the repo.** Cassettes are small (< 10 KB
each); no secrets (everything records against disposable test repos and
pinned images); review-visible via `git diff` on the refresh PR.
Committing them matches the rest of HydraFlow's "state in config,
history in git" stance (`ADR-0044` P1 Documentation Contract — the
wiki/ADR spine as the source of truth for knowledge, and git as the
audit log).

### 4.3 Staging-red attribution + auto-revert

**Purpose.** Close the full loop from "RC is red" to "green RC with the
culprit reverted and a retry issue filed" — without pulling a human in
on the happy path. Per §3.2, the loop reverts the bad commit, routes
the original work back through the factory as a retry, and only pulls a
human in when a safety guardrail trips.

**`StagingBisectLoop`** — `src/staging_bisect_loop.py`, a new
`BaseBackgroundLoop`.

**Trigger.** The loop subscribes to a new `rc_red` event emitted by
`src/staging_promotion_loop.py:StagingPromotionLoop._handle_open_promotion`
when CI fails on an RC PR. See §8 for the prerequisite — today the
method files a `hydraflow-find` issue but does not emit an event; the
plan adds the emission.

**On fire.**

1. **Flake filter.** Before bisecting, re-run the RC gate's
   scenario suite once against the RC PR's head. If the second run
   passes, the red was a flake; log at `warning`, increment a
   `flake_reruns_total` counter in state, and exit. No bisect, no
   revert.
2. **Bisect.** Read `last_green_rc_sha` from
   `src/state/__init__.py:StateTracker` (written by
   `StagingPromotionLoop` on each successful promotion — see §8).
   Read `current_red_rc_sha` from the RC PR's head. In a dedicated
   worktree under `<data_root>/<repo_slug>/bisect/<rc_ref>/`
   (`ADR-0021` P9 persistence):
   - `git bisect start <current_red_rc_sha> <last_green_rc_sha>`
   - `git bisect run` against the RC gate's full scenario command
     set — at minimum `make scenario && make scenario-loops` per the
     current `rc-promotion-scenario.yml` steps. The plan adds a
     dedicated Makefile target (e.g. `make bisect-probe`) that mirrors
     the RC gate's scenario commands so changes to the RC gate
     automatically update what bisect runs. Critical: the bisect
     probe must match the RC gate exactly; a scenario-loops-only
     regression won't bisect if the probe runs `make scenario` alone.
3. **Attribution.** Parse bisect output. First-bad commit = the
   culprit. Resolve the containing PR via
   `gh api repos/.../commits/<sha>/pulls`; call the PR number `N`.
4. **Safety guardrail.** `StateTracker` tracks `rc_cycle_id` and
   `auto_reverts_in_cycle` (count). If `auto_reverts_in_cycle > 0`,
   **do not revert again.** A second red after a first revert means
   either the bisect was wrong or the damage is broader than one PR —
   escalate: file `hitl-escalation`, `rc-red-bisect-exhausted` with
   both bisect logs and stop. Reset the counter only when a green RC
   promotes.
5. **Revert PR.** Create branch
   `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}` off `staging`. Run
   `git revert <culprit_sha>` for a single commit, or
   `git revert -m 1 <merge_sha>` for a merge commit. Push. Open PR
   against `staging` via `src/pr_manager.py:PRManager`:
   - Title: `Auto-revert: PR #{N} — RC-red attribution on <test_name>`
   - Body: culprit SHA, failing scenario test names, RC PR URL,
     `git show <sha> --stat`, bisect log, link to the retry issue
     (step 6).
   - Labels: `hydraflow-find`, `auto-revert`, `rc-red-attribution`.
6. **Retry issue.** Simultaneously file a new `hydraflow-find` issue
   via `src/pr_manager.py:PRManager.create_issue`:
   - Title: `Retry: <original PR title>`
   - Body: link to the reverted PR, full bisect log, failing test
     names, time bounds (start SHA → end SHA → duration).
   - Labels: `hydraflow-find`, `rc-red-retry`. The standard pipeline
     picks up `hydraflow-find` issues; the factory re-does the work.
7. **Auto-merge path (per §3.2).** The revert PR flows through the
   standard agent-reviewer + quality-gate + auto-merge path. The
   retry issue flows through the standard implement/review pipeline.
   No human approval on either happy path.
8. **Outcome verification.** After the revert merges, the next
   `StagingPromotionLoop` cycle creates a fresh RC. The loop waits
   (bounded watchdog: default 2 RC cycles or 8 hours, whichever is
   shorter) for the RC to go green.
   - **Green:** log at `info`, increment
     `StateTracker.auto_reverts_successful`, reset
     `auto_reverts_in_cycle`, close the loop cleanly.
   - **Still red:** escalate `hitl-escalation`,
     `rc-red-post-revert-red` with both the original bisect log and
     the new RC's failure output. The revert stays in place (it
     eliminated one red; pulling it out blindly could introduce
     another).
   - **Watchdog timeout:** escalate
     `hitl-escalation`, `rc-red-verify-timeout` — RC pipeline may be
     stalled for unrelated reasons; the human can disambiguate.
9. **Cleanup.** `git worktree remove --force` on the bisect worktree
   regardless of outcome.

**Revert edge cases.**

- **Merge conflicts on revert.** `git revert` exit non-zero with
  conflicts → abandon immediately, do not attempt auto-resolution.
  Escalate `hitl-escalation`, `revert-conflict` with the conflicting
  paths. Conflicts mean subsequent PRs depend on the culprit; fixing
  requires judgment the loop does not have.
- **Merge commits (squash vs merge commits).** `staging` uses merge
  commits per `ADR-0042` merge-strategy decision. Use
  `git revert -m 1 <merge_sha>` by default. Single-commit PRs
  (uncommon on `staging`) use `git revert <sha>`.
- **Dependent PRs already landed on top.** The revert may break
  follow-up work. Acceptable trade-off: the follow-up can retry via
  its own issue. The revert is the cheapest safe undo; broader
  dependency surgery is a human decision.

**Idempotency.** `src/dedup_store.py:DedupStore` keyed by
`(rc_pr_number, current_red_rc_sha)` — a re-fire for the same RC does
not double-bisect or double-revert. If the repo has advanced past the
bisect range (e.g. `last_green_rc_sha` no longer reachable due to a
rebase), skip with a warning log — idempotent no-op, do not fail the
loop.

**Error handling.** Bisect harness failures (bisect itself errors,
`make scenario` errors for a reason unrelated to the regression) log at
`warning` per `ADR-0044` P7 Sentry rules and file a
`hitl-escalation` with label `bisect-harness-failure`. These are
infrastructure bugs, not scenario regressions, and the loop cannot
self-heal them.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `staging_bisect_interval`. The loop is event-driven, not
polling, so the interval acts as a watchdog poll for missed events;
default `600` seconds. No per-worker LLM model override (no LLM call).

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

Per §3.2, every row resolves to either **autonomous repair** or
**HITL escalation**; "waits for human review" is not a state.

| Gate | Failure mode | Autonomous action | Blocks RC until fix? | Escalates? | Label(s) |
|---|---|---|---|---|---|
| `adversarial` corpus (RC gate) | Skill fails to flag a case | Standard CI-red retry; factory dispatches implementer against the failing skill | Yes | On retry exhaustion | `hydraflow-find`, `skill-regression` → `hitl-escalation`, `skill-repair-stuck` |
| `CorpusLearningLoop` | Synthesized case self-validation fails | Retry per escape issue | No | After 3× on same escape | `hitl-escalation`, `corpus-learning-stuck` |
| `contracts` replay (RC gate) | Fake output diverges from cassette | File `fake-drift`; factory dispatches implementer against `tests/scenarios/fakes/` | Yes | After 3 repair attempts | `hydraflow-find`, `fake-drift` → `hitl-escalation`, `fake-repair-stuck` |
| `ContractRefreshLoop` — cassette-only drift | Real output changed, fakes still green | Refresh PR auto-merges via standard reviewer + quality gates | No | Only if agent reviewer rejects the refresh PR 3× | — / `hitl-escalation`, `contract-refresh-stuck` |
| `ContractRefreshLoop` — cassette + fake drift | Real output changed, fakes broke | Refresh PR lands cassettes; companion `fake-drift` issue routes repair through implement phase | No (the drift itself is a warning signal; repair closes the loop) | After 3 implementer attempts | `hydraflow-find`, `fake-drift` → `hitl-escalation`, `fake-repair-stuck` |
| `ContractRefreshLoop` — stream-parser drift | Parser errors on fresh Claude stream | File `stream-protocol-drift`; factory repairs `src/stream_parser.py` | No | After 3 repair attempts | `hydraflow-find`, `stream-protocol-drift` → `hitl-escalation`, `stream-parser-stuck` |
| `StagingBisectLoop` — flake filter | Second `make scenario` passes | Log and exit; increment `flake_reruns_total` | No | No | — |
| `StagingBisectLoop` — confirmed red | Bisect identifies culprit | Auto-revert PR + retry issue; both auto-merge through standard gates | Yes (until revert merges) | No | `hydraflow-find`, `auto-revert`, `rc-red-attribution`, `rc-red-retry` |
| `StagingBisectLoop` — second revert needed | `auto_reverts_in_cycle > 0` | Stop reverting | Yes | Yes | `hitl-escalation`, `rc-red-bisect-exhausted` |
| `StagingBisectLoop` — revert conflict | `git revert` fails with conflicts | Abandon revert | Yes | Yes | `hitl-escalation`, `revert-conflict` |
| `StagingBisectLoop` — post-revert still red | New RC red after revert landed | Stop reverting; leave revert in place | Yes | Yes | `hitl-escalation`, `rc-red-post-revert-red` |
| `StagingBisectLoop` — watchdog timeout | No green RC within 2 cycles / 8h | Stop waiting | Yes | Yes | `hitl-escalation`, `rc-red-verify-timeout` |
| `StagingBisectLoop` — harness failure | Bisect itself errors | Log at warning | No (unrelated to regression) | Yes | `hitl-escalation`, `bisect-harness-failure` |
| `StagingBisectLoop` — invalid bisect range | `last_green_rc_sha` unreachable (rebase) | Skip with warning log | No | No (idempotent no-op) | — |

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
- `src/state/__init__.py:StateTracker` — `last_green_rc_sha` read
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

## 11. Scope: HydraFlow-self today, managed repos later

### 11.1 Principles as foundation (load-bearing)

This entire initiative rests on `ADR-0044` HydraFlow Principles being
**in place and enforced**. These gates are not freestanding "good
ideas" — they are the concrete guardrails that presuppose a specific
repository shape:

- The adversarial skill corpus (§4.1) presupposes **P3** — the
  post-impl skill chain exists and is dispatched through a known
  registry.
- The contract tests (§4.2) presuppose **P3** — stateful `MockWorld`
  fakes exist under `tests/scenarios/fakes/` that real adapters can
  be diffed against.
- The staging-red bisect (§4.3) presupposes **P4/P5** plus
  `ADR-0042` — branch protection, CI mirroring local gates, a
  two-tier branch model with an RC promotion PR.
- Every subsystem presupposes **P1** (documentation contract) so the
  filed `hydraflow-find` issues have a knowable structure, **P8**
  (skills integration) so the repair-side implement phase has a
  working agent toolchain, and **P9** (persistence layout) so
  caretaker state is stored under a predictable root.

Without these in place, the trust subsystems have nothing to stand
on. Shipping them to a repo that fails `make audit` is cargo-cult
trust — the gate runs but guards a shape that does not exist.

**Today this is enforced by convention, not mechanism.** `make audit`
(`scripts/hydraflow_audit/`) measures conformance; `make init`
(`scripts/hydraflow_init/`) scaffolds missing pieces for greenfield
adoption. Neither is wired as a hard gate: no CI job fails on audit
regression, no onboarding flow refuses to manage a non-conformant
target repo, no caretaker detects principle drift over time. See
§11.3 for the drift detector this initiative adds to the named
follow-on caretaker list.

### 11.2 Per-subsystem extension path

**Today (v1).** Every subsystem in this spec operates on HydraFlow's
own repository: the adversarial corpus tests HydraFlow's own skill
chain, the contract tests guard HydraFlow's own fakes, the bisect loop
watches HydraFlow's own RC promotion. This matches `ADR-0042`'s
negative consequence ("Single-repo scope today; revisit when the
multi-repo factory lands").

**Tomorrow.** HydraFlow's goal is to build and maintain **real
software**, not just itself. As the factory scales to N managed
target repos, the trust architecture must follow — **but only for
repos that pass `make audit` first**. Each subsystem has a per-repo
extension path, with principle conformance as the gate:

| Subsystem | Per-managed-repo extension | Notes |
|---|---|---|
| Adversarial skill corpus (§4.1) | Each managed repo gets its own corpus under its repo slug (e.g. `tests/trust/adversarial/cases/<repo_slug>/`), plus a shared-core corpus for universal bug classes (syntax errors, missing tests, scope creep) | The harness reads the skill registry; no spec change needed to onboard a new repo's corpus |
| Contract tests (§4.2) | Fakes live in HydraFlow (they simulate HydraFlow's adapters), so a single contract suite covers all managed repos. One cassette set is enough | The `ContractRefreshLoop` remains a single caretaker |
| Staging-red bisect (§4.3) | Per managed repo that adopts `ADR-0042`'s two-tier model. The loop runs N instances (one per repo with a staging branch), each bisecting that repo's own promotion | Requires per-repo `last_green_rc_sha` state keys; straightforward with current `StateTracker` repo-slug scoping (`ADR-0021` P9) |

### 11.3 The caretaker fleet — what "lots of caretaking" means

The three loops in this spec are a beachhead. The long-term vision is
a caretaker fleet — each loop a bounded, auditable trust-building job
that keeps some aspect of the system honest. Obvious next caretakers,
out of scope for this spec but worth naming so future plans know
where to slot in. **Priority 0 (foundational)** comes first because it
enforces the principle conformance §11.1 says this whole initiative
rests on:

- **P0 — Principles-drift detector (`PrinciplesAuditLoop`).** Runs
  `make audit --json` on HydraFlow itself and on every managed target
  repo on a cadence (weekly default). Compares the result to a stored
  last-green audit snapshot per repo. Any principle that regressed
  from PASS to FAIL files a `hydraflow-find` issue with label
  `principles-drift` naming the specific check_id (e.g. `P5.7`),
  citing the ADR-0044 row, pointing at the remediation column. On
  new repo onboarding, the loop refuses to install the trust
  subsystems on a repo whose audit has outstanding P1–P5 FAILs —
  foundation has to be in place before the guardrails go up. This
  caretaker closes the loop §11.1 identifies as missing today.
- **Flake tracker** — tallies flakes across RCs, files repair issues
  when the flake rate crosses a threshold per test.
- **Skill-prompt eval** — periodically re-runs the full adversarial
  corpus against current skill prompts to detect slow drift that the
  RC gate's sampled corpus misses.
- **Fake coverage auditor** — inspects each adapter's method surface
  and flags un-cassetted methods.
- **RC wall-clock budget** — tracks RC gate duration and escalates
  when it exceeds a budget (prevents the "scenario gate silently
  bloats to 30 min" failure mode).
- **Managed-repo wiki rot detector** — for every managed repo, checks
  `repo_wiki/<slug>/` entries against actual file paths and symbols
  they cite; files repair issues for broken cites (`ADR-0032`).

Each of these is its own future spec. This spec scopes to the three
subsystems that close the most load-bearing gaps first — skill
regressions (every PR HydraFlow ships), fake drift (every scenario
assertion), RC-red attribution (every release). **The P0 drift
detector is the natural next plan** once this initiative lands, since
the three subsystems' value is conditional on it. Caretakers compound;
we start where the return on trust is highest per unit of
implementation.
