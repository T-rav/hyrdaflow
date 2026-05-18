# Per-Area Review: Quality Gates (slice 5.4)

**Date:** 2026-05-12
**Branch:** audit/area-quality-gates
**Auditor:** Automated (slice 5.4)
**Scope:** CIMonitorLoop + surrounding quality-enforcement infrastructure
(pre-commit hooks, `.github/workflows`, `make quality` / `make quality-lite`,
`make trust-contracts`, arch tests)

---

## Area membership

Per `docs/arch/functional_areas.yml`:

| Members | |
|---|---|
| Loop | `CIMonitorLoop` (1 loop) |
| Related ADRs | ADR-0023, ADR-0035, ADR-0044 |
| Supporting infra | `.githooks/pre-commit`, `.githooks/pre-push`, `.github/workflows/ci.yml`, `.github/workflows/quality.yml`, `.github/workflows/arch-regen.yml`, `make quality`, `make quality-lite`, `make trust-contracts` |

---

## Dimension 1 — Test coverage

### CIMonitorLoop unit tests

File: `tests/test_ci_monitor_loop.py` — 8 tests.

Coverage of observable behavior:

| Scenario | Covered |
|---|---|
| Green CI, no open issue | Yes (`test_green_ci_returns_no_action`) |
| Red CI, issue created | Yes (`test_red_ci_creates_issue`) |
| Red CI, duplicate prevention | Yes (`test_red_ci_does_not_duplicate_issue`) |
| CI recovery closes issue | Yes (`test_ci_recovery_closes_issue`) |
| API error returns error dict | Yes (`test_api_error_does_not_crash`) |
| Dry-run returns None | Yes (`test_dry_run_returns_none`) |
| Close failure retains `_open_issue` for retry | Yes (`test_close_failure_retains_open_issue_for_retry`) |
| `_get_default_interval` reads from config | Yes (`test_default_interval_from_config`) |
| **Restart recovery via `_rehydrate_open_issue`** | **No — untested** |

The `_rehydrate_open_issue` path (calls `list_issues_by_label` on first cycle
to recover `_open_issue` across restarts) has zero unit test coverage. ADR-0029
calls this out as a load-bearing feature: "CIMonitorLoop persists its open-issue
tracker via a GitHub label (`hydraflow-ci-failure`) to survive restarts." Without
a test, a regression in `_rehydrate_open_issue` would silently duplicate the
failure issue on every restart.

### MockWorld scenario tests

`tests/scenarios/test_loops.py` (marker: `scenario_loops`) has two tests:

- Red CI fires, issue created, issue number in state.
- CI recovers, close issued, issue reference cleared.

`tests/scenarios/test_edge.py` (marker: `scenario`) has a trivial
`E11: run_with_loops completes without hanging` test, not a behavioral
assertion.

All meaningful scenario coverage is under `scenario_loops`, which runs:
- In `ci.yml` via `make scenario-loops` (every PR to main/staging where
  code changes). Confirmed via `ci.yml` lines for the scenario job.
