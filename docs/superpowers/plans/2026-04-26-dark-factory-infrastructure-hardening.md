# Dark-Factory Infrastructure Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move five load-bearing dark-factory conventions from "remembered by careful engineers" to "structurally enforced by the codebase" — across three sequential PRs that each merge independently.

**Architecture:** PR 1 lands process documentation (ADR-0051) and a pre-commit gate (zero risk). PR 2 introduces `BaseSubprocessRunner` (a generic-over-result-type subprocess base class), migrates `AutoAgentRunner` as the proof point, and adds strict Port↔Fake signature conformance (medium risk: a refactor of a recently-merged loop). PR 3 ships `scripts/scaffold_loop.py` with file-level tempdir-transaction atomicity (medium risk: non-trivial script with a clear validation surface).

**Tech Stack:** Python 3.11 (`abc.ABC`, `Generic[T_Result]`, `inspect.signature`, `dataclasses.dataclass(frozen=True)`); existing `runner_utils.stream_claude_process` + `prompt_telemetry.PromptTelemetry` + `exception_classify.reraise_on_credit_or_bug`; `Jinja2` for scaffold templates; `make arch-check` (existing); `.githooks/pre-commit` (existing).

**Spec ref:** `docs/superpowers/specs/2026-04-26-dark-factory-infrastructure-hardening-design.md`.

---

## Decisions Locked

