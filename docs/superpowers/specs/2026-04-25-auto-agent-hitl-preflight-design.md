# Auto-Agent HITL Pre-Flight Loop — Design Spec

**Status:** Draft (2026-04-25)
**ADR:** Will need a new ADR (`ADR-0050-auto-agent-hitl-preflight.md`) once design is approved.
**Related ADRs:** ADR-0001 (async loops), ADR-0002 (labels as state machine), ADR-0029 (caretaker loop pattern), ADR-0044 (principles), ADR-0045 (trust architecture), ADR-0049 (kill-switch convention).

## §1 Motivation

### The dark-factory contract

HydraFlow's stated operating model is **lights-off**: the system runs autonomously for any software project meeting the spec, and humans are paged only for genuine fires.

Today, that contract is broken at one specific seam: the `hitl-escalation` label fires for ~25 distinct failure conditions across phases and caretaker loops, and *every one of them goes straight to a human*. There is no autonomous "try to fix this first" layer between the escalating loop and the human queue. As a result:

- Routine, mechanically-resolvable failures (flaky test, drifted cassette, mergeable rebase, lint regression) demand the same human attention as genuinely novel failures.
- The human queue is dominated by toil that the system itself could resolve.
- The dark-factory promise — that any well-specified project runs without operator involvement — is broken.

### What "Auto-Agent" is

This spec adds a new caretaker loop, **`AutoAgentPreflightLoop`**, that intercepts every `hitl-escalation`-labeled issue *before* the human sees it. The loop:

1. Reads the issue + the originating loop's `escalation_context` + the wiki + recent Sentry events + recent commits.
2. Spawns a Claude Code subprocess in the issue's worktree, given a parameterized "lead engineer" persona prompt routed by the escalation sub-label.
3. The agent attempts a real fix — refactor, write code, open a PR — or returns `needs_human` with a precise diagnosis.
4. Up to 3 attempts per issue, each subsequent attempt seeing what prior attempts tried and ruled out.
5. On success: closes the loop autonomously. On failure: applies a new `human-required` label that becomes the *actual* page-a-human signal.

The human watches `human-required`. The human never watches `hitl-escalation` directly anymore.

### What changes for the operator

| Today | After |
|---|---|
| Operator watches `hitl-escalation` items in the UI HITL panel. | Operator watches `human-required` items in the UI HITL panel. |
| Every escalating loop pages immediately. | Loop pre-flights for ~3–10 minutes (one cycle) before paging. |
| Diagnosis quality varies — sometimes a stack trace, sometimes a one-line "CI failed". | Failed pre-flights produce a structured diagnosis comment with what was tried, what was ruled out, and what the agent thinks the human should do next. |
| No observability into "what does HydraFlow's own agent think?" | A new `Auto-Agent` dashboard tile shows resolution rates, p50/p95 cost and wall-clock, top-spend issues, sub-label breakdown. |

### Non-goals

- **Not** a fire-suppression layer. Sentry-direct alerts, secret-scan blocks, orchestrator crash loops continue to use existing emergency channels — Auto-Agent is about *issue-queue triage*, not *runtime emergencies*.
- **Not** a replacement for `DiagnosticLoop`. Diagnostic stays focused on `hydraflow-diagnose` issues; Auto-Agent generalizes to all `hitl-escalation` items.
- **Not** a replacement for `PRUnsticker`. Unsticker continues to handle in-flight HITL items with open PRs (conflict rebase, CI re-run, etc.).
- **Not** an unbounded autonomy expansion. Hard tool restrictions (no CI config edits, no force-push, no secret writes, no self-modification of the principles-audit code) are enforced at the worktree-tool layer.

## §2 Architecture

### §2.1 Loop scaffolding

New file: `src/auto_agent_preflight_loop.py`. Class: `AutoAgentPreflightLoop`. Inherits `BaseBackgroundLoop`. `worker_name = "auto_agent_preflight"`. Default interval = 120 seconds. `run_on_startup = False`.