- In `rc-promotion-scenario.yml` on every rc/* promotion PR.

### Sandbox e2e tests

**Gap: No dedicated sandbox scenario for CIMonitorLoop.**

`tests/sandbox_scenarios/scenarios/s04_ci_red_then_fixed.py` tests the
ci-fix runner pipeline (a PR with failing CI gets a ci-fix runner dispatched),
not CIMonitorLoop's caretaker behavior (watching main-branch CI status and
filing/closing a bare issue).

Per `docs/standards/testing/README.md`: "New loop or runner: sandbox e2e
required (sNN scenario)." CIMonitorLoop has unit and scenario-loops coverage
but is missing the third layer. This is a procedural compliance gap against
the testing standard.

### Trust contract coverage

`tests/trust/contracts/test_fake_github_contract.py` covers only four methods
via cassette replay: `create_pr`, `merge_pr`, `close_issue`, `close_task`.

CIMonitorLoop uses four port methods on `PRPort`:

| Method | Contract cassette | Notes |
|---|---|---|
| `get_latest_ci_status` | No | Core polling method |
| `list_issues_by_label` | No | Restart-recovery path |
| `create_issue` | No | Issue creation on red CI |
| `post_comment` | No (close_issue covered) | Recovery comment |

None of the methods that CIMonitorLoop actually calls against `PRPort` are
covered by a fake contract cassette. This means drift between `FakeGitHub`
and the real gh CLI for these methods would not be detected until a
sandbox e2e run or live testing.

---

## Dimension 2 — Loop health

### Correctness

`CIMonitorLoop` conforms to all five checkpoint conventions (ADR-0029 /
dark-factory §2):

1. `reraise_on_credit_or_bug(exc)` is called in the CI-status fetch exception
   handler. It is also called in the close-recovery handler. Both are correct.
2. `_enabled_cb` is checked at the top of `_do_work`. Returns `{"status":
   "disabled"}` when disabled.
3. `dry_run` guard returns `None` early.
4. `_get_default_interval` delegates to `config.ci_monitor_interval`.
5. The loop is wired in all four required locations: `orchestrator.py`
   `bg_loop_registry`, `ServiceRegistry` dataclass, `constants.js`
   `BACKGROUND_WORKERS`, and `_INTERVAL_BOUNDS` (60–86400 seconds).
   `test_loop_wiring_completeness.py` enforces these.

The `_rehydrate_open_issue` early-exit guard (`_startup_check_done`) prevents
the label-lookup from running on every cycle. This is correct.

### State management

`_open_issue` is in-memory only. The persistence design (using a GitHub label
as a sentinel, re-discovered on startup via `_rehydrate_open_issue`) is
documented in ADR-0029. The in-memory approach is intentional and acceptable
because the GitHub label is the durable source of truth.

### Error handling

The `except Exception` blocks in `_do_work` are not over-broad: both call
`reraise_on_credit_or_bug(exc)` before logging and returning an error dict.
`tests/regressions/test_issue_6459.py`, `test_issue_6417.py`,
`test_issue_6630.py`, and `test_issue_6768.py` all guard the
`AuthenticationError` / `CreditExhaustedError` propagation requirements.

---

## Dimension 3 — Pre-commit hooks

### `.githooks/pre-commit`

**Correctness**

- `set -euo pipefail` is used correctly. All `git diff` commands use
  `|| true`, preventing pipefail-triggered exits on empty results.
- The multi-line `STAGED_ARCH` variable correctly places `|| true` at the
  end of the subshell.
- `LINES_ADDED` / `LINES_REMOVED` extraction uses `awk '{print $1}'` and
  `$2` on the `git diff --numstat` output. This is correct for the format
  `<added>\t<removed>\t<file>`.
- The `make lint-fix` self-repair path re-stages files via `xargs -I {} git
  add "{}"` which handles most filenames, but paths containing literal `{}`
  or `'` would break. In practice this is an extremely unlikely edge case
  in a Python codebase.

**Arch trigger scope (medium gap)**

`STAGED_ARCH` is built from `'src/*.py'` (shell glob passed as a git pattern).
Git interprets this as a pathspec matching only top-level files directly under
`src/`. Changes to `src/dashboard_routes/*.py`, `src/mockworld/**`, or any
other `src/` subdirectory do NOT trigger the pre-commit `arch-check` step.

The pre-push hook does run `arch-check` unconditionally (except kill-switch),
so the gap is fully mitigated for solo developers. However, automated commits
that bypass pre-push (e.g. `git commit` in CI without a push phase, or bots
that push directly) would skip the arch-check window.

**Test-sludge scope (low gap)**

`STAGED_TESTS` is built from `'tests/test_*.py'` (top-level only). Tests in
`tests/architecture/test_*.py`, `tests/regressions/test_*.py`, and
`tests/scenarios/test_*.py` do not trigger the test-sludge check. If the
sludge patterns are known to appear in non-top-level test files too, the
pattern should widen.

**Unquoted `$STAGED_TESTS` expansion (low)**

Line 53: `STAGED_TESTS_ONE_LINE=$(echo $STAGED_TESTS)` — the unquoted
variable undergoes word splitting and shell glob expansion before `echo`
receives it. File paths containing whitespace or glob characters (`*`, `?`,
`[`) would be mangled. A defensive fix is
`STAGED_TESTS_ONE_LINE=$(printf '%s\n' $STAGED_TESTS | tr '\n' ' ')` or
simply passing the variable through `"$STAGED_TESTS"` and having the Make
target handle multi-line input.

### `.githooks/pre-push`

- Runs `make arch-check` unconditionally (kill-switch:
  `HYDRAFLOW_DISABLE_PRE_PUSH_ARCH_CHECK=1`).
- Runs `make quality-lite` (lint + typecheck + security) on every push.
- Does NOT run `make test` or `make trust-contracts`. This is intentional:
  the full test suite runs in CI, not on every push. Acceptable.

---

## Dimension 4 — CI workflows

### `ci.yml` — coverage

| Check | Trigger | Notes |
|---|---|---|
| Ruff lint/format | Python or CI change on PR/push | Separate `lint` job |
| Pyright typecheck | Python or CI change | Separate `typecheck` job |
| Bandit security | Python or CI change | Separate `security` job |
| Unit tests + coverage (70%) | Python or CI change | `--ignore=tests/regressions` |
| MockWorld scenario + scenario-loops | Python or CI change | `make scenario && make scenario-loops` |
| Regression tests | Python or CI change | `tests/regressions/` job |
| Smoke tests | Python, UI, or CI change | `make smoke` |
| Architecture tests | indirectly via `pytest tests/` | included in unit test job |
| Trust adversarial + contracts | rc/* PRs only (rc-promotion-scenario.yml) | not on every PR |

**Critical gap: `make trust-contracts` only runs on rc/ promotion PRs.** It
is not included in `ci.yml`, `quality.yml`, or the pre-push hook. A PR that
breaks the `FakeGitHub` cassette contract for one of the four methods
CIMonitorLoop depends on would pass all normal PR gates and only fail at the
rc/ promotion stage (if the cassettes cover those methods — which they
currently do not).

### `quality.yml` — coverage

Runs `make quality-lite` then `make quality` then `make smoke` for every
discovered project with a Makefile. `make quality` runs `pytest tests/`
(without `--ignore=tests/regressions`), so architecture tests and trust
contract tests run here.

`quality.yml` and `ci.yml` both trigger on `push: [main, staging]` and
`pull_request: [main, staging]` for code-touching changes. This creates
genuine overlap: `pytest tests/` runs in both pipelines for the same PR.
The duplication is low-risk but doubles CI minutes.

### `arch-regen.yml` — coverage

Triggers on PR when `src/**`, `docs/adr/**`, `docs/arch/**`,
`tests/scenarios/fakes/**`, or `tests/architecture/**` change.

- Validates `functional_areas.yml` schema.
- Runs `make arch-check` (dry-run regeneration).
- Runs `pytest tests/architecture -x --tb=short`.

**Gap: no `push:` trigger.** Arch drift introduced by a direct push to
`staging` (even though project policy forbids it) would not be caught by
`arch-regen.yml`. The `test_curated_drift` test is included in the `ci.yml`
test job's `pytest tests/` sweep, so the test *is* covered, but only if
Python files changed. A YAML-only arch change with no code delta would skip
the ci.yml test job but still trigger arch-regen.yml (docs/arch path is in
its filter). This appears intentionally handled.

### `make quality` target — shell portability

The `quality` target uses a subshell with background jobs and `jobs -p`:

```make
quality: deps lint-ul
	@cd $(HYDRAFLOW_DIR) && ( \
		$(UV) ruff check . ... & \
		...
		for job in $$(jobs -p); do wait $$job || wait_result=1; done; \
		exit $$wait_result; \
	)
```

Make uses `/bin/sh` by default (no `SHELL=bash` override). On macOS,
`/bin/sh` is bash 3.2 so `jobs -p` works. On GitHub Actions
`ubuntu-latest`, `/bin/sh` is also bash (GitHub configures it). This has
been working in CI, so it is not a current breakage — but the absence of an
explicit `SHELL=/bin/bash` in the Makefile means this target is one CI
image change away from breakage on systems where `/bin/sh` is dash.

---

## Dimension 5 — Architecture tests wiring

| Test | Location | Runs in |
|---|---|---|
| `test_curated_drift` | `tests/architecture/` | ci.yml `test` job (pytest tests/), arch-regen.yml |
| `test_functional_area_coverage` | `tests/architecture/` | ci.yml `test` job, arch-regen.yml |
| `test_loop_wiring_completeness` | `tests/` (top-level) | ci.yml `test` job, quality.yml |

All three tests have no pytest markers, so they run in every default `pytest
tests/` invocation. They are not excluded by the `not soak and not docker and
not scenario_loops and not scenario_browser` filter in `pyproject.toml`.

The `real_repo_root` fixture in `tests/architecture/conftest.py` resolves the
repo root from `Path(__file__).resolve().parents[2]`. In the GitHub Actions
checkout this resolves correctly. The `test_curated_drift` test skips
gracefully when `docs/arch/generated/` does not exist yet (new repo bootstrap
path), so it does not produce false failures.

---

## Findings summary

### High severity

| ID | Finding | Location | Recommended fix |
|---|---|---|---|
| QG-H1 | **Missing sandbox e2e scenario for CIMonitorLoop.** Per `docs/standards/testing/README.md`, new loops require all three pyramid layers. The caretaker behavior (watch main-branch CI, file/close issue) has no sandbox scenario. `s04` covers the ci-fix runner, not this loop. | No file yet | Add `tests/sandbox_scenarios/scenarios/s15_ci_monitor_main_branch_red.py` exercising: (1) seeded main-branch CI failure → issue appears in dashboard; (2) CI green → issue auto-closed. |
| QG-H2 | **Trust contracts do not cover any method CIMonitorLoop calls.** `test_fake_github_contract.py` covers `create_pr`, `merge_pr`, `close_issue`, `close_task`. None of `get_latest_ci_status`, `list_issues_by_label`, `create_issue`, or `post_comment` have cassettes. Drift between `FakeGitHub` and real gh CLI for these methods is invisible until sandbox or live testing. | `tests/trust/contracts/test_fake_github_contract.py` | Record cassettes for the four methods above and add dispatch arms in `_invoke_fake_github`. |
| QG-H3 | **`_rehydrate_open_issue` (restart recovery) has zero test coverage.** ADR-0029 calls this load-bearing. A regression would silently duplicate the failure issue on every restart. | `tests/test_ci_monitor_loop.py` | Add a test that pre-populates `list_issues_by_label` to return an existing open issue, calls `_do_work()`, and asserts `loop._open_issue` is set without calling `create_issue`. |

### Medium severity

| ID | Finding | Location | Recommended fix |
|---|---|---|---|
| QG-M1 | **`make trust-contracts` only runs on rc/ promotion PRs.** A PR that degrades `FakeGitHub` fidelity for ci-monitor-relevant methods would pass all normal PR gates. | `.github/workflows/ci.yml` | Add a `trust-contracts` job to `ci.yml` (or `quality.yml`) gated on `needs.changes.outputs.python == 'true'`. 5-minute timeout is sufficient. |
| QG-M2 | **Pre-commit `STAGED_ARCH` pathspec only covers `src/*.py` (top-level src).** Changes to `src/dashboard_routes/*.py`, `src/mockworld/**`, etc. do not trigger the pre-commit arch-check. Mitigated by the pre-push hook running arch-check unconditionally. | `.githooks/pre-commit` line 30–34 | Widen to `'src/**/*.py'` or simply remove the path gate (the arch-check is fast enough to run on any staged Python change). |
| QG-M3 | **`make quality` has no explicit `SHELL=/bin/bash` override.** The `jobs -p` subshell pattern is bash-specific. Works today because GitHub Actions `/bin/sh` is bash, but fragile if the CI image changes. | `Makefile` near `quality:` target | Add `SHELL=/bin/bash` at the top of the Makefile (or per-recipe override for the quality target). |
| QG-M4 | **`quality.yml` and `ci.yml` both run `pytest tests/` on the same trigger conditions**, doubling CI minutes without adding coverage. | `.github/workflows/quality.yml`, `ci.yml` | Consider removing the `quality.yml` Python test step in favor of the dedicated jobs in `ci.yml`, or inverting (keep `quality.yml` for multi-project matrix, remove from `ci.yml`). |