0. **Pre-existing infrastructure check.** `scripts/scaffold_loop.py` already exists (197 lines, PR #5911). PR 3 UPGRADES it — see PR 3 preamble. The existing CLI signature is preserved; new flags are additive.
1. **Three independent PRs, sequenced in order.** PR 2 uses ADR-0051 as a reference. PR 3 generates code that inherits `BaseBackgroundLoop` (caretaker) — and a future extension can target `BaseSubprocessRunner` from PR 2.
2. **`BaseSubprocessRunner` is `Generic[T_Result]`.** Subclasses define their own typed return shape (e.g., `AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn])`); the base does not impose a single `SubprocessRunResult` dataclass. The internal `SpawnOutcome` is the record passed from `base.run()` to `subclass._make_result`.
3. **Auth-retry budget: 3 attempts, 5s/10s/20s exponential backoff.** Matches BaseRunner exactly. Constants live on the class for subclass-override.
4. **`reraise_on_credit_or_bug(exc)` is the FIRST line of the broad `except`.** Propagates `CreditExhaustedError` + terminal `AuthenticationError` so caretaker loops can suspend.
5. **Pre-commit hook reuses existing `arch-check` Makefile target** — no new `arch-regen-dry-run` target. Hook trigger broadens beyond Python files to include `.likec4` / `functional_areas.yml` / arch source.
6. **Scaffold script uses file-level tempdir transactions, not git branches.** Writes to a tmpdir, validates via `python -c "import ..."`, bulk-copies on success. Working tree is never half-applied.
7. **Port-signature conformance is Port↔Fake only.** Existing `tests/test_ports.py` already covers Port↔Adapter signature parity for `IssueStorePort↔IssueStore`. New test fills the Port↔Fake gap.
8. **Hand-maintained `_PORT_FAKE_PAIRS` for v1.** Auto-discovery deferred (the list has ~3 pairs at start; auto-discovery is YAGNI).
9. **No retrofit of existing runners.** `AutoAgentRunner` migrates as proof point. Other runners migrate opportunistically when next touched.
10. **Tool restrictions in scaffold.** The scaffold writes `enabled_cb` gate, static config gate, and `BaseBackgroundLoop` MRO — but does NOT write a `_do_work` body (engineer fills in).
11. **No `.pre-commit-config.yaml`.** HydraFlow uses `.githooks/pre-commit` driven by `Makefile`; we extend that, not introduce pre-commit-framework.
12. **Sequencing: PR 1 → PR 2 → PR 3.** PR 1 must merge before PR 2 because the strict-conformance test is one of the things ADR-0051 refers to as "structurally enforced." PR 2 must merge before PR 3 because the scaffold templates emit `BaseSubprocessRunner` subclasses.

---

## File Structure

| File | Role | C/M | PR |
|---|---|---|---|
| `docs/adr/0051-iterative-production-readiness-review.md` | ADR-0051 doc | C | 1 |
| `docs/adr/README.md:32` | Add ADR-0051 row to Accepted index | M | 1 |
| `CLAUDE.md:43-46` | Workflow skills section adds ADR-0051 link | M | 1 |
| `.githooks/pre-commit:28-32` | Replace `STAGED_PY` short-circuit with broader trigger | M | 1 |
| `.githooks/pre-commit:50` | Append `arch-check` invocation block | M | 1 |
| `src/runners/__init__.py` | Empty package marker | C | 2 |
| `src/runners/base_subprocess_runner.py` | `SpawnOutcome` + `BaseSubprocessRunner[T_Result]` | C | 2 |
| `src/preflight/auto_agent_runner.py` | Refactor to inherit `BaseSubprocessRunner[PreflightSpawn]` | M | 2 |
| `tests/test_base_subprocess_runner.py` | Unit tests for base class (auth retry, credit propagation, telemetry, never-raises, cost estimate) | C | 2 |
| `tests/scenarios/fakes/test_port_signature_conformance.py` | Strict Port↔Fake signature conformance | C | 2 |
| `scripts/scaffold_loop.py` | UPGRADE existing 197-line script: add kill-switch + static config in templates, add state mixin, swap inline `textwrap.dedent` for Jinja2, add five-checkpoint auto-patcher, add file-level tempdir transaction, add `--dry-run`/`--apply` flags | M | 3 |
| `scripts/scaffold_templates/loop.py.j2` | Jinja2 template for loop file (extracted from inline strings + ADR-0049 gate added) | C | 3 |
| `scripts/scaffold_templates/state_mixin.py.j2` | Jinja2 template for state mixin (new — existing script doesn't generate this) | C | 3 |
| `scripts/scaffold_templates/test_loop.py.j2` | Jinja2 template for loop test (extracted + kill-switch tests added) | C | 3 |
| `tests/test_scaffold_loop.py` | Golden-file tests for templates | C | 3 |

---

## PR 1: ADR-0051 + Pre-commit arch-regen check

**Goal:** Land the process documentation (ADR-0051) and the pre-commit gate that catches stale arch-generated docs before push. Zero runtime code changes.

**Risk: zero.** Docs + Makefile-driven hook update only.

### Task 1.1 — Write ADR-0051

**Create** `docs/adr/0051-iterative-production-readiness-review.md`:

```markdown
# ADR-0051: Iterative production-readiness review

- **Status:** Accepted
- **Date:** 2026-04-26
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0044](0044-superpowers-workflow-discipline.md) (TDD as default workflow), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0050](0050-auto-agent-hitl-preflight.md) (auto-agent HITL pre-flight). See also `docs/wiki/dark-factory.md` (lessons inventory).
- **Enforced by:** `superpowers:subagent-driven-development` workflow (per-task reviews), this ADR (process documentation), `superpowers:code-reviewer` skill (the fresh-eyes reviewer).

## Context

Across the trust-fleet (#8390) and auto-agent (#8431, #8439) feature builds, every Critical finding caught in fresh-eyes review was a missed load-bearing convention. Each feature took 3–5 review iterations before converging to "no Critical findings on the next pass." Without an explicit policy, convergence is a heroic ad-hoc effort that depends on the engineer remembering to dispatch reviewers; with one, it's the standard workflow.

We need to codify the "iterate fresh-eyes review until convergence" pattern as the standard for substantial features, so that the engineer's first instinct after implementation passes its per-task reviews is to start fresh-eyes iteration rather than to merge.

## Decision

For substantial features (new caretaker loop, new runner, spec → multi-task implementation), after the implementation passes its per-task reviews, run **fresh-eyes review iterations** until convergence.

- Each iteration uses `superpowers:code-reviewer` (or equivalent reviewer with no conversation context) on the cumulative diff against `main`.
- The reviewer reads the spec + the diff + the live codebase and reports Critical / Important / Minor findings.
- After fixes, the next iteration repeats.
- **Convergence = next pass finds nothing material** (Critical = 0, Important ≤ 1, all explained as deliberate).

Plan for **3 iterations** before merge. Empirical convergence point on recent features:

- Trust-fleet (#8390): 5 passes
- Auto-Agent spec (#8431): 3 passes
- Auto-Agent wiring (#8439): 3 passes

## Rules

1. **Fresh-eyes means no conversation context.** The reviewer reads the diff + the live codebase and reports findings without seeing the design rationale that produced the diff. This catches assumptions the engineer has grown blind to.
2. **Don't merge before convergence.** A Critical finding on iteration N is a merge-blocker until iteration N+1 confirms the fix.
3. **Iteration counts decline.** Each pass should find fewer issues. If iteration N+1 finds MORE issues than iteration N, something is wrong with the fixes — pause and re-spec.
4. **Per-task reviews continue during implementation.** This ADR is about the END phase (after implementation looks done); per-task reviews remain the standard during the build (per `superpowers:subagent-driven-development`).

## Consequences

**Positive:**
- Critical bugs caught at PR time, not in production.
- Reviews surface architectural drift while still cheap to fix.
- "Substantial features take 3 review passes" becomes a planning expectation, not a surprise.
- Convergence is a clear merge gate: don't merge until reviews are clean.

**Negative:**
- Substantial features take longer to merge (~30–60 min of reviewer time per pass).
- Reviewers must read live code (not just the diff) — but `code-reviewer` agent already does this.

**Risks:**
- Reviewer fatigue / noise from repeated passes. Mitigation: skip iterations once convergence reached; Minor-only findings don't re-trigger.

## Alternatives Considered

- **Single review pass.** Rejected — empirically misses bugs.
- **Reviewer in CI (mandatory).** Rejected — too much friction; reviewer needs codebase access and runs ~5 minutes per pass.
- **Pre-merge checklist.** Rejected — doesn't catch what reviewers do (cross-cutting drift, contract holes).

## When to supersede this ADR

- If a `superpowers:production-readiness-review` skill is built that automates the iteration loop, this ADR's "manually iterate" guidance becomes a legacy fallback. Update accordingly.
- If empirical convergence point shifts (e.g., features routinely converge in 1 pass), reduce the planning expectation.

## Source-file citations

- `docs/wiki/dark-factory.md` §3 — the convergence loop documentation.
- `docs/adr/0050-auto-agent-hitl-preflight.md` — the recent feature whose review iterations validated this ADR.
- `superpowers:code-reviewer` (Claude Code skill) — the reviewer this ADR refers to.
- `superpowers:subagent-driven-development` (Claude Code skill) — the per-task review workflow during implementation.
```

- [ ] **Step 1: Create the ADR file** above. (No tests for an ADR; this is process documentation.)

- [ ] **Step 2: Run lint check** — `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec && uv run ruff check docs/` (should pass; ADRs are markdown so no Python lint applies, but confirm no accidental Python syntax errors in code blocks).

- [ ] **Step 3: Update `docs/adr/README.md`** — find the Accepted ADR table, append a row for ADR-0051. Use the same format as ADR-0049 (alphabetical/numerical position).

- [ ] **Step 4: Commit**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
git add docs/adr/0051-iterative-production-readiness-review.md docs/adr/README.md
git commit -m "docs(adr): ADR-0051 — iterative production-readiness review"
```

### Task 1.2 — Update CLAUDE.md workflow skills section

**Modify** `CLAUDE.md:43-46` (the "Workflow skills" block).

Current state (already includes a quick-rule about 2–3 iterations from PR #8443):

```markdown
TDD is the default: `superpowers:brainstorming` → `superpowers:writing-plans`
→ `superpowers:test-driven-development` (red/green/refactor) → `superpowers:verification-before-completion` → `superpowers:requesting-code-review`.
Use `superpowers:systematic-debugging` on failures. Bug fixes land with a
regression test in `tests/regressions/`. See [`docs/wiki/testing.md`](docs/wiki/testing.md).
```

- [ ] **Step 1: Append a sentence linking ADR-0051**

After the existing block, add:

```markdown

For substantial features (new loop, new runner, spec → multi-task work), end with **2–3 fresh-eyes review iterations** until convergence per [ADR-0051](docs/adr/0051-iterative-production-readiness-review.md) — convergence = next pass finds nothing material.
```

- [ ] **Step 2: Confirm pre-commit hook accepts the change**

Run `git diff CLAUDE.md` — verify net content removal is zero (the pre-commit hook blocks `lines_removed > lines_added` on CLAUDE.md). This change adds lines, so pre-commit will accept.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): link ADR-0051 in workflow skills section"
```

### Task 1.3 — Pre-commit hook update

**Modify** `.githooks/pre-commit` to broaden the trigger condition AND add the arch-check invocation.

Current state (line 28–32):

```bash
# Only check if Python files are staged
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' || true)
if [ -z "$STAGED_PY" ]; then
    exit 0
fi
```

This short-circuits on non-Python changes. We need it to also fire on arch source changes.

- [ ] **Step 1: Write the broader trigger** — replace lines 28–32 with:

```bash
# Detect Python changes (existing) AND arch source changes (new).
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' || true)
STAGED_ARCH=$(git diff --cached --name-only --diff-filter=ACM \
    -- 'docs/arch/*.likec4' \
       'docs/arch/functional_areas.yml' \
       'docs/arch/source/*' \
       'src/*.py' || true)

# Short-circuit only when neither trigger fires.
if [ -z "$STAGED_PY" ] && [ -z "$STAGED_ARCH" ]; then
    exit 0
fi
```

- [ ] **Step 2: Append the arch-check invocation** — after the existing `echo "pre-commit: lint OK"` line (line 50), add:

```bash

# Arch-regen check — fail-fast with helpful message when generated docs are stale.
# Reuses the existing `make arch-check` target (does not auto-stage).
if [ -n "$STAGED_ARCH" ]; then
    echo "pre-commit: running make arch-check..."
    if ! make arch-check >/tmp/hydraflow-arch-check.out 2>&1; then
        echo "❌ docs/arch/generated/ is out of sync with source." >&2
        echo "" >&2
        echo "Run:" >&2
        echo "  make arch-regen && git add docs/arch/" >&2
        echo "" >&2
        echo "First 20 lines of arch-check output:" >&2
        head -20 /tmp/hydraflow-arch-check.out >&2
        exit 1
    fi
    echo "pre-commit: arch-check OK"
fi
```

- [ ] **Step 3: Test the negative path manually**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
# Make a benign source change that affects arch extraction.
echo "# trigger arch drift" >> src/auto_agent_preflight_loop.py
# DON'T regen.
git add src/auto_agent_preflight_loop.py
git commit -m "test"  # should fail with arch-check helpful message
```

Expected output: pre-commit fails, prints the helpful message, exits 1. Verify the message is the one we wrote.

- [ ] **Step 4: Test the positive path** — revert the test change, regen, commit again.

```bash
git restore src/auto_agent_preflight_loop.py
make arch-regen
git add -A
git commit -m "test commit, will revert" --allow-empty
git reset HEAD~1  # or git revert if pushed
```

Expected: pre-commit passes when arch-check passes.

- [ ] **Step 5: Test the no-arch-change path**

Make a Python-only change that doesn't affect arch extraction (e.g., add a comment to a test file), commit. Pre-commit should run lint-check and skip arch-check. Verify by reading the output for `arch-check OK` (should NOT appear since `STAGED_ARCH` is empty).

- [ ] **Step 6: Commit the hook itself**

```bash
git add .githooks/pre-commit
git commit -m "chore(precommit): add arch-check invocation + broaden trigger to non-Python changes"
```

### Task 1.4 — Verification + push + open PR1

- [ ] **Step 1: Final lint pass**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
make quality 2>&1 | tail -8
```

Expected: 11700+ tests pass, 0 failures (PR1 is docs + hook only; no code changes).

- [ ] **Step 2: Push**

```bash
git push -u origin dark-factory-infra-spec
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "docs(adr): ADR-0051 + pre-commit arch-check" --body "$(cat <<'EOF'
## Summary

PR 1 of 3 in the dark-factory infrastructure hardening track (spec at `docs/superpowers/specs/2026-04-26-dark-factory-infrastructure-hardening-design.md`).

Lands process documentation and a pre-commit gate. Zero runtime code changes.

- **ADR-0051**: codifies the "iterate fresh-eyes review until convergence" pattern for substantial features. References the recent trust-fleet (#8390) and auto-agent (#8431, #8439) iteration counts as evidence.
- **CLAUDE.md**: workflow skills section links ADR-0051.
- **`.githooks/pre-commit`**: trigger condition broadens beyond Python files; appended `make arch-check` invocation with a helpful message when generated docs are stale.

## Test plan

- [x] Pre-commit hook tested on three paths: arch-stale (fails with message), arch-clean (passes), Python-only (skips arch-check correctly).
- [x] `make quality` passes — no test changes required for PR1.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR 1 lands first. PR 2 begins after PR 1 merges (or rebases on it).

---

## PR 2: BaseSubprocessRunner + AutoAgentRunner Migration + PRPort signature conformance

**Goal:** Introduce `BaseSubprocessRunner` (encapsulates auth-retry + telemetry + reraise + never-raises), migrate `AutoAgentRunner` as the proof point (-90 lines of duplicated logic), and add strict `inspect.signature` Port↔Fake conformance.

**Risk: medium.** Refactor of a recently-merged runner. Mitigated by keeping all 11 existing tests green post-migration.

### Task 2.1 — `runners/` package + `SpawnOutcome` dataclass

**Create** `src/runners/__init__.py` (empty file — package marker).

**Create** `src/runners/base_subprocess_runner.py` initial file with imports + `SpawnOutcome`:

```python
"""BaseSubprocessRunner — abstract base for runners that spawn a subprocess.

Spec §3.1. Encapsulates the four conventions PR #8439 surfaced as
load-bearing across any runner that spawns a Claude Code / codex /
gemini subprocess:

- 3-attempt auth-retry loop with exponential backoff (5s, 10s, 20s) on
  AuthenticationRetryError from runner_utils.
- reraise_on_credit_or_bug propagates CreditExhaustedError + terminal
  AuthenticationError so caretaker loops can suspend.
- PromptTelemetry.record() with subclass-provided source attribution.
- Never-raises contract: every failure path returns a typed result,
  never propagates a generic RuntimeError to the caller.

Subclasses parameterise their own typed result (e.g.,
`AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn])`) — the base does
NOT impose a single shared dataclass. The internal `SpawnOutcome` is the
record passed from `base.run()` to `subclass._make_result`.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from config import HydraFlowConfig
from events import EventBus
from exception_classify import reraise_on_credit_or_bug
from model_pricing import load_pricing
from prompt_telemetry import PromptTelemetry
from runner_utils import AuthenticationRetryError, StreamConfig, stream_claude_process

logger = logging.getLogger("hydraflow.runners.base_subprocess_runner")


@dataclass(frozen=True)
class SpawnOutcome:
    """Internal record passed from base.run() to subclass._make_result.

    Internal to BaseSubprocessRunner — not part of any subclass's public
    API. Subclass converts this into its own dataclass (e.g., PreflightSpawn)
    via _make_result.
    """

    transcript: str
    usage_stats: dict[str, object]
    wall_clock_s: float
    crashed: bool
    prompt_hash: str
    cost_usd: float


T_Result = TypeVar("T_Result")


def _coerce_int(value: object) -> int:
    """Best-effort int coercion for usage_stats values from streaming parsers.

    Stream parsers may emit ints, strings, or even Decimal — coerce safely
    and clamp to >= 0 since negative token counts are nonsense.
    """
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
```

- [ ] **Step 1: Create the package files** above.

- [ ] **Step 2: Lint clean**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
uv run ruff check src/runners/
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/runners/
git commit -m "feat(runners): SpawnOutcome dataclass + runners package marker"
```

### Task 2.2 — `BaseSubprocessRunner` skeleton (init + abstract methods)

**Modify** `src/runners/base_subprocess_runner.py` — append the class:

```python
class BaseSubprocessRunner(abc.ABC, Generic[T_Result]):
    """Abstract base for subprocess-spawning runners. See module docstring.

    Subclasses MUST override:
    - `_telemetry_source()` → str (e.g., "auto_agent_preflight")
    - `_build_command(prompt, worktree)` → list[str]
    - `_make_result(outcome)` → T_Result (e.g., PreflightSpawn)

    Subclasses MAY override:
    - `_default_timeout_s()` → int (default: config.agent_timeout)
    - `_pre_spawn_hook(prompt)` → None (logging, validation, etc.)
    - `_estimate_cost(usage_stats)` → float (default: model_pricing lookup)
    """

    # Match BaseRunner._execute auth-retry budget so transient OAuth blips
    # don't burn the per-issue attempt cap.
    _AUTH_RETRY_MAX = 3
    _AUTH_RETRY_BASE_DELAY = 5.0  # seconds

    def __init__(self, *, config: HydraFlowConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._telemetry = PromptTelemetry(config)

    @abc.abstractmethod
    def _telemetry_source(self) -> str:
        """Return the source string for PromptTelemetry attribution."""

    @abc.abstractmethod
    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        """Build the CLI command (e.g., via build_agent_command)."""

    @abc.abstractmethod
    def _make_result(self, outcome: SpawnOutcome) -> T_Result:
        """Convert the internal SpawnOutcome into the subclass's typed result."""

    def _default_timeout_s(self) -> int:
        """Default subprocess timeout. Override per subclass for caps."""
        return int(self._config.agent_timeout)

    def _pre_spawn_hook(self, prompt: str) -> None:
        """Hook for pre-spawn checks/logging (e.g., warn on backend mismatch)."""
        # Default: no-op.

    def _estimate_cost(self, usage_stats: dict[str, object]) -> float:
        """Default cost estimate via model_pricing.

        Returns 0.0 when the model isn't in the pricing table or stats are
        missing. Subclasses may override for custom pricing or no-op for
        free-tier runs.
        """
        try:
            pricing = load_pricing()
            estimate = pricing.estimate_cost(
                model=self._config.model,
                input_tokens=_coerce_int(usage_stats.get("input_tokens")),
                output_tokens=_coerce_int(usage_stats.get("output_tokens")),
                cache_write_tokens=_coerce_int(
                    usage_stats.get("cache_creation_input_tokens")
                ),
                cache_read_tokens=_coerce_int(
                    usage_stats.get("cache_read_input_tokens")
                ),
            )
            return float(estimate or 0.0)
        except Exception as exc:
            logger.warning("subprocess runner cost estimate failed: %s", exc)
            return 0.0
```

- [ ] **Step 1: Apply the append.**

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
uv run python -c "from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome; print('OK')"
```

Expected: prints `OK`. (Cannot instantiate `BaseSubprocessRunner` directly since it's abstract.)

- [ ] **Step 3: Commit**

```bash
git add src/runners/base_subprocess_runner.py
git commit -m "feat(runners): BaseSubprocessRunner abstract skeleton"
```

### Task 2.3 — `run()` method with auth-retry loop

**Modify** `src/runners/base_subprocess_runner.py` — append the `run()` method to `BaseSubprocessRunner`. This is the load-bearing piece; matches the auth-retry shape from `auto_agent_runner.py:127-186` exactly.

```python
    async def run(
        self,
        *,
        prompt: str,
        worktree_path: str,
        issue_number: int,
    ) -> T_Result:
        """Run one subprocess attempt; never raises.

        Auth blips retry up to _AUTH_RETRY_MAX times. Credit/auth-terminal
        errors propagate (caretaker loop suspends). Other failures collapse
        to crashed=True in the SpawnOutcome the subclass converts.
        """
        from preflight.agent import hash_prompt  # noqa: PLC0415

        self._pre_spawn_hook(prompt)
        cmd = self._build_command(prompt, Path(worktree_path))

        usage_stats: dict[str, object] = {}
        prompt_hash = hash_prompt(prompt)
        timeout_s = self._default_timeout_s()
        start = time.monotonic()
        crashed = False
        transcript = ""

        last_auth_error: AuthenticationRetryError | None = None
        for attempt in range(1, self._AUTH_RETRY_MAX + 1):
            try:
                transcript = await stream_claude_process(
                    cmd=cmd,
                    prompt=prompt,
                    cwd=Path(worktree_path),
                    active_procs=self._active_procs,
                    event_bus=self._bus,
                    event_data={
                        "issue": issue_number,
                        "source": self._telemetry_source(),
                    },
                    logger=logger,
                    config=StreamConfig(
                        timeout=timeout_s,
                        usage_stats=usage_stats,
                    ),
                )
                last_auth_error = None
                break
            except AuthenticationRetryError as exc:
                last_auth_error = exc
                if attempt < self._AUTH_RETRY_MAX:
                    delay = self._AUTH_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "subprocess runner auth retry %d/%d for issue #%d, "
                        "sleeping %.0fs: %s",
                        attempt,
                        self._AUTH_RETRY_MAX,
                        issue_number,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                # Credit / terminal-auth / programming bugs propagate so the
                # caretaker loop can suspend or surface the bug; everything
                # else collapses to crashed=True with a partial transcript.
                reraise_on_credit_or_bug(exc)
                crashed = True
                tail = transcript[-2000:] if transcript else ""
                transcript = f"{tail}\n\nspawn error: {exc}"
                logger.warning(
                    "subprocess runner failed for issue #%d: %s",
                    issue_number,
                    exc,
                )
                break

        if last_auth_error is not None:
            crashed = True
            transcript = (
                f"{transcript}\n\nauth retry exhausted after "
                f"{self._AUTH_RETRY_MAX} attempts: {last_auth_error}"
            )
            logger.error(
                "subprocess runner auth retry exhausted for issue #%d after %d attempts",
                issue_number,
                self._AUTH_RETRY_MAX,
            )
        wall_s = time.monotonic() - start

        # Telemetry — best-effort write to inferences.jsonl.
        try:
            self._telemetry.record(
                source=self._telemetry_source(),
                tool=self._config.implementation_tool,
                model=self._config.model,
                issue_number=issue_number,
                pr_number=None,
                session_id=self._bus.current_session_id,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=wall_s,
                success=not crashed,
                stats=usage_stats,
            )
        except Exception as exc:
            logger.warning("subprocess runner telemetry write failed: %s", exc)

        cost_usd = self._estimate_cost(usage_stats)

        outcome = SpawnOutcome(
            transcript=transcript,
            usage_stats=usage_stats,
            wall_clock_s=wall_s,
            crashed=crashed,
            prompt_hash=prompt_hash,
            cost_usd=cost_usd,
        )
        return self._make_result(outcome)
```

- [ ] **Step 1: Apply the append.**

- [ ] **Step 2: Lint clean**

```bash
uv run ruff check src/runners/base_subprocess_runner.py
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/runners/base_subprocess_runner.py
git commit -m "feat(runners): BaseSubprocessRunner.run() with auth-retry + reraise + telemetry"
```

### Task 2.4 — Unit tests for BaseSubprocessRunner

**Create** `tests/test_base_subprocess_runner.py`:

```python
"""BaseSubprocessRunner unit tests (spec §3.1).

Mocks `stream_claude_process` at the module boundary so no real Claude
Code subprocess is spawned. Verifies:

- subclass abstract methods are required (TypeError on instantiation).
- happy path: outcome.transcript, usage_stats, prompt_hash flow through.
- auth-retry loop: transient AuthenticationRetryError retries up to
  _AUTH_RETRY_MAX times; auth-retry exhausted → crashed=True.
- credit / terminal-auth errors propagate (loop can suspend).
- generic exceptions collapse to crashed=True (never-raises contract).
- telemetry write failure is logged but doesn't fail the run.
- cost estimate default works against the model_pricing table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
)
from tests.helpers import ConfigFactory


@dataclass(frozen=True)
class _FakeResult:
    """Test-only result type satisfying the T_Result contract."""

    crashed: bool
    transcript: str
    cost_usd: float
    tokens: int
    prompt_hash: str


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    """Concrete subclass for tests."""

    def _telemetry_source(self) -> str:
        return "fake_runner_test"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["fake-claude", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        from runners.base_subprocess_runner import _coerce_int
        return _FakeResult(
            crashed=outcome.crashed,
            transcript=outcome.transcript,
            cost_usd=outcome.cost_usd,
            tokens=_coerce_int(outcome.usage_stats.get("total_tokens")),
            prompt_hash=outcome.prompt_hash,
        )


def _make_runner(**config_overrides: Any) -> _FakeRunner:
    config = ConfigFactory.create(**config_overrides)
    bus = MagicMock()
    bus.current_session_id = "test-session"
    return _FakeRunner(config=config, event_bus=bus)


def test_abstract_methods_required() -> None:
    """BaseSubprocessRunner cannot be instantiated without subclass overrides."""
    config = ConfigFactory.create()
    bus = MagicMock()
    with pytest.raises(TypeError):
        BaseSubprocessRunner(config=config, event_bus=bus)  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_happy_path_yields_outcome(tmp_path: Path) -> None:
    async def fake_stream(*, config, **kwargs: Any) -> str:
        config.usage_stats["input_tokens"] = 100
        config.usage_stats["output_tokens"] = 50
        config.usage_stats["total_tokens"] = 150
        return "<status>resolved</status>"

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ):
        result = await runner.run(
            prompt="hello", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is False
    assert "resolved" in result.transcript
    assert result.tokens == 150
    assert result.prompt_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_auth_retry_then_success(tmp_path: Path) -> None:
    """Two transient AuthenticationRetryErrors retry; third call succeeds."""
    from runner_utils import AuthenticationRetryError

    call_count = 0

    async def fake_stream(**kwargs: Any) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise AuthenticationRetryError("transient OAuth")
        return "<status>resolved</status>"

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ), patch(
        "runners.base_subprocess_runner.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert call_count == 3
    assert result.crashed is False


@pytest.mark.asyncio
async def test_auth_retry_exhausted_marks_crashed(tmp_path: Path) -> None:
    from runner_utils import AuthenticationRetryError

    async def always_auth_fail(**kwargs: Any) -> str:
        raise AuthenticationRetryError("OAuth refresh broken")

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=always_auth_fail,
    ), patch(
        "runners.base_subprocess_runner.asyncio.sleep", new_callable=AsyncMock
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is True
    assert "auth retry exhausted" in result.transcript


@pytest.mark.asyncio
async def test_credit_exhausted_propagates(tmp_path: Path) -> None:
    """CreditExhaustedError must propagate so the caretaker loop suspends."""
    from subprocess_util import CreditExhaustedError

    async def credit_exhausted(**kwargs: Any) -> str:
        raise CreditExhaustedError("api credits at zero")

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=credit_exhausted,
    ), pytest.raises(CreditExhaustedError):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)


@pytest.mark.asyncio
async def test_generic_exception_collapses_to_crashed(tmp_path: Path) -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("subprocess oom")

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process", side_effect=boom
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is True
    assert "spawn error" in result.transcript


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_fail_run(tmp_path: Path) -> None:
    async def stream_ok(**kwargs: Any) -> str:
        return "<status>needs_human</status>"

    runner = _make_runner()
    runner._telemetry = MagicMock()
    runner._telemetry.record = MagicMock(side_effect=OSError("disk full"))
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_ok,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.crashed is False  # run succeeded despite telemetry failure


@pytest.mark.asyncio
async def test_cost_estimate_default_returns_non_negative(tmp_path: Path) -> None:
    async def fake_stream(*, config, **kwargs: Any) -> str:
        config.usage_stats["input_tokens"] = 100
        config.usage_stats["output_tokens"] = 50
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ):
        result = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert result.cost_usd >= 0.0


@pytest.mark.asyncio
async def test_pre_spawn_hook_is_called(tmp_path: Path) -> None:
    """Subclass override of _pre_spawn_hook fires once before stream_claude_process."""
    pre_calls: list[str] = []

    class _HookRunner(_FakeRunner):
        def _pre_spawn_hook(self, prompt: str) -> None:
            pre_calls.append(prompt)

    config = ConfigFactory.create()
    bus = MagicMock()
    bus.current_session_id = "test-session"
    runner = _HookRunner(config=config, event_bus=bus)

    async def stream_ok(**kwargs: Any) -> str:
        return ""

    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_ok,
    ):
        await runner.run(prompt="hi", worktree_path=str(tmp_path), issue_number=1)
    assert pre_calls == ["hi"]
```

- [ ] **Step 1: Run failing tests** — `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec && uv run pytest tests/test_base_subprocess_runner.py -v`

If `stream_claude_process` runs the actual subprocess (because module path differs from what's patched), tests will fail with errors — adjust the patch target to the real module path.

- [ ] **Step 2: Verify all 9 tests pass.**

- [ ] **Step 3: Commit**

```bash
git add tests/test_base_subprocess_runner.py
git commit -m "test(runners): BaseSubprocessRunner unit tests"
```

### Task 2.5 — Migrate `AutoAgentRunner` to inherit `BaseSubprocessRunner`

**Modify** `src/preflight/auto_agent_runner.py` — refactor to inherit `BaseSubprocessRunner[PreflightSpawn]`. Removes ~90 lines of duplicated logic; keeps the auto-agent-specific concerns (disallowed_tools=WebFetch, backend warning, wall-clock cap override).

Replace the entire body of the file with:

```python
"""AutoAgentRunner — Claude Code subprocess spawn for AutoAgentPreflightLoop.

Spec §3.1 / ADR-0050. Inherits BaseSubprocessRunner[PreflightSpawn] for
the load-bearing conventions (auth-retry, reraise_on_credit_or_bug,
telemetry, never-raises). Auto-agent-specific concerns:

- tool restrictions (`--disallowedTools=WebFetch` per spec §5.2)
- backend-mismatch warning when implementation_tool != "claude"
- wall-clock cap override (auto_agent_wall_clock_cap_s)
- result shape: PreflightSpawn (with output_text + tokens fields)
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_cli import build_agent_command
from preflight.agent import PreflightSpawn
from runners.base_subprocess_runner import (
    BaseSubprocessRunner,
    SpawnOutcome,
    _coerce_int,
)

logger = logging.getLogger("hydraflow.preflight.auto_agent_runner")


# Spec §5.2 — tools the auto-agent must NOT use.
#
# `WebFetch` is disabled because the auto-agent should reason from the
# context the loop gathered (wiki + sentry + recent commits + escalation
# context), not chase arbitrary external URLs that could leak issue
# content or pull in malicious instructions.
_AUTO_AGENT_DISALLOWED_TOOLS = "WebFetch"


class AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn]):
    """Spawns a Claude Code subprocess for one auto-agent attempt.

    One instance per attempt; lifetime is bounded by `run()`.
    """

    def _telemetry_source(self) -> str:
        return "auto_agent_preflight"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            disallowed_tools=_AUTO_AGENT_DISALLOWED_TOOLS,
        )

    def _default_timeout_s(self) -> int:
        return int(
            self._config.auto_agent_wall_clock_cap_s or self._config.agent_timeout
        )

    def _pre_spawn_hook(self, prompt: str) -> None:
        # `--disallowedTools=WebFetch` is silently dropped by build_agent_command
        # for codex/gemini backends. Warn so the operator knows the CLI-level
        # guard isn't active for that backend — the path-level honor-system
        # in the prompt envelope is the only remaining restriction layer.
        if self._config.implementation_tool != "claude":
            logger.warning(
                "auto-agent: --disallowedTools is only enforced for the claude "
                "backend; current implementation_tool=%s — WebFetch restriction "
                "is honor-system + post-hoc CI for this run",
                self._config.implementation_tool,
            )

    def _make_result(self, outcome: SpawnOutcome) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=outcome.transcript,
            cost_usd=outcome.cost_usd,
            tokens=_coerce_int(outcome.usage_stats.get("total_tokens")),
            crashed=outcome.crashed,
            prompt_hash=outcome.prompt_hash,
        )
```

- [ ] **Step 1: Apply the rewrite.**

- [ ] **Step 2: Run all existing AutoAgentRunner tests** — they must ALL pass:

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
uv run pytest tests/test_preflight_auto_agent_runner.py -v
```

Expected: 11 tests pass. If any fail, the migration broke behavior — the most likely cause is a patch target that needs updating (e.g., `patch("preflight.auto_agent_runner.stream_claude_process")` may now need to be `patch("runners.base_subprocess_runner.stream_claude_process")` since the call site moved).

- [ ] **Step 3: If tests fail because of patch-target moves, update the test file**

The tests in `tests/test_preflight_auto_agent_runner.py` patch `preflight.auto_agent_runner.stream_claude_process`. After migration, `stream_claude_process` is called from `runners.base_subprocess_runner`. Update each `patch(...)` call:

```python
# Before:
patch("preflight.auto_agent_runner.stream_claude_process", ...)
# After:
patch("runners.base_subprocess_runner.stream_claude_process", ...)
```

(Same for `asyncio.sleep` patches.)

- [ ] **Step 4: Re-run** — confirm 11/11 pass.

- [ ] **Step 5: Run the loop tests too** (regression net):

```bash
uv run pytest tests/test_auto_agent_preflight_loop.py tests/test_auto_agent_close_reconciliation.py tests/test_auto_agent_loop_wiring.py tests/scenarios/test_auto_agent_preflight.py tests/auto_agent/adversarial/ -m "" 2>&1 | tail -5
```

Expected: 121 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/preflight/auto_agent_runner.py tests/test_preflight_auto_agent_runner.py
git commit -m "refactor(auto-agent): migrate AutoAgentRunner to inherit BaseSubprocessRunner"
```

### Task 2.6 — Strict Port↔Fake signature conformance test

**Create** `tests/scenarios/fakes/test_port_signature_conformance.py`:

```python
"""Strict Port↔Fake signature conformance (spec §3.3).

Existing test test_port_conformance.py uses isinstance() against the
runtime-checkable Protocol — passes when method names match, but
Python's structural subtyping does NOT compare signatures. C2/C3 from
PR #8439 (`remove_labels` plural typo, nonexistent `list_issue_comments`)
slipped through.

This test fills the Port↔Fake gap: for every (Port, Fake) pair, every
public Port method must have a Fake method with the same name AND the
same kwarg signature. tests/test_ports.py already covers Port↔Adapter
signature parity for IssueStorePort↔IssueStore (the real adapter).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from ports import PRPort, WorkspacePort
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_workspace import FakeWorkspace

# Hand-maintained Port↔Fake pair list. Add new pairs as Fakes are
# introduced. (Auto-discovery via convention `Fake<PortStem>` is YAGNI
# at this scale; ~3 pairs total.)
_PORT_FAKE_PAIRS: list[tuple[type, type]] = [
    (PRPort, FakeGitHub),
    (WorkspacePort, FakeWorkspace),
    # IssueStorePort: no Fake; covered separately by tests/test_ports.py
    # against the real IssueStore adapter.
]


def _public_methods(cls: type) -> dict[str, Any]:
    """Return public methods of cls (skip dunders + private prefix)."""
    out = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name)
        if not callable(attr):
            continue
        out[name] = attr
    return out


def _signatures_compatible(port_sig: inspect.Signature, fake_sig: inspect.Signature) -> bool:
    """True if fake_sig is drop-in-compatible with port_sig.

    Compatibility check:
    - Same parameter names (kwargs match by name; we use keyword-only by convention)
    - Same required vs optional status (default-vs-no-default)
    - Type annotations are not strictly compared — Python's runtime accepts
      duck-typed kwargs and exact match would over-constrain Fakes.
    """
    port_params = {p: pinfo for p, pinfo in port_sig.parameters.items() if p != "self"}
    fake_params = {p: pinfo for p, pinfo in fake_sig.parameters.items() if p != "self"}

    # Must have exactly the same parameter names.
    if set(port_params.keys()) != set(fake_params.keys()):
        return False

    # Each param: same required-vs-optional status.
    for name, port_pinfo in port_params.items():
        fake_pinfo = fake_params[name]
        port_required = port_pinfo.default is inspect.Parameter.empty
        fake_required = fake_pinfo.default is inspect.Parameter.empty
        if port_required != fake_required:
            return False

    return True


@pytest.mark.parametrize(
    "port_cls,fake_cls",
    _PORT_FAKE_PAIRS,
    ids=[f"{p.__name__}↔{f.__name__}" for p, f in _PORT_FAKE_PAIRS],
)
def test_fake_signatures_match_port(port_cls: type, fake_cls: type) -> None:
    """For every public method on the Port, the Fake must have a method
    with the same name AND the same kwarg signature."""
    port_methods = _public_methods(port_cls)
    fake_methods = _public_methods(fake_cls)

    missing = port_methods.keys() - fake_methods.keys()
    assert not missing, (
        f"{fake_cls.__name__} is missing methods declared on {port_cls.__name__}: "
        f"{sorted(missing)}\n\n"
        f"This catches the C2/C3 class of break from PR #8439 — Fake drift "
        f"hidden by AsyncMock auto-attribute behavior."
    )

    for name in port_methods:
        port_sig = inspect.signature(port_methods[name])
        fake_sig = inspect.signature(fake_methods[name])
        assert _signatures_compatible(port_sig, fake_sig), (
            f"Signature mismatch on {fake_cls.__name__}.{name}:\n"
            f"  Port: {port_sig}\n"
            f"  Fake: {fake_sig}\n\n"
            f"Either rename the Fake method or update the Port — but they "
            f"must agree on parameter names and required-vs-optional status."
        )
```

- [ ] **Step 1: Run the test** — `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec && uv run pytest tests/scenarios/fakes/test_port_signature_conformance.py -v`

The test will likely fail on first run, surfacing pre-existing Port↔Fake drift that has been silently OK. Read each failure message carefully.

- [ ] **Step 2: For each failure, decide between FIX or `xfail`**

If the drift is small and clearly a typo / rename oversight, FIX it (update the Fake to match the Port).

If the drift is intentional (e.g., the Fake's method takes an extra optional kwarg for test seeding), add an explicit `xfail` marker with a linked follow-up issue:

```python
@pytest.mark.xfail(reason="FakeGitHub.X has test-seeding kwarg Y; tracked in #NNNN")
```

- [ ] **Step 3: Re-run** — confirm all parametrized cases pass or xfail.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/fakes/test_port_signature_conformance.py
# If you fixed any Fakes:
git add tests/scenarios/fakes/fake_*.py
git commit -m "test(conformance): strict Port↔Fake signature conformance"
```

### Task 2.7 — Verification + push + open PR2

- [ ] **Step 1: Full quality gate**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
make quality 2>&1 | tail -8
```

Expected: 11700+ tests pass, 0 failures (including the 9 new BaseSubprocessRunner tests + 1 new conformance parametrized test).

- [ ] **Step 2: Push (rebase if needed onto main, since PR1 should have merged)**

```bash
git fetch origin main
git rebase origin/main -X theirs  # arch-generated conflicts auto-resolve to theirs
make arch-regen 2>&1 | tail -3
git add -A && git commit -m "chore(arch): regen after rebase" --allow-empty
git push --force-with-lease
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(runners): BaseSubprocessRunner + AutoAgentRunner migration + Port↔Fake signature conformance" --body "$(cat <<'EOF'
## Summary

PR 2 of 3 in the dark-factory infrastructure hardening track.

- **`BaseSubprocessRunner[T_Result]`** — generic-over-result-type abstract base. Encapsulates auth-retry, reraise_on_credit_or_bug, telemetry, never-raises contract. Subclasses parameterize their own typed result (e.g., `AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn])`).
- **`AutoAgentRunner` migration** — inherits the base; removes ~90 lines of duplicated logic; all 11 existing tests + 121 loop/scenario/adversarial tests pass unchanged.
- **`tests/scenarios/fakes/test_port_signature_conformance.py`** — strict `inspect.signature` Port↔Fake conformance. Catches the C2/C3 class of break from PR #8439 (`remove_labels` plural typo, nonexistent `list_issue_comments`).

## Test plan

- [x] `uv run pytest tests/test_base_subprocess_runner.py` — 9 tests pass.
- [x] `uv run pytest tests/test_preflight_auto_agent_runner.py` — 11 tests pass post-migration.
- [x] `uv run pytest tests/scenarios/test_auto_agent_preflight.py tests/auto_agent/adversarial/` — 121 tests pass.
- [x] `uv run pytest tests/scenarios/fakes/test_port_signature_conformance.py` — parametrized cases pass or xfail with linked issues.
- [x] `make quality` — full suite passes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR 2 lands; PR 3 begins after PR 2 merges (or rebases on it).

---

## PR 3: scripts/scaffold_loop.py upgrade

**IMPORTANT — pre-existing script:** `scripts/scaffold_loop.py` already exists (197 lines, landed in PR #5911 as part of "Factory validation checks"). It generates a loop file + test file using inline `textwrap.dedent` strings and prints "manual wiring instructions" for the rest. PR 3 UPGRADES this existing script — it does not create a new file.

**Existing capabilities (keep):**
- CLI signature: `python scripts/scaffold_loop.py NAME LABEL DESCRIPTION --interval N`
- Generates `src/NAME_loop.py` + `tests/test_NAME_loop.py`

**What PR 3 adds:**
- ADR-0049 in-body kill-switch gate baked into the loop template (existing template's `_do_work` body has no gate).
- Static config gate (`*_enabled` field check).
- State mixin generation (`src/state/_NAME.py`) — existing script doesn't generate this.
- Five-checkpoint AUTO-patching of `models.py`, `state/__init__.py`, `config.py`, `service_registry.py`, `orchestrator.py`, `ui/src/constants.js`, `_common.py`, `loop_registrations.py`, `functional_areas.yml` — replaces the existing "print manual instructions" approach.
- Jinja2 templates (`scripts/scaffold_templates/`) — replaces the existing inline `textwrap.dedent` strings.
- File-level tempdir transaction with import-validation gate.
- `--dry-run` flag (default) and `--apply` flag.
- Refuses to run on a dirty working tree.

**Goal:** Upgrade `scripts/scaffold_loop.py` so a new caretaker loop is fully five-checkpoint-complete on a single command, with all conventions baked in.

**Risk: medium.** Modifies a 197-line script in place across the templates + adds the auto-patcher. Mitigations:
- Dry-run by default — script never modifies anything without `--apply`.
- Atomic tempdir transaction — failure leaves working tree untouched.
- Golden-file tests cover the diff shape against a fixture name.
- Self-validation canary scaffolds a throwaway loop, validates against `make quality`, then reverts.

**Backward compatibility:** existing CLI signature continues to work. The new `--apply` flag is additive; the new five-checkpoint auto-patcher activates whenever the patcher's targets are present (always true in the live repo, so this is effectively unconditional after upgrade).

### Task 3.1 — Templates directory

**Create** `scripts/scaffold_templates/loop.py.j2`:

```jinja
"""{{ name_title }}Loop — {{ description }}

Generated by scripts/scaffold_loop.py on {{ today }}.
Implements the five-checkpoint wiring + ADR-0049 in-body kill-switch.
"""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.{{ snake }}")


class {{ pascal }}Loop(BaseBackgroundLoop):
    """{{ description }}"""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: Any,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="{{ snake }}",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.{{ snake }}_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch (universal mandate).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Static config gate (defense-in-depth: deploy-time disable).
        if not self._config.{{ snake }}_enabled:
            return {"status": "config_disabled"}

        # TODO(scaffold): implement loop body. Return a dict[str, Any]
        # (or None when the tick was a no-op).
        return {"status": "ok"}
```

**Create** `scripts/scaffold_templates/state_mixin.py.j2`:

```jinja
"""State mixin for {{ pascal }}Loop. Generated on {{ today }}."""

from __future__ import annotations


class {{ pascal }}StateMixin:
    """Per-{{ snake }}-loop state accessors.

    TODO(scaffold): add fields the loop needs. Example pattern (uncomment
    + adjust):

    def get_{{ snake }}_attempts(self, key: str) -> int:
        return int(self._data.{{ snake }}_attempts.get(key, 0))
    """
```

**Create** `scripts/scaffold_templates/test_loop.py.j2`:

```jinja
"""{{ pascal }}Loop unit tests. Generated on {{ today }}."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from {{ snake }}_loop import {{ pascal }}Loop
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True, **config_overrides):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    state = MagicMock()
    loop = {{ pascal }}Loop(
        config=deps.config,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, state


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "{{ snake }}"


def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, {{ snake }}_interval=180)
    assert loop._get_default_interval() == 180


@pytest.mark.asyncio
async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_static_config_disable_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_{{ upper }}_ENABLED", "false")
    loop, _ = _make_loop(tmp_path, enabled=True)
    result = await loop._do_work()
    assert result == {"status": "config_disabled"}
```

- [ ] **Step 1: Create the three template files** above.

- [ ] **Step 2: Commit**

```bash
git add scripts/scaffold_templates/
git commit -m "feat(scaffold): Jinja2 templates for new caretaker loops"
```

### Task 3.2 — `scaffold_loop.py` CLI entry + arg parsing + dry-run

**Create** `scripts/scaffold_loop.py`:

```python
#!/usr/bin/env python3
"""Scaffold a new caretaker loop with all conventions correct.

Usage:
    python scripts/scaffold_loop.py NAME [--description "one-line desc"]
                                          [--type caretaker|subprocess]
                                          [--dry-run]
                                          [--apply]

NAME: snake_case loop name (e.g., "blarg_monitor"). Generated class name
will be PascalCase ("BlargMonitorLoop").

Default behavior: dry-run. Prints unified diff of all planned edits and
asks `Apply? [y/N]`. Use `--apply` to skip the prompt (for CI).

The script:
1. Refuses to run on a dirty working tree.
2. Renders three new files from scripts/scaffold_templates/.
3. Patches the five-checkpoint files (models.py, state/__init__.py,
   config.py, service_registry.py, orchestrator.py, ui constants,
   _common.py, scenario catalog, functional_areas.yml).
4. File-level tempdir transaction: writes everything to a tmpdir,
   validates the result imports, bulk-copies to working tree on success.
5. Runs `make arch-regen` after apply.

Spec: docs/superpowers/specs/2026-04-26-dark-factory-infrastructure-hardening-design.md §3.2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import jinja2

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "scaffold_templates"


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Thin subprocess.run wrapper with sane defaults."""
    return subprocess.run(
        cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=check
    )


def _ensure_clean_tree() -> None:
    """Refuse to run on a dirty working tree — apply must be atomic."""
    out = _run(["git", "status", "--porcelain"]).stdout.strip()
    if out:
        sys.stderr.write(
            "scaffold-loop: working tree is dirty. Stash or commit before running.\n"
            f"Dirty:\n{out}\n"
        )
        sys.exit(2)


def _names(snake: str) -> dict[str, str]:
    """Compute the case variants the templates need."""
    parts = snake.split("_")
    pascal = "".join(p.title() for p in parts)
    return {
        "snake": snake,
        "pascal": pascal,
        "name_title": " ".join(p.title() for p in parts),
        "upper": snake.upper(),
        "today": dt.date.today().isoformat(),
    }


def _render_templates(names: dict[str, str], description: str) -> dict[Path, str]:
    """Return {target_path: rendered_content} for all template-emitted files."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
    )
    ctx = {**names, "description": description}
    return {
        REPO_ROOT / f"src/{names['snake']}_loop.py": env.get_template("loop.py.j2").render(ctx),
        REPO_ROOT / f"src/state/_{names['snake']}.py": env.get_template("state_mixin.py.j2").render(ctx),
        REPO_ROOT / f"tests/test_{names['snake']}_loop.py": env.get_template("test_loop.py.j2").render(ctx),
    }


def _print_planned_edits(rendered: dict[Path, str], patches: list[tuple[Path, str]]) -> None:
    """Print a human-readable summary of all planned edits (the dry-run output)."""
    print("\n=== New files ===")
    for path in rendered:
        rel = path.relative_to(REPO_ROOT)
        print(f"  CREATE {rel} ({len(rendered[path])} chars)")
    print("\n=== Five-checkpoint patches ===")
    for path, summary in patches:
        rel = path.relative_to(REPO_ROOT)
        print(f"  PATCH  {rel}: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Preserve existing CLI signature for backward-compat:
    #   python scripts/scaffold_loop.py NAME LABEL DESCRIPTION --interval N
    parser.add_argument("name", help="snake_case loop name")
    parser.add_argument("label", nargs="?", default=None, help="Human-readable label (optional)")
    parser.add_argument("description", nargs="?", default="No description provided.")
    parser.add_argument("--interval", type=int, default=3600, help="Default interval seconds")
    parser.add_argument("--type", choices=["caretaker", "subprocess"], default="caretaker")
    parser.add_argument("--dry-run", action="store_true", help="default; print diff and exit")
    parser.add_argument("--apply", action="store_true", help="skip the y/N prompt")
    args = parser.parse_args()

    if args.type == "subprocess":
        sys.stderr.write(
            "scaffold-loop: --type=subprocess not yet implemented; falling "
            "back to caretaker template.\n"
        )

    _ensure_clean_tree()

    names = _names(args.name)
    rendered = _render_templates(names, args.description)
    # NOTE: Five-checkpoint patches are computed in Task 3.3 below.
    patches: list[tuple[Path, str]] = []  # populated by Task 3.3

    _print_planned_edits(rendered, patches)

    if args.dry_run and not args.apply:
        print("\nDry-run mode (default). Use --apply to write the files.")
        return 0

    if not args.apply:
        ans = input("\nApply all edits? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return 1

    # Task 3.4 wires the file-level tempdir transaction here.
    raise NotImplementedError("Task 3.4 wires the apply transaction.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 1: Make the script executable**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
chmod +x scripts/scaffold_loop.py
```

- [ ] **Step 2: Smoke test the dry-run path**

```bash
python scripts/scaffold_loop.py blarg_monitor --description "Watches blargs."
```

Expected: prints the three new file paths and "No five-checkpoint patches yet (Task 3.3)". Exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/scaffold_loop.py
git commit -m "feat(scaffold): scaffold_loop.py CLI skeleton (templates only)"
```

### Task 3.3 — Five-checkpoint patcher

**Modify** `scripts/scaffold_loop.py` — replace the empty `patches` list with a real patcher that computes (but does NOT yet apply) the planned edits to the 9 wiring files.

The patcher reads each target file, computes the new content (with the appended block), returns `(path, new_content)` pairs. The new_content strings are passed to the apply transaction in Task 3.4.

For brevity, this plan documents the patcher's STRUCTURE — the actual marker-based string editing is mechanical and should be derived by reading each target file.

```python
def _compute_patches(names: dict[str, str], description: str) -> list[tuple[Path, str]]:
    """Compute (target_path, new_content) for each five-checkpoint file.

    Each patch is a string substitution against a stable marker.
    Markers identified by reading existing wired loops (e.g., flake_tracker).
    """
    snake = names["snake"]
    pascal = names["pascal"]
    upper = names["upper"]
    patches: list[tuple[Path, str]] = []

    # 1. src/models.py — append two StateData fields.
    models_path = REPO_ROOT / "src/models.py"
    models_text = models_path.read_text()
    # Marker: the existing trust-fleet block.
    new_fields = (
        f"    # {pascal}Loop state\n"
        f"    {snake}_attempts: dict[str, int] = Field(default_factory=dict)\n"
    )
    # Insert after "# Trust fleet — caretaker loops" block.
    marker = "    flake_attempts: dict[str, int]"
    new_models = models_text.replace(marker, new_fields + marker)
    patches.append((models_path, new_models))

    # 2. src/state/__init__.py — import + MRO.
    state_init_path = REPO_ROOT / "src/state/__init__.py"
    state_text = state_init_path.read_text()
    import_line = f"from ._{snake} import {pascal}StateMixin\n"
    # Insert in alphabetical position (after AutoAgentStateMixin).
    state_text = state_text.replace(
        "from ._auto_agent import AutoAgentStateMixin\n",
        f"from ._auto_agent import AutoAgentStateMixin\n{import_line}",
    )
    state_text = state_text.replace(
        "    AutoAgentStateMixin,",
        f"    AutoAgentStateMixin,\n    {pascal}StateMixin,",
    )
    patches.append((state_init_path, state_text))

    # 3. src/config.py — env override + HydraFlowConfig fields.
    config_path = REPO_ROOT / "src/config.py"
    config_text = config_path.read_text()
    env_row = f'    ("{snake}_interval", "HYDRAFLOW_{upper}_INTERVAL", 3600),\n'
    config_text = config_text.replace(
        '    ("auto_agent_preflight_interval",',
        env_row + '    ("auto_agent_preflight_interval",',
    )
    fields_block = f'''
    {snake}_enabled: bool = Field(
        default=True,
        description="UI kill-switch for {pascal}Loop (ADR-0049).",
    )
    {snake}_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between {pascal}Loop cycles (default 1h).",
    )
'''
    config_text = config_text.replace(
        "    auto_agent_preflight_enabled: bool = Field(",
        fields_block + "    auto_agent_preflight_enabled: bool = Field(",
    )
    patches.append((config_path, config_text))

    # 4. src/service_registry.py — import + dataclass field + construction + ServiceRegistry kwarg.
    sr_path = REPO_ROOT / "src/service_registry.py"
    sr_text = sr_path.read_text()
    sr_text = sr_text.replace(
        "from auto_agent_preflight_loop import AutoAgentPreflightLoop\n",
        f"from auto_agent_preflight_loop import AutoAgentPreflightLoop\nfrom {snake}_loop import {pascal}Loop\n",
    )
    sr_text = sr_text.replace(
        "    auto_agent_preflight_loop: AutoAgentPreflightLoop\n",
        f"    auto_agent_preflight_loop: AutoAgentPreflightLoop\n    {snake}_loop: {pascal}Loop\n",
    )
    construction = f"""
    {snake}_loop = {pascal}Loop(  # noqa: F841
        config=config,
        state=state,
        deps=loop_deps,
    )
"""
    sr_text = sr_text.replace(
        "    auto_agent_audit_store = PreflightAuditStore",
        construction + "\n    auto_agent_audit_store = PreflightAuditStore",
    )
    sr_text = sr_text.replace(
        "        auto_agent_preflight_loop=auto_agent_preflight_loop,",
        f"        auto_agent_preflight_loop=auto_agent_preflight_loop,\n        {snake}_loop={snake}_loop,",
    )
    patches.append((sr_path, sr_text))

    # 5. src/orchestrator.py — bg_loop_registry + loop_factories.
    orch_path = REPO_ROOT / "src/orchestrator.py"
    orch_text = orch_path.read_text()
    orch_text = orch_text.replace(
        '            "auto_agent_preflight": svc.auto_agent_preflight_loop,',
        f'            "auto_agent_preflight": svc.auto_agent_preflight_loop,\n            "{snake}": svc.{snake}_loop,',
    )
    orch_text = orch_text.replace(
        '            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),',
        f'            ("auto_agent_preflight", self._svc.auto_agent_preflight_loop.run),\n            ("{snake}", self._svc.{snake}_loop.run),',
    )
    patches.append((orch_path, orch_text))

    # 6. src/ui/src/constants.js — three sites.
    consts_path = REPO_ROOT / "src/ui/src/constants.js"
    consts_text = consts_path.read_text()
    consts_text = consts_text.replace(
        "'auto_agent_preflight'])",
        f"'auto_agent_preflight', '{snake}'])",
    )
    consts_text = consts_text.replace(
        "  auto_agent_preflight: 120,\n}",
        f"  auto_agent_preflight: 120,\n  {snake}: 3600,\n}}",
    )
    consts_text = consts_text.replace(
        "  { key: 'auto_agent_preflight',",
        f"  {{ key: '{snake}', label: '{names['name_title']}', description: '{description}', color: theme.purple, group: 'autonomy', tags: ['scaffold'] }},\n  {{ key: 'auto_agent_preflight',",
    )
    patches.append((consts_path, consts_text))

    # 7. src/dashboard_routes/_common.py — _INTERVAL_BOUNDS.
    common_path = REPO_ROOT / "src/dashboard_routes/_common.py"
    common_text = common_path.read_text()
    common_text = common_text.replace(
        '"auto_agent_preflight": (60, 600),',
        f'"auto_agent_preflight": (60, 600),\n    "{snake}": (60, 86400),',
    )
    patches.append((common_path, common_text))

    # 8. tests/scenarios/catalog/loop_registrations.py — _build_NAME + _BUILDERS.
    cat_path = REPO_ROOT / "tests/scenarios/catalog/loop_registrations.py"
    cat_text = cat_path.read_text()
    builder = f'''
def _build_{snake}(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    """Build {pascal}Loop for scenarios."""
    from {snake}_loop import {pascal}Loop  # noqa: PLC0415
    state = ports.get("{snake}_state") or MagicMock()
    ports.setdefault("{snake}_state", state)
    return {pascal}Loop(config=config, state=state, deps=deps)


'''
    cat_text = cat_text.replace(
        "def _build_auto_agent_preflight(",
        builder + "def _build_auto_agent_preflight(",
    )
    cat_text = cat_text.replace(
        '    "auto_agent_preflight": _build_auto_agent_preflight,',
        f'    "auto_agent_preflight": _build_auto_agent_preflight,\n    "{snake}": _build_{snake},',
    )
    patches.append((cat_path, cat_text))

    # 9. docs/arch/functional_areas.yml — append to autonomy area's loops:.
    fa_path = REPO_ROOT / "docs/arch/functional_areas.yml"
    fa_text = fa_path.read_text()
    fa_text = fa_text.replace(
        "      - AutoAgentPreflightLoop\n",
        f"      - AutoAgentPreflightLoop\n      - {pascal}Loop\n",
    )
    patches.append((fa_path, fa_text))

    return patches
```

- [ ] **Step 1: Apply the patcher addition** to `scripts/scaffold_loop.py`. Replace the empty `patches = []` line in `main()` with `patches = _compute_patches(names, args.description)`.

- [ ] **Step 2: Smoke test dry-run**

```bash
python scripts/scaffold_loop.py blarg_monitor --description "Watches blargs."
```

Expected: prints the three CREATE lines + 9 PATCH lines.

- [ ] **Step 3: Commit**

```bash
git add scripts/scaffold_loop.py
git commit -m "feat(scaffold): five-checkpoint patcher (computed, not yet applied)"
```

### Task 3.4 — File-level tempdir transaction (apply path)

**Modify** `scripts/scaffold_loop.py` — replace the `raise NotImplementedError` in `main()` with the real apply path.

```python
def _apply_atomic(rendered: dict[Path, str], patches: list[tuple[Path, str]]) -> None:
    """File-level tempdir transaction: write all changes to a tempdir
    mirror, validate the result, bulk-copy on success.

    Tempdir mirror approach: copy the entire repo into the tempdir,
    apply all changes there, validate via `python -c "import ..."`,
    then bulk-copy back. If validation fails, the tempdir is discarded
    and the working tree is untouched.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        # Copy everything, but skip .git, venv, node_modules, .claude.
        shutil.copytree(
            REPO_ROOT,
            tmp_root / "repo",
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", ".venv", "__pycache__", ".claude",
            ),
            symlinks=True,
        )
        tmp_repo = tmp_root / "repo"

        # Apply new files.
        for target, content in rendered.items():
            tmp_target = tmp_repo / target.relative_to(REPO_ROOT)
            tmp_target.parent.mkdir(parents=True, exist_ok=True)
            tmp_target.write_text(content)

        # Apply patches.
        for target, content in patches:
            tmp_target = tmp_repo / target.relative_to(REPO_ROOT)
            tmp_target.write_text(content)

        # Validate: the new loop module must import cleanly.
        snake = next(iter(rendered)).stem.replace("_loop", "")
        validate = subprocess.run(
            ["uv", "run", "python", "-c", f"import sys; sys.path.insert(0, 'src'); import {snake}_loop"],
            cwd=tmp_repo,
            capture_output=True, text=True,
        )
        if validate.returncode != 0:
            sys.stderr.write(
                f"scaffold-loop: validation failed in tempdir.\n"
                f"stderr:\n{validate.stderr}\n"
                f"stdout:\n{validate.stdout}\n"
                "Working tree NOT modified.\n"
            )
            sys.exit(3)

        # Bulk-copy back. New files first, then patches.
        for target, _ in {**rendered, **dict(patches)}.items():
            tmp_source = tmp_repo / target.relative_to(REPO_ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_source, target)

    print("scaffold-loop: apply complete. Running make arch-regen...")
    _run(["make", "arch-regen"])
    print("scaffold-loop: done. Next: implement _do_work body, run tests, commit.")
```

Replace `raise NotImplementedError(...)` in `main()` with:

```python
    _apply_atomic(rendered, patches)
    return 0
```

- [ ] **Step 1: Apply the addition.**

- [ ] **Step 2: End-to-end smoke test**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
python scripts/scaffold_loop.py canary_monitor --description "Canary loop for scaffold validation." --apply
```

Expected: creates the three new files, patches the 9 sites, runs `make arch-regen`. Then run `make quality` to verify the canary loop passes all checkpoints.

- [ ] **Step 3: Revert the canary**

```bash
git restore --source=HEAD --staged --worktree -- .
git clean -fd
```

- [ ] **Step 4: Commit the script**

```bash
git add scripts/scaffold_loop.py
git commit -m "feat(scaffold): file-level tempdir-transaction atomic apply"
```

### Task 3.5 — Golden-file tests for scaffold

**Create** `tests/test_scaffold_loop.py`:

```python
"""scripts/scaffold_loop.py golden-file tests.

Runs the scaffold against a fixture name and asserts the rendered template
output matches a committed golden file. Catches accidental template changes
(e.g., variable rename, formatter pass) that would otherwise silently affect
all future scaffolded loops.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture()
def fixture_names() -> dict[str, str]:
    from importlib import import_module

    # `scaffold_loop.py` is in scripts/ — already snake_case, can import directly.
    scaffold_loop = import_module("scaffold_loop")
    return scaffold_loop._names("fixture_loop")


def test_loop_template_renders_expected(fixture_names: dict[str, str]) -> None:
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    rendered = scaffold_loop._render_templates(fixture_names, "Fixture description.")

    loop_path = next(p for p in rendered if p.name == "fixture_loop_loop.py")
    content = rendered[loop_path]

    # Anchored assertions on stable invariants of the template:
    assert "class FixtureLoopLoop(BaseBackgroundLoop):" in content
    assert "if not self._enabled_cb(self._worker_name):" in content
    assert "return {\"status\": \"disabled\"}" in content
    assert "self._config.fixture_loop_enabled" in content
    assert "self._config.fixture_loop_interval" in content


def test_state_template_renders_expected(fixture_names: dict[str, str]) -> None:
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    rendered = scaffold_loop._render_templates(fixture_names, "Fixture description.")

    state_path = next(p for p in rendered if p.name == "_fixture_loop.py")
    content = rendered[state_path]

    assert "class FixtureLoopStateMixin:" in content
```

- [ ] **Step 1: Run the test**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
uv run pytest tests/test_scaffold_loop.py -v
```

Expected: 2 tests pass.

- [ ] **Step 2: Commit**

```bash
git add tests/test_scaffold_loop.py
git commit -m "test(scaffold): golden-file tests for scaffold templates"
```

### Task 3.6 — Self-validation canary

End-to-end validation: scaffold a throwaway loop, verify all auto-discovery tests pass against it, then revert.

- [ ] **Step 1: Scaffold the canary**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/dark-factory-infra-spec
python scripts/scaffold_loop.py canary_validation --description "Self-validation canary." --apply
```

- [ ] **Step 2: Run the auto-discovery tests against the canary**

```bash
uv run pytest \
    tests/test_loop_wiring_completeness.py \
    tests/architecture/test_functional_area_coverage.py \
    tests/architecture/test_curated_drift.py \
    tests/test_canary_validation_loop.py \
    -m "" -v
```

Expected: all pass. If any fail, the scaffold templates are wrong — fix them.

- [ ] **Step 3: Revert the canary entirely**

```bash
git restore --source=HEAD --staged --worktree -- .
git clean -fd
```

Verify with `git status`: clean working tree.

### Task 3.7 — Verification + push + open PR3

- [ ] **Step 1: Full quality gate**

```bash
make quality 2>&1 | tail -8
```

Expected: 11700+ tests pass, 0 failures (including the 2 new scaffold golden tests).

- [ ] **Step 2: Rebase + push**

```bash
git fetch origin main
git rebase origin/main -X theirs
make arch-regen 2>&1 | tail -3
git add -A && git commit -m "chore(arch): regen after rebase" --allow-empty
git push --force-with-lease
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(scaffold): scripts/scaffold_loop.py with atomic apply" --body "$(cat <<'EOF'
## Summary

PR 3 of 3 in the dark-factory infrastructure hardening track. Final piece.

- **`scripts/scaffold_loop.py`** — CLI scaffold for new caretaker loops. Generates loop file + state mixin + tests; patches the 9 five-checkpoint sites; file-level tempdir-transaction atomic apply; refuses to run on a dirty working tree; dry-run by default.
- **`scripts/scaffold_templates/`** — Jinja2 templates with ADR-0049 in-body kill-switch + static config gate baked in.
- **`tests/test_scaffold_loop.py`** — golden-file tests for the templates.

Self-validation canary: scaffolded a throwaway loop, verified it passes `test_loop_wiring_completeness.py` + `test_functional_area_coverage.py` + `test_curated_drift.py`, then reverted. The scaffold output passes every test the codebase enforces.

## Test plan

- [x] `uv run pytest tests/test_scaffold_loop.py` — 2 tests pass.
- [x] Self-validation canary scaffolded + verified + reverted.
- [x] `make quality` — full suite passes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Final verification

After all three PRs merge:

- [ ] **Run full quality gate** — `make quality` should pass with no regressions.
- [ ] **Verify the conventions are now enforced** — try writing a NEW loop without using `scaffold_loop.py` and confirm `tests/test_loop_wiring_completeness.py` fails. Try writing a new subprocess runner without inheriting `BaseSubprocessRunner` and confirm code review flags the missing auth-retry / reraise.
- [ ] **Verify the dashboard signal** — Auto-Agent's `resolution_rate` should still show real values (no behavior regression from the `BaseSubprocessRunner` migration).
- [ ] **Update `docs/wiki/dark-factory.md` §6** — note that the planned infrastructure (`BaseSubprocessRunner`, `scripts/scaffold_loop.py`, auto-PRPort conformance, pre-commit arch-regen, ADR-0051) is now landed.