Wired to all five checkpoints per ADR-0049 universal mandate:

1. `HydraFlowConfig.auto_agent_preflight_interval` (config field)
2. `service_registry` (loop registration)
3. `Orchestrator.bg_loop_registry` (live registry)
4. `src/ui/src/constants.js::SYSTEM_WORKER_INTERVALS` (UI tab)
5. `src/_INTERVAL_BOUNDS` and `tests/scenarios/catalog/loop_registrations.py` (validation + scenario catalog)

In-body `enabled_cb` gate at the top of `_do_work`:

```python
async def _do_work(self) -> dict[str, Any] | None:
    if not self._enabled_cb(self._worker_name):
        return {"status": "disabled"}
    ...
```

### §2.2 Label state machine

Extends ADR-0002. Adds the following new labels (all set exclusively by `AutoAgentPreflightLoop`; cleared by humans or by a future label-cleanup loop after issue close):

| Label | Meaning | When applied |
|---|---|---|
| `human-required` | Pre-flight has bailed; this issue actually needs a human now. | Every escalation result other than `resolved`. |
| `auto-agent-fatal` | Subprocess crashed — the system itself is broken, not "this issue is hard". | Paired with `human-required` when `PreflightResult.status == "fatal"`. |
| `auto-agent-exhausted` | Three pre-flight attempts ran without resolution. | Paired with `human-required` when `auto_agent_attempts[issue] >= max_attempts`. |
| `auto-agent-pr-failed` | Agent returned `resolved` but PR creation failed. | Paired with `human-required` when `PreflightResult.status == "pr_failed"`. |
| `cost-exceeded` | Operator-set cost cap fired mid-attempt. | Paired with `human-required` when `PreflightResult.status == "cost_exceeded"`. |
| `timeout` | Operator-set wall-clock cap fired mid-attempt. | Paired with `human-required` when `PreflightResult.status == "timeout"`. |

Existing labels keep their semantics:

- `hitl-escalation` — applied by escalating loops/phases exactly like today (no call-site changes anywhere). Now means *"pre-flight needed"* rather than *"human needed"*.
- All sub-labels (`flaky-test-stuck`, `principles-violation`, `revert-conflict`, etc.) are unchanged.

### §2.3 State transitions

```
escalating loop adds (hitl-escalation + sub-label)
       │
       ▼
AutoAgentPreflightLoop._do_work polls open issues with `hitl-escalation`
       │
       ▼
sub-label in deny-list?  ──yes──► add `human-required`, audit "skipped: deny-list", done
       │ no
       ▼
auto_agent_attempts[issue] >= max_attempts (3)?  ──yes──► add `human-required` + `auto-agent-exhausted`, done
       │ no
       ▼
daily budget exhausted?  ──yes──► return {"status": "budget_exceeded"}, retry next cycle
       │ no
       ▼
gather PreflightContext (issue + escalation_context + wiki + sentry + commits + prior attempts)
       │
       ▼
spawn PreflightAgent (Claude Code in worktree, persona-prompted, sub-label-routed)
       │
       ▼
PreflightResult { status, pr_url?, diagnosis, cost_usd, wall_clock_s, tokens }
       │
       ▼
record audit (always)
       │
       ▼
PreflightDecision applies labels:
  resolved      → remove `hitl-escalation` + sub-label, append diagnosis comment, link PR
  needs_human   → add `human-required` + diagnosis comment (keep `hitl-escalation` for trail)
  fatal         → add `human-required` + `auto-agent-fatal` + crash trace
  pr_failed     → add `human-required` + `auto-agent-pr-failed` + agent diagnosis
  cost_exceeded → add `human-required` + `cost-exceeded` + partial diagnosis
  timeout       → add `human-required` + `timeout` + partial diagnosis
```

Sequential: one issue per cycle. Bounds concurrent cost. Acceptable because pre-flight latency tolerance is "minutes", not "seconds".

