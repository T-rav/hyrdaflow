# ADR-0059: Advisor-pattern self-repairing review

- **Status:** Proposed
- **Date:** 2026-05-08
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0001](0001-five-concurrent-async-loops.md) (subagent isolation pattern this builds on); [ADR-0042](0042-two-tier-branch-release-promotion.md) (removed the human merge gate, motivating this work); [ADR-0044](0044-hydraflow-principles.md) (TDD as default; ADR write-after-shipping); [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention this ADR conforms to); [ADR-0051](0051-iterative-production-readiness-review.md) (this feature ran 4 fresh-eyes review passes); [ADR-0052](0052-sandbox-tier-scenarios.md) (Tier-2 scenario placeholder lives here); [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) (terms updated by this ADR); [ADR-0055](0055-otel-honeycomb-instrumentation.md) (telemetry primitive this feature uses).
- **Enforced by:** `tests/test_review_advisor.py` (~100+ unit tests covering all 5 surfaces); `tests/scenarios/test_pr_review_advisor_*.py` (11 Tier-1 MockWorld scenarios); `tests/test_review_phase_core.py::TestSelfModificationGuard` (T29 self-modification guard); `make quality` CI gate.

## Context

Anthropic's "Advisor Strategy" (Code with Claude, May 2026) pairs Opus as **advisor** (thinks, plans, second-opinion) with Sonnet as **executor** (acts, verifies). The pattern shifts cost/quality at the margin: Opus catches false negatives the executor misses, while Sonnet keeps the per-call cost manageable on the hot path.

HydraFlow's two-tier release model ([ADR-0042](0042-two-tier-branch-release-promotion.md)) removed the human merge gate. The `ReviewPhase` became the last line of defense — every PR that lands in `staging` (and thence into the `rc/*` promotion to `main`) had to be cleared by the executor alone. We needed a layered advisor mechanism that:

- catches false negatives the executor misses (post-verify second opinion);
- improves first-pass fix quality (pre-flight planning + mid-flight consultation when stuck);
- replaces the missing human merge gate with **veto authority** on critical surfaces.

Constraint: HydraFlow's runtime cannot use the Anthropic SDK directly (per session memory `feedback_no_direct_anthropic_sdk.md`). All LLM invocations route through Claude Code subagent dispatch — either subprocess agents (existing `runner` pattern) or in-session `Task` tool dispatch with `model=` override. Anthropic's literal "shared advisor session" shape isn't expressible across Claude Code's subagent boundary; we implement it as **artifact-based sharing** instead (scratchpad files + structured prompt context summaries).

## Decision

Implement the advisor pattern as **three role-based advisors** layered onto `ReviewPhase`:

1. **Pre-flight (`PreFlightAdvisor`)** — runs before the executor on a conditional trigger. Produces a `ReviewPlan` JSON (`risk_summary`, `focus_areas`, `rubric`, `escalation_signals`). Plan is written to `review_logs/{pr}/preflight.json` and threaded into both the executor's prompt and the post-verify input.
2. **Mid-flight (`MidFlightAdvisor`)** — the executor session has access to a `consult_advisor` Task-tool template. When stuck on a judgment call (not verifiable), the executor invokes `Task(subagent_type="hydraflow-review-advisor", model="opus", prompt=<midflight template with sentinel marker>)`. Cap: `HYDRAFLOW_REVIEW_MIDFLIGHT_MAX_CONSULTS=5` per review.
3. **Post-verify (`PostVerifyAdvisor`)** — runs after the executor's verdict. Authority is per-surface: `veto` (blocks merge; bounded retry hands transcript back to executor) or `advisory` (downgrades VETO to APPROVE; logs disagreements for calibration).

### Per-surface tiering

The matrix below matches `_SURFACE_DEFAULTS` in `src/review_advisor.py`:

