# ADR-0047: Fake-adapter contract testing via cassette record/replay

- **Status:** Proposed
- **Date:** 2026-04-23
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0045](0045-trust-architecture-hardening.md) §4.2 initiated this work; [ADR-0022](0022-integration-test-architecture-cross-phase-pipeline-harness.md) (integration test harness) — this ADR extends it with contract testing of fakes.
- **Enforced by:** `make trust-contracts`; `tests/trust/contracts/test_fake_*_contract.py`; `src/contract_refresh_loop.py` (the weekly refresh loop that keeps cassettes in sync with reality).

## Context

HydraFlow's scenario test harness (`MockWorld`, ADR-0022) uses fake adapters — `FakeGitHub`, `FakeGit`, `FakeDocker`, `FakeLLM` — to replace real external services during tests. The problem: a fake that silently diverges from the real service is worse than no fake, because green tests hide broken code. Historically this manifested as "tests pass, but the first production call blows up on a field the fake didn't return" or "the fake's stdout shape was never what `gh` actually prints." As the number of fakes grew, the divergence risk compounded.

We needed a way to:
1. **Prove** the fakes match the real services' observable behavior for the call shapes the code actually uses.
2. **Detect drift** automatically — if `gh` changes its output format, we must hear about it before production does.
3. **Be cheap to maintain** — the cassette corpus should update itself, not require a human to re-record every time an API changes.

## Decision

Adopt a **record/replay cassette pattern** with three parts:

### Part 1 — Cassette schema
Each cassette is a YAML file (or JSONL for streaming APIs) stored under `tests/trust/contracts/cassettes/<adapter>/<scenario>.yaml` with a strict pydantic model (`tests/trust/contracts/_schema.py::Cassette`). The schema includes:
- `adapter` name (gated to the 4 known values).
- `input` (command + args + stdin).
- `output` (stdout + stderr + exit code).
- `normalizers` (list of declarative field-normalizer names — e.g. `pr_number`, `timestamps.ISO8601`, `sha:short`) that strip volatile fields before compare.
- `recorded_at` / `recorder_sha` for forensic tracing.

### Part 2 — Per-adapter contract tests
One `test_fake_<adapter>_contract.py` per fake. Each loads committed cassettes and replays them against the fake via `replay_cassette` (`tests/trust/contracts/_replay.py`). Drift assertion: the normalized `got` output must equal the normalized `expected` output, byte-for-byte. Claude streams bypass the YAML schema and compare as normalized JSONL via `_normalize_claude_stream` in `src/contract_diff.py`.

### Part 3 — Automated refresh (ContractRefreshLoop)
Weekly, `ContractRefreshLoop` (spec §4.2) re-records the corpus against the real services using recorders in `src/contract_recording.py`, normalizes via the declared normalizers, diffs against committed cassettes (`src/contract_diff.py`), and opens a refresh PR if drift is detected. After the PR opens, the loop re-runs `make trust-contracts` locally (the replay gate) — if it still fails with the new bytes, a `fake-drift` companion issue is filed for a human to triage because it means the fake's code (not just the cassette) needs updating.

## Consequences

**Positive:**
- Fakes now have a machine-checkable contract. A commit that changes `FakeGitHub.create_pr`'s output shape breaks `test_fake_github_contract.py` until the cassette is re-recorded to match (which is the right signal — "you changed the fake, prove the contract still holds").
- Drift in the real API surfaces in a refresh PR, not in a production incident. A CI reviewer sees "contract-refresh: 2026-04-30 (github)" and auto-merges or triages.
- New fake adapters follow the pattern mechanically: add a recorder to `contract_recording.py`, add cassettes, add a `test_fake_<name>_contract.py`, done.

**Negative:**
- Cassette maintenance is a real cost. Every schema change to the fake requires re-recording. Mitigated by the automated refresh loop (weekly) and by the normalizer registry (volatile fields filtered automatically).
- Live recording requires credentials (`gh` auth, Docker daemon, Claude CLI). The refresh loop gracefully no-ops on missing credentials — a tolerated partial state.
- The 3-attempt escalation tracker in `ContractRefreshLoop` means a persistently-drifting adapter can take up to 3 weekly cycles to escalate to HITL. Acceptable tradeoff — most drift resolves in one refresh cycle.

**Neutral:**
- Cassette YAMLs live in the repo and therefore participate in git diff / history. Large cassettes could bloat the repo. Mitigated by keeping cassettes small (one call per cassette) and preferring JSONL for streaming.

## When to add a new cassette

- A new call shape is added to a fake. The fake code must be backed by a cassette proving the new shape matches the real API.
- An adapter's cassette directory is empty but the fake is wired into production code paths. Fix by recording a baseline cassette even if the corpus is small.

## When to replace this pattern

If a service becomes so dynamic (e.g. non-idempotent responses, per-request IDs that can't be normalized) that cassettes can't faithfully capture it, the fake is no longer a valid test double. Options:
- Move the service to a live-only test lane (e.g. nightly against a sandbox).
- Narrow the fake's surface to deterministic operations and document the rest as untested.
- Supersede this ADR with a different testing strategy (property-based? contract-by-protobuf?).

## Related

- Cassette normalizers registry: `tests/trust/contracts/_schema.py::NORMALIZERS`
- Recorders (capture real-service output): `src/contract_recording.py`
- Diff/drift detection: `src/contract_diff.py`
- Refresh loop: `src/contract_refresh_loop.py`
- Fleet scenario: `tests/scenarios/test_contract_refresh_scenario.py`