## §3 Components

Five focused modules, each independently testable. All under `src/preflight/` except the loop itself.

### §3.1 `AutoAgentPreflightLoop` (`src/auto_agent_preflight_loop.py`)

The loop scaffolding. Roughly 200 lines. Responsibilities:

- Poll `hitl-escalation`-labeled open issues that don't already have `human-required`.
- For each issue (sequential): apply the deny-list / attempt-cap / budget gates, gather context, spawn agent, apply decision, record audit, emit subprocess trace (`emit_loop_subprocess_trace`).
- Respect `stop_event` between issues.
- Status payload: `{"status": "ok" | "disabled" | "budget_exceeded", "issues_processed": N, "resolved": N, "escalated": N, "fatal": N}`.

### §3.2 `PreflightContext` (`src/preflight/context.py`)

Pure data-gathering, no I/O side effects. Inputs: `issue_number`, `issue_body`, `sub_label`, `prior_attempts: list[PreflightAuditEntry]`. Outputs:

```python
@dataclass(frozen=True)
class PreflightContext:
    issue_number: int
    issue_body: str
    issue_comments: list[IssueComment]  # last 10
    sub_label: str
    escalation_context: EscalationContext | None  # from state.get_escalation_context(); see note below
    wiki_excerpts: str  # from RepoWikiStore.query()
    sentry_events: list[SentryEvent]  # from new reverse-lookup helper, may be empty
    recent_commits: list[CommitRef]  # git log --since=7d on files mentioned
    sublabel_extras: dict[str, Any]  # e.g. flake_tracker state for flaky-test-stuck
    prior_attempts: list[PreflightAuditEntry]
```

`EscalationContext` is the existing Pydantic model in `src/models.py:950`. **Important constraint:** only `review_phase` and `phase_utils` populate it today — most caretaker-loop escalations (flake_tracker, wiki_rot_detector, rc_budget, skill_prompt_eval, fake_coverage_auditor, contract_refresh, trust_fleet_sanity) never call `set_escalation_context`, so `escalation_context` will be `None` for the majority of pre-flight invocations. The agent prompt template MUST handle this — when context is `None`, the prompt operates on issue body + sub-label + wiki + sentry alone, and the prompt template renders an explicit "no escalation context — operate on issue body" block instead of the structured escalation breakdown.

The Sentry reverse-lookup is new; it queries Sentry's API by issue title + stack-trace fingerprint. On failure, returns `[]` and logs at warning level — does not block the pre-flight.

### §3.3 `PreflightAgent` (`src/preflight/agent.py`)

The Travis-emulator wrapper. Spawns Claude Code subprocess in the issue's worktree. Loads sub-label-routed prompt from `prompts/auto_agent/<sub_label>.md`, falls back to `prompts/auto_agent/_default.md`. Substitutes `{persona}` from `auto_agent_persona` config field. Captures cost telemetry via existing `prompt_telemetry.py`. Returns:

```python
@dataclass(frozen=True)
class PreflightResult:
    status: Literal["resolved", "needs_human", "fatal", "pr_failed", "cost_exceeded", "timeout"]
    pr_url: str | None
    diagnosis: str
    cost_usd: float
    wall_clock_s: float
    tokens: int
```

Wraps the subprocess with cost-cap and wall-clock-cap watchers (both default `None`/unlimited; see §5). When a cap is hit, sends a soft "wrap up + bail" prompt; if subprocess overruns the soft window by >30s, hard-kills via `process.terminate()` then `kill()` and preserves stdout-so-far as partial diagnosis.

### §3.4 `PreflightDecision` (`src/preflight/decision.py`)

Pure logic, no I/O. Translates `PreflightResult` + current issue state → label operations. The only place that touches GitHub via `PRPort` / `IssueStorePort`. Idempotent: re-running on the same `(issue, result)` is a no-op. Detects races via atomic `auto_agent_attempts` counter check.