| Surface | Pre-flight | Mid-flight | Post-verify | Authority | `max_veto_retries` |
|---|---|---|---|---|---|
| `pr_review` | conditional (`CompositeTrigger`: LOC + critical paths + prior fix attempts) | yes | yes | `veto` | 2 |
| `pre_merge_spec_check` | piggyback (reuses `pr_review`'s plan) | yes | yes | `veto` | 2 (binary gate) |
| `adr_review` | always (`AlwaysTrigger`) | n/a | yes | `veto` | 2 |
| `visual_gate` | n/a | n/a | yes | `veto` | 1 |
| `wiki_ingest` | n/a | n/a | yes | `advisory`* | 0 |

\* `wiki_ingest`'s advisory authority is upgraded to `veto` when the diff modifies advisor's own implementation (T29 self-modification guard).

## Rules

1. **All LLM invocations route through Claude Code subagent dispatch** — subprocess agents (existing `runner` pattern) or in-session `Task` tool. No direct `anthropic` SDK use anywhere in HydraFlow runtime.
2. **Kill-switch hierarchy** (AND across scopes; default `True` when env unset):
   - Master: `HYDRAFLOW_REVIEW_ADVISOR_ENABLED`
   - Per-role: `HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED`, `HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED`, `HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED`
   - Per-surface: `HYDRAFLOW_<SURFACE>_ADVISOR_ENABLED`
   Kill-switch state is resolved **once per review at start**; mid-review flips do not take effect (consistent with [ADR-0049](0049-trust-loop-kill-switch-convention.md)'s tick-boundary semantics, adapted to per-review boundaries here).
3. **Self-modification guard** (T29) — when a diff modifies `src/review_advisor.py` or `src/review_phase.py`, post-verify authority is **forced to `veto`** regardless of surface config. Prevents the advisor from approving changes to itself in `wiki_ingest` (advisory) mode.
4. **Failure-soft contract** — advisor crashes / parse errors degrade per-role:
   - Pre-flight failure → `None` (executor proceeds without plan).
   - Mid-flight failure → executor proceeds with own judgment.
   - Post-verify failure → APPROVE by default; `HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO=true` flips to VETO for high-trust environments.
5. **Credit/bug error propagation** — every advisor runner calls `reraise_on_credit_or_bug(exc)` in its broad `except` block, per `docs/wiki/dark-factory.md` §2.2. Without this, `CreditExhaustedError` is silently eaten and the review burns retry budget against an exhausted billing signal.
6. **Veto bounded retry** — post-verify VETO hands back the **full advisor transcript** (not just verdict reasoning) to the executor for re-attempt. After `max_veto_retries` exhausted, escalate to HITL with the disagreement transcript attached.
7. **Cross-review state isolation** — `_advisor_attempt`, `_advisor_results`, and `_advisor_pre_flight_plan` reset per review entry. HITL-escalated PRs that come back through review get a fresh budget; nothing leaks across re-reviews.
8. **Explicit `role` Protocol parameter, not substring detection** — initial prototypes inferred role from prompt-text substrings; this misrouted on meta-PRs whose body legitimately quoted role markers. Replaced with an explicit `role` parameter on the advisor Protocol plus a HTML-comment sentinel marker for mid-flight. (T24.5 fix; see Risks below.)

## Telemetry

Nine OTel metrics (all surface-tagged), wired via [ADR-0055](0055-otel-honeycomb-instrumentation.md)'s Honeycomb pipeline:

- `review_advisor_calls_total{surface, role, outcome}`
- `review_advisor_call_duration_seconds{surface, role}` (histogram)
- `review_advisor_post_verify_verdict_total{surface, verdict}`
- `review_advisor_post_verify_degraded_total{surface}`
- `review_advisor_disagreement_total{surface, role, severity}`
- `review_advisor_disagreement_validated_total{surface, role}`
- `review_advisor_veto_retries_total{surface, attempt}`
- `review_advisor_veto_recovered_total{surface}`
- `review_advisor_veto_exhausted_total{surface}`

**Headline KPIs:**

- **Self-repair rate:** `_recovered / (_recovered + _exhausted)` — target ≥0.7 after staging soak. If lower, the advisor's veto reasons aren't actionable enough for the executor to repair on retry.
- **Advisor calibration quality:** `_disagreement_validated_total / _disagreement_total` — target non-zero. A zero numerator over a long window means the advisor is either always right (raise stakes) or always noise (re-tune).
- **Wall-clock budget:** median PR review wall-clock < 1.5× pre-advisor baseline. Per-surface tiering exists to keep this in band.

## Consequences

**Positive:**

- The missing human merge gate is replaced by an Opus advisor with veto authority on all critical surfaces.
- False negatives caught: the advisor independently reviews every executor verdict on `veto`-authority surfaces.
- First-pass fix quality improved: pre-flight rubric + mid-flight consultation + transcript hand-back on retry.
- `wiki_ingest` advisory mode produces calibration data without blocking ingestion (except on self-modification, where authority upgrades to veto).
- Per-surface tiering: heavy machinery only where stakes warrant it (`visual_gate` has only post-verify; trivial PRs skip pre-flight via `CompositeTrigger`).

**Negative:**

- Adds ~3500 lines of code + tests across `src/review_advisor.py`, `src/review_phase.py`, `src/reviewer.py`, `src/mockworld/fakes/fake_llm.py`, and `tests/`.
- Each advisor invocation is a Claude Code subagent dispatch — measurable latency and cost. Mitigated by per-surface tiering and conditional pre-flight (composite trigger skips trivial PRs).
- `src/review_phase.py` grew to ~3700 lines. Phase 5+ should consider extraction (per cumulative review M2, see *When to supersede* below).

**Risks:**

- **Production transcript shape:** transcripts from `claude -p` aren't bare JSON; `_extract_json_block` handles fenced/inline/bare cases. Documented as the T16.5 fix; regression-tested.
- **Substring-based role detection footgun:** the earlier prototype false-positived on meta-PRs whose body contained role markers (this very PR's body would have triggered the bug). Fixed in T24.5 with explicit `role` Protocol parameter + sentinel marker for mid-flight.
- **Cross-review state leak:** `_advisor_*` state on `ReviewPhase` could survive across HITL re-reviews of the same PR. Mitigated by resetting per-PR state at function entry (T16.5 + T18 fixes).
- **Self-modifying diffs:** without the T29 guard, a PR that edits `review_advisor.py` could land via `wiki_ingest`'s advisory mode. Guard forces `veto` authority in that case.

## Alternatives Considered

- **Single Opus executor (no advisor).** Rejected — defeats Anthropic's advisor-strategy cost/quality tradeoff and provides no second-pair-of-eyes signal. Doubles per-review cost without doubling assurance.
- **Direct Anthropic SDK calls for the advisor.** Rejected — violates HydraFlow's runtime dispatch invariant. All LLM calls route through Claude Code subagent dispatch.
- **Single shared advisor session (literal Anthropic shape).** Rejected — Claude Code's subagent boundary doesn't expose literal "shared conversation history". Implemented as artifact-based sharing (scratchpad files + structured prompt-context summaries) — equivalent in effect, expressible in our runtime.
- **Substring-based role detection (initial implementation).** Rejected after Phase 3 fresh-eyes review — meta-PRs containing role markers in their spec body misrouted (I2 finding). Replaced with explicit Protocol parameter + HTML-comment sentinel for mid-flight.
- **Single-tier "always-on" advisor across all surfaces.** Rejected — wall-clock and cost budget forces tiering. `visual_gate` doesn't need pre-flight planning; `wiki_ingest` doesn't warrant veto authority on the steady-state path.

## When to supersede this ADR

- If a future feature replaces the advisor pattern (e.g. a unified executor with built-in second-opinion reasoning), supersede with rationale.
- If empirical KPIs after staging soak deviate significantly from the targets in §Telemetry, supersede with the new tuning + fresh KPI bands.
- If the helper duplication cleanup (Phase 5 cumulative review M1+M2 — extract a `_run_post_verify_for_surface` skeleton from the per-surface wiring in `src/review_phase.py`) materially changes the wiring shape, supersede.
- If the runtime gains literal shared-session subagent semantics (Claude Code roadmap), revisit the artifact-based sharing decision and supersede if the literal shape becomes preferable.

## Source-file citations

- `src/review_advisor.py` — schemas, env helpers, advisor classes, `_SURFACE_DEFAULTS`, telemetry.
- `src/review_phase.py` — wiring across 5 surfaces, retry loop, runner adapter, self-modification guard.
- `src/reviewer.py` — executor prompt threading (pre-flight plan injection).
- `src/mockworld/fakes/fake_llm.py` — `_FakeAdvisorRunner` for scenario testing.
- `.claude/agents/hydraflow-review-advisor.md` — Opus subagent definition.
- `tests/test_review_advisor.py` — unit tests (~100+ across 5 surfaces).
- `tests/test_review_phase_core.py` — surface integration tests, including `TestSelfModificationGuard`.
- `tests/scenarios/test_pr_review_advisor_*.py` — Tier-1 MockWorld scenarios (11 cases).