### Low severity

| ID | Finding | Location | Notes |
|---|---|---|---|
| QG-L1 | **Pre-commit `STAGED_TESTS` only captures `tests/test_*.py`** (top-level). Tests in `tests/architecture/`, `tests/regressions/`, `tests/scenarios/` bypass the test-sludge check. | `.githooks/pre-commit` line 35 | Widen to `'tests/**/*.py'` if sludge patterns are expected to appear in subdirectory test files. Low priority unless a pattern violation is found there in practice. |
| QG-L2 | **Unquoted `$STAGED_TESTS` in pre-commit hook** (line 53). Word splitting could corrupt paths with whitespace. | `.githooks/pre-commit` line 53 | Use `"$STAGED_TESTS"` or `printf '%s\n' $STAGED_TESTS | tr '\n' ' '`. Practically safe since Python file paths in this repo have no spaces. |
| QG-L3 | **`arch-regen.yml` has no `push:` trigger for `main`/`staging`.** The pre-push hook compensates locally; in CI the arch tests run via `ci.yml test` job. No actual gap in normal workflows. | `.github/workflows/arch-regen.yml` | Document the intentional design (no push trigger needed because ci.yml covers it). Low urgency. |

---

## Overall score by dimension

| Dimension | Score | Notes |
|---|---|---|
| Test coverage — unit | Good | 8/9 scenarios covered; `_rehydrate` missing |
| Test coverage — scenario | Good | scenario_loops coverage runs in every PR |
| Test coverage — sandbox e2e | **Gap** | No sNN scenario for CIMonitorLoop |
| Test coverage — trust contracts | **Gap** | 0/4 CIMonitorLoop port methods have cassettes |
| Loop health (wiring, error handling) | Excellent | All 5 checkpoints correct; all 4 wiring sites present |
| Pre-commit hooks | Good with gaps | Arch trigger too narrow; test-sludge scope narrow |
| CI workflow coverage | Good with gap | trust-contracts deferred to rc/ only |
| Architecture test wiring | Good | All 3 arch tests run in ci.yml and arch-regen.yml |
| `make quality` completeness | Good | Runs lint + typecheck + security + tests in parallel |

**Top 3 recommended actions:**

1. Add `tests/sandbox_scenarios/scenarios/s15_ci_monitor_main_branch_red.py`
   to close QG-H1 (missing sandbox layer).
2. Add `get_latest_ci_status` and `list_issues_by_label` cassettes to
   `tests/trust/contracts/` and wire them into `test_fake_github_contract.py`
   (QG-H2).
3. Add a unit test for `_rehydrate_open_issue` in
   `tests/test_ci_monitor_loop.py` (QG-H3).

Human review required before acting on QG-M1 (adding trust-contracts to
standard PR CI may meaningfully increase CI runtime). QG-M4 (de-duplicating
quality.yml vs ci.yml test runs) has broader impact and should be assessed
alongside the project CI cost budget.