### §3.5 `PreflightAuditStore` (`src/preflight/audit.py`)

Append-only JSONL at `data_root/auto_agent/audit.jsonl`. Each entry:

```json
{
  "ts": "2026-04-25T14:32:11Z",
  "issue": 8501,
  "sub_label": "flaky-test-stuck",
  "attempt_n": 2,
  "prompt_hash": "sha256:...",
  "cost_usd": 1.42,
  "wall_clock_s": 187.4,
  "tokens": 41250,
  "status": "resolved",
  "pr_url": "https://github.com/...",
  "diagnosis": "...",
  "llm_summary": "agent ruled out timing race, found state leak in fixture, added cleanup hook"
}
```

Provides query helpers used by the dashboard endpoint:

- `query_24h() -> AuditWindowStats`
- `query_7d() -> AuditWindowStats`
- `top_spend(n: int = 5) -> list[PreflightAuditEntry]`
- `entries_for_issue(issue: int) -> list[PreflightAuditEntry]`

### §3.6 New helpers

- `src/sentry/reverse_lookup.py` — query Sentry API by title + fingerprint. ~80 lines. VCR-cassette tested.

- **`StateData` field additions** (`src/models.py`, alongside the trust-fleet fields around line 1772):
  - `auto_agent_attempts: dict[str, int] = Field(default_factory=dict)` — issue-id-string → attempt count.
  - `auto_agent_daily_spend: dict[str, float] = Field(default_factory=dict)` — `YYYY-MM-DD` → spend USD.
  These are the persistence layer; the mixin below adds typed accessors but the Pydantic fields are required for serialization to the JSON state file.

- **`src/state/_auto_agent.py`** — new mixin (mirrors `src/state/_flake_tracker.py`). Methods: `get_auto_agent_attempts(issue) -> int`, `bump_auto_agent_attempts(issue) -> int`, `clear_auto_agent_attempts(issue)` (called from issue-close reconciliation, mirrors `clear_flake_attempts`), `get_auto_agent_daily_spend(date_iso) -> float`, `add_auto_agent_daily_spend(date_iso, usd) -> float`. Mixed into `StateTracker` in `src/state/__init__.py` per existing convention.

- **Issue-close reconciliation** — when an issue with `human-required` (or any auto-agent label) closes, call `clear_auto_agent_attempts(issue)` so a future re-open starts fresh. Hook this into the existing close-reconciliation flow that other loops use (mirror `principles_audit_loop._reconcile_closed_escalations`).

## §4 Sub-label routed prompts

Prompts live as Markdown files at `prompts/auto_agent/<sub_label>.md`, mirroring existing prompt-management conventions. ~150–250 lines each. Operator-tunable without code changes.

### §4.1 Shared prompt envelope

Every prompt wraps these blocks (defined once in `prompts/auto_agent/_envelope.md`, included via `{{> envelope}}` partials):

1. **Identity** — substitutes `{persona}` from `auto_agent_persona` config field. Default value: *"the lead engineer for this project — pragmatic, prefers small fixes, leaves regression tests, doesn't over-engineer. When in doubt about scope, do less."*
2. **Context block** — issue body, escalation_context, wiki_excerpts, sentry_events, recent_commits, sublabel_extras.
3. **Previous attempts block** — rendered only when `prior_attempts` is non-empty. Lists each prior attempt's diagnosis + what was tried + why it bailed. This is what makes attempts 2 and 3 useful.
4. **Tool restrictions** — explicit list of paths and operations not permitted (also enforced at runtime, see §5).
5. **Decision protocol** — the agent must terminate by either (a) opening a PR + returning `resolved`, or (b) returning `needs_human` with a precise diagnosis.

### §4.2 Sub-label routing table (initial set)

