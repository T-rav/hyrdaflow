# ADR-0052: Sandbox-tier scenario testing

- **Status:** Accepted
- **Date:** 2026-04-28
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md), [ADR-0042](0042-staging-promotion-loop.md), [ADR-0049](0049-trust-loop-kill-switch-convention.md), [ADR-0050](0050-auto-agent-hitl-preflight.md), [ADR-0051](0051-iterative-production-readiness-review.md)
- **Enforced by:** `tests/test_mockworld_fakes_conformance.py` (Port↔Fake signature parity), `.github/workflows/ci.yml` `sandbox` job (CI gate).

## Context

The dark-factory infrastructure-hardening track (#8445/#8446/#8448) closed the structural-enforcement gap at the unit and per-loop level. What it did not close is the end-to-end gap: there was no test that booted HydraFlow as a deployed system and verified "issue → label-state-machine progression → PR merged" without a human watching.

That gap was closed by the human in the loop. Removing the human means moving that verification into automation.

## Decision

Two test tiers backed by the same MockWorld substrate (`src/mockworld/fakes/`):

- **Tier 1 (in-process, every PR):** existing `tests/scenarios/` suite. ~30 scenarios, ~0.1s each.
- **Tier 2 (sandbox, PR B/C):** new `tests/sandbox_scenarios/` suite. ~12 curated scenarios that boot HydraFlow inside `docker-compose.sandbox.yml`, swap MockWorld at the boundary, drive the UI via Playwright, assert end-to-end. ~30–60s each.

**MockWorld is always-on infrastructure**, not a configurable mode. Selection between Fake and real adapters happens at the **entrypoint level**: production runs the `hydraflow` console script (`server:main`); sandbox runs `python -m mockworld.sandbox_main`. `build_services()` and `HydraFlowOrchestrator.__init__` accept optional adapter overrides; production never passes them.

**Air-gap is structural** (compose `internal: true`), not honor-system. Containers have no default gateway; external hosts cannot be routed to.

## Rules

1. **No config switch for MockWorld.** No `HYDRAFLOW_MOCKWORLD_ENABLED` env var, no boolean field on `HydraFlowConfig`. The choice is at the entrypoint level, period.
2. **Fakes ship in `src/mockworld/fakes/`,** treated as production code (ruff, pyright, bandit). They are not test fixtures — they are alternative adapters.
3. **Every sandbox scenario has a Tier-1 parity test** (`tests/scenarios/test_sandbox_parity.py`). If only Tier 2 fails, the bug is in container/wiring/UI; if both fail, it's in scenario logic. Triage starts with Tier 1.
4. **The dashboard renders a persistent MOCKWORLD MODE banner** when the injected `PRPort` carries the `_is_fake_adapter` marker. Duck-typed; not config-driven.
5. **CI gate (PR C):** all 12 sandbox scenarios must pass on the rc/* promotion PR before staging→main merge. Failures auto-dispatch the auto-agent self-fix loop (`SandboxFailureFixerLoop`).

## Sandbox carve-outs (preserving the air-gap)

The air-gap surfaces sites where production code has implicit network dependencies that hang under `internal: true`:

- `src/contract_recording.py` synchronously invokes `claude -p ping` at startup, hanging on api.anthropic.com. Sandbox carve-out: the `mockworld.sandbox_main` entrypoint disables `contract_refresh` via `is_enabled` in its WorkerRegistryCallbacks.
- `src/ui/src/context/HydraFlowContext.jsx` calls `crypto.randomUUID()` which is undefined in non-secure contexts (HTTP). Fallback: a deterministic `_fallbackUuidV4` based on `crypto.getRandomValues`.

Both are real production-relevant findings the sandbox tier surfaced — exactly the bug class Tier 2 is designed to catch. ADR-0052 ratifies the carve-out pattern: when a production code path can't run on the air-gapped network, EITHER short-circuit it via a sandbox-only path in `mockworld.sandbox_main`, OR fix the production code to handle the air-gapped case (preferred when the fix is cheap, e.g., `randomUUID` fallback).

## Consequences

**Positive:**
- End-to-end "did this build actually work?" verification runs without a human.
- Container-only bugs (Dockerfile drops, network policy, UI routing) caught at PR time instead of in production.
- Production releases leave staging with high confidence; observability catches what no test could anticipate.
- Cross-tier alignment via shared Fake substrate eliminates "in-process passes, container fails" surprises.

**Negative:**
- Sandbox tier adds ~30–60s per scenario. ~12 scenarios = ~10 min full-suite run.
- New caretaker loop (`SandboxFailureFixerLoop`, lands in PR C) adds ~400 LOC of code to maintain.
- Dockerfile.agent must `COPY` `tests/` until `src/contract_diff.py:54` is refactored away from importing `tests.trust.contracts._schema`.

**Risks:**
- Sandbox flakes erode trust if not investigated. Mitigation: 3-strikes-then-bug pattern from PR C's Trigger 3 (nightly).
- Self-fix loop oscillation. Mitigation: 3-attempt cap then HITL escalation.

## When to supersede this ADR

- If a future revision adopts a config-flag-based MockWorld selection (the design rejected here), supersede with rationale.
- If empirical convergence shifts (e.g., sandbox scenarios routinely catch zero bugs over many quarters), reduce the planning expectation.

## Source-file citations

- `docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md` — full spec (converged through 4 fresh-eyes review iterations per ADR-0051).
- `src/mockworld/sandbox_main.py` — the sandbox entrypoint.
- `src/mockworld/fakes/` — the always-loaded Fake adapter set.
- `docker-compose.sandbox.yml` — the air-gapped sandbox stack.
- `tests/sandbox_scenarios/` — the Tier-2 scenarios (s01 in PR B; s02–s12 in PR C).
- `.github/workflows/ci.yml` `sandbox` job — the CI gate.