| Sub-label | Prompt file | Stance |
|---|---|---|
| `flaky-test-stuck` | `prompts/auto_agent/flaky-test-stuck.md` | "Read the test, the recent flake history, the git blame on the test file. Most flakes are timing or order-dependent — fix the test, not the production code. If you can't reproduce, mark `@pytest.mark.flaky(reruns=3)` with a clear comment and open a follow-up issue." |
| `revert-conflict` | `prompts/auto_agent/revert-conflict.md` | "You're cleaning up a staging revert. Goal: get staging green. Don't try to fix the underlying bug — just complete the revert cleanly and add a regression test stub for the next person." |
| `rc-red-bisect-exhausted` | `prompts/auto_agent/rc-red-bisect-exhausted.md` | Same family as revert-conflict; specific guidance on what bisect output reveals. |
| `fake-drift-stuck` | `prompts/auto_agent/fake-drift-stuck.md` | "An adapter cassette has drifted. Re-record from a real fixture if available, otherwise update the fake to match observed behavior + leave a comment explaining the drift." |
| `fake-coverage-stuck` | `prompts/auto_agent/fake-coverage-stuck.md` | Same family as fake-drift-stuck; focuses on coverage holes specifically. |
| `wiki-rot-stuck` | `prompts/auto_agent/wiki-rot-stuck.md` | "Wiki entries are stale. Read what changed in the codebase since the entry was written; rewrite the entry, don't delete it unless the feature is gone." |
| `rc-duration-stuck` | `prompts/auto_agent/rc-duration-stuck.md` | "Release-critical work is taking too long. Look at what's blocking — usually a single PR. Comment on that PR with a specific unblock action; if it's a code issue, propose a patch." |
| `skill-prompt-stuck` | `prompts/auto_agent/skill-prompt-stuck.md` | "A skill prompt evaluation is failing. Read the eval, the prompt, recent changes — usually a regression in prompt structure or output format." |
| `trust-loop-anomaly` | `prompts/auto_agent/trust-loop-anomaly.md` | "A trust-fleet anomaly fired. Read the anomaly type, the loop's recent telemetry. Most anomalies are runtime drift, not bugs — propose a config tune or note that anomaly is expected. Don't modify the loop code itself." |
| `principles-stuck` / `cultural-check` | (n/a — deny-listed) | These bypass pre-flight entirely. The principles audit IS the system that judges Auto-Agent; allowing Auto-Agent to "fix" a principles violation would let it modify the judge. Always escalates straight to `human-required`. |
| (any other / phase escalations) | `prompts/auto_agent/_default.md` | "You're picking up a failed phase. Read the escalation_context, look at what was attempted. Try the obvious recovery; if it's not obvious, escalate with a specific question for the human." |

### §4.3 Adding a new sub-label

1. Drop a new Markdown file at `prompts/auto_agent/<new-sub-label>.md`.
2. No code changes required — `PreflightAgent` looks up by sub-label string and falls back to `_default.md` if absent.
3. Add a corpus entry under `tests/auto_agent/adversarial/corpus/<new-sub-label>/` for regression coverage (see §7).

## §5 Configuration & guardrails

### §5.1 Config fields (new)

All in `HydraFlowConfig`. All ship-defaults shown.

| Field | Type | Default | Purpose |
|---|---|---|---|
| `auto_agent_preflight_enabled` | `bool` | `True` | UI kill-switch (per ADR-0049). |
| `auto_agent_preflight_interval` | `int` | `120` | Seconds between cycles. |
| `auto_agent_persona` | `str` | *"the lead engineer for this project — pragmatic, prefers small fixes, leaves regression tests, doesn't over-engineer. When in doubt about scope, do less."* | Substituted into shared prompt envelope. Operator-tunable. |
| `auto_agent_max_attempts` | `int` | `3` | Per-issue attempt cap before `auto-agent-exhausted`. |
| `auto_agent_skip_sublabels` | `list[str]` | `["principles-stuck", "cultural-check"]` | Sub-labels that bypass pre-flight entirely. Match `principles_audit_loop.py:339-345` exact label names — the principles-audit recursion guard. |
| `auto_agent_cost_cap_usd` | `float \| None` | `None` (unlimited) | Per-attempt cost cap. Code path wired but inactive by default. |
| `auto_agent_wall_clock_cap_s` | `int \| None` | `None` (unlimited) | Per-attempt wall-clock cap. Code path wired but inactive by default. |
| `auto_agent_daily_budget_usd` | `float \| None` | `None` (unlimited) | Per-day total spend budget. Code path wired but inactive by default. |

### §5.2 Always-on tool restrictions

Enforced at the worktree-tool-restriction layer (same mechanism as existing capability gates). The agent receives a tool-call-rejected error when violating any of these:

- `.github/workflows/**` (CI config)
- Branch protection / repo settings
- Force-push, branch deletion, history rewrite
- Secret-pattern matches (existing pre-commit secrets allowlist)
- Self-PR approve / merge
- `src/principles_audit_loop.py`, `src/auto_agent_preflight_loop.py`, ADR-0044 / ADR-0049 implementation files (recursion guard — agent must not modify the system that judges or governs it)

These are correctness constraints, NOT cost-bounding. They are always on regardless of operator overrides.

### §5.3 The "raging fire" path is preserved

Auto-Agent is for *issue-queue triage*. It does NOT intercept:

- Sentry-direct alerts (these go straight to the operator's Sentry-watch channel)
- Pre-commit secret-scan blocks (these stop commits at the developer's machine)
- Orchestrator crash loops (handled by `_restart_loop` + Sentry)
- Anything outside the `hitl-escalation` label flow

If the system itself is on fire, those channels are unaffected.

## §6 Observability

### §6.1 Dashboard tile

New `AutoAgentStats` tile in the System tab UI. Shows:

- **Today:** total spend, attempts, resolved count, resolution rate (%), p50/p95 cost, p50/p95 wall-clock.
- **Last 7 days:** same series, sparklines.
- **Top 5 most-expensive attempts in the window:** issue link, sub-label, cost, wall-clock, status.
- **Per-sub-label breakdown:** attempts and resolution rate per sub-label.
- **Current cycle status:** which issue is being pre-flighted (if any).

No alerts. No threshold notifications. Information surface only — operator decides whether anything looks wrong.

### §6.2 API endpoint

New endpoint: `GET /api/diagnostics/auto-agent`. Returns JSON:

```json
{
  "today": {"spend_usd": 12.40, "attempts": 8, "resolved": 5, "resolution_rate": 0.625, ...},
  "last_7d": {...},
  "top_spend": [...],
  "by_sublabel": {"flaky-test-stuck": {"attempts": 3, "resolved": 3}, ...},
  "in_flight": {"issue": 8501, "sub_label": "flaky-test-stuck", "started_ts": "...", "elapsed_s": 42}
}
```

Reads from `PreflightAuditStore` + StateData. Cached for 30s to bound dashboard load.

### §6.3 Cost / token attribution

Uses existing `prompt_telemetry.py` JSONL stream + `emit_loop_subprocess_trace` timestamp join (the same pattern trust-fleet uses). `worker_name="auto_agent_preflight"` joins to per-attempt traces. The audit JSONL is the per-attempt source of truth; the StateData fields are caches for fast dashboard reads.

### §6.4 No silent-success failures

Every code path that could swallow an error has at least one of: (a) audit entry, (b) Sentry log, (c) label change. Most have all three.

## §7 Failure modes

| Failure | Handling |
|---|---|
| Loop crashes mid-tick | `BaseBackgroundLoop._restart_loop` respawns; Sentry via `LoggingIntegration`; no half-state because issue still has `hitl-escalation` only. |
| Claude Code subprocess crashes | `PreflightResult(status="fatal", ...)`. Decision applies `human-required + auto-agent-fatal`. Audit recorded. Counts toward attempt cap. |
| Wiki query fails | Logged warning, empty wiki block, agent prompt notes "wiki unavailable". Doesn't block. |
| Sentry query fails | Same — logged warning, empty Sentry block. |
| Audit write fails | ERROR-level log (Sentry-visible). Loop continues. Dashboard shows stale data — visible drift, not silent. |
| Issue closes mid-pre-flight | Re-fetch issue state at start of each issue's processing. If closed, skip. |
| `human-required` already added externally | Same re-fetch check before label-swap. If present, audit + bail without double-labeling. |
| Cost cap hit (when operator turns it on) | Subprocess hard-killed. `human-required + cost-exceeded`. Partial diagnosis preserved. |
| Wall-clock cap hit | Same as cost-cap. `human-required + timeout`. |
| Daily budget gate fires | Cycle returns `{"status": "budget_exceeded"}`. Issues stay in `hitl-escalation`. Tomorrow picks up. Dashboard surfaces the gate. |
| Tool restriction violated | Agent gets tool-call-rejected. Can recover or bail. Repeated violations → agent typically bails to `needs_human`. |
| Pre-flight resolves but PR fails to open | `human-required + auto-agent-pr-failed`. Diagnosis preserved with what was changed locally. |
| Two pre-flights racing (defensive) | Single-cycle loop precludes this; defensive: `auto_agent_attempts` atomic check in Decision aborts on race. |
| `escalation_context` missing for caretaker-loop escalations | Most caretaker loops (flake_tracker, wiki_rot_detector, rc_budget, etc.) never call `set_escalation_context`. Prompt template branches on `escalation_context is None` — renders "no structured escalation context — operate from issue body + sub-label + wiki + sentry" rather than failing. The `_default.md` prompt and every sub-label-specific prompt MUST tolerate the missing-context case. |

## §8 Testing strategy

Three test layers, mirrors trust-fleet pattern (ADR-0045).

### §8.1 Unit tests

Files: `tests/test_auto_agent_*.py`. Pure modules, no I/O.

| File | Covers |
|---|---|
| `test_auto_agent_preflight_loop.py` | Kill-switch gate, single-issue-per-tick, deny-list bypass, attempt-cap exhaustion, daily-budget gate, status payload shape. |
| `test_preflight_context.py` | Wiki-query keyword extraction, Sentry-fail-graceful, escalation_context read, sub-label-specific extras, prior-attempts injection on attempts 2/3. |
| `test_preflight_agent.py` | Prompt rendering with persona substitution, sub-label routing to correct prompt file, default fallback, cost telemetry capture, subprocess crash → `fatal`, soft-cap-then-bail, hard-kill on cap. |
| `test_preflight_decision.py` | Each `PreflightResult` status → correct label transition, idempotency on re-runs, race-detection via atomic counter check. |
| `test_preflight_audit_store.py` | JSONL append-only correctness, 24h / 7d aggregator, top-5-spend ranking, entries_for_issue lookup. |

### §8.2 Scenario tests

File: `tests/scenarios/test_auto_agent_preflight.py`. Full loop, mocked GitHub + cassette-fake Claude Code.

| Scenario | Verifies |
|---|---|
| `flaky_test_resolved` | Agent returns resolved + PR → labels swap, audit recorded, no `human-required`. |
| `principles_violation_bypassed` | Sub-label in deny-list → instant `human-required`, no agent spawn, audit notes bypass. |
| `agent_bails_after_3_attempts` | Three sequential `needs_human` results → final state `human-required + auto-agent-exhausted`, all 3 in audit, prior-attempts visible in attempt 2/3 prompts. |
| `subprocess_fatal` | Cassette injects subprocess crash → `human-required + auto-agent-fatal`. |
| `cost_cap_hit` | Operator-set cap, cassette runs over → kill-then-escalate, partial diagnosis preserved. |
| `daily_budget_gate` | StateData seeded; loop skips cycle, dashboard reads 1 budget-block, no label changes. |
| `issue_closed_during_preflight` | Race scenario → agent runs but Decision skips label change. |
| `pr_open_fails` | Agent returns resolved but `gh pr create` returns 500 → `human-required + auto-agent-pr-failed`, diagnosis preserved. |

### §8.3 Adversarial corpus

Directory: `tests/auto_agent/adversarial/corpus/<sub-label>/`. Each entry contains a synthetic-but-realistic issue + cassette-fixed Claude Code outputs + golden expected outcome.

Run via new make target: `make auto-agent-adversarial`.

Initial corpus: one entry per sub-label in §4.2's table. Grows over time as we observe new patterns in production — this is the regression net for "Auto-Agent used to handle X correctly".

### §8.4 Contract tests

File: `tests/contracts/test_sentry_reverse_lookup.py`. VCR cassette of a real Sentry API response → assert the parser extracts the right event metadata. Same VCR pattern as existing Sentry contract tests.

### §8.5 Coverage gates

- `make test` → unit + scenarios pass.
- `make auto-agent-adversarial` → adversarial corpus passes (new target).
- `make trust-contracts` → existing contracts continue to pass (no regressions in shared infra).
- `make quality` → all of the above + lint + typecheck.

No live LLM calls in CI. All cassette-driven.

## §9 Migration & rollout

### §9.1 One-time UI change

UI HITL panel filter changes from `label:hitl-escalation` to `label:human-required`. Single-line change in the React HITL view component. Documented in release notes as a notification-routing change.

### §9.2 No code-side migration

Zero changes to existing escalation call sites. Every loop and phase that currently adds `hitl-escalation` continues to do so. The semantics shift from "human needed" to "pre-flight needed" without any code changes outside the new loop and the UI filter.

### §9.3 Rollout sequence

1. Land all code with `auto_agent_preflight_enabled=False` by default — loop registered but not running.
2. Operator enables loop in System tab once they want to start observing.
3. Watch dashboard for one week with full observability + zero caps.
4. Optionally enable caps if anything looks runaway.

This means the spec can ship to other operators with a safe-by-default off state, and each operator turns it on when ready.

### §9.4 Kill-switch behavior

Per ADR-0049: flipping `auto_agent_preflight_enabled` off in the UI causes the loop to return `{"status": "disabled"}` on its next cycle. In-flight issues already being pre-flighted complete (or hit their cap) and then no new work is picked up. UI HITL panel continues to show `human-required`-labeled items; pre-existing `hitl-escalation`-only items pile up until the loop is re-enabled OR the operator manually labels them.

## §10 Open decisions for the implementation plan

(To be resolved in `superpowers:writing-plans` step.)

1. Exact placement of `PreflightAgent`'s subprocess invocation — does it use `HITLRunner` directly, subclass it, or compose a new `BaseRunner`-derived runner? Trade-off: HITLRunner is purpose-built for human-correction-driven runs; Auto-Agent has different prompt structure. Likely answer: new `AutoAgentRunner` subclass of `BaseRunner`.
2. Whether the Sentry reverse-lookup helper warrants its own ADR (small footprint but new external API surface).
3. Whether to bead-track each sub-label prompt as its own deliverable (10 prompts × 1 bead each), or batch them as one.
4. Whether the new `AutoAgentStats` dashboard tile lives in the existing System tab or warrants its own top-level "Auto-Agent" tab.
5. ADR-0050 wording — does the auto-agent need its own ADR, or is it an extension of ADR-0029 (caretaker loop pattern)?

## §11 Out of scope (explicit)

- Multi-agent coordination (one Auto-Agent per issue, sequentially).
- Cross-issue learning (each pre-flight starts fresh; "memory" is the wiki + audit, not a vector store).
- Chat-style interactive pre-flight (no operator can interject mid-pre-flight).
- Pre-flighting issues in OTHER repos than the current `repo_root`.
- Web dashboard write actions (operator can disable, can't trigger an Auto-Agent run from the UI in v1).

These are deliberate non-features for v1. Each can be added later as its own spec.

---

**End of design spec.**
