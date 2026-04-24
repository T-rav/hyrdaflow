# ADR-0041: GitHub as Source of Truth, Local Cache as Sidecar

**Status:** Accepted
**Enforced by:** tests/test_issue_cache.py, tests/test_precondition_gate.py
**Date:** 2026-04-08

## Context

The Swamp lifecycle work (#6421, #6422, #6423, #6424) introduces a structured local JSONL cache that mirrors HydraFlow's derived state — versioned plans, adversarial review findings, classifications with routing outcomes, bug reproduction records, and route-back audit trails. The Swamp project's original design pattern proposes inverting the source-of-truth relationship: the local datastore becomes authoritative and GitHub is "just a reflection for humans to read."

HydraFlow does **not** invert the relationship. GitHub remains the primary source of truth and the cache is a structured sidecar that supplements GitHub with information GitHub cannot represent natively. This ADR documents the rationale so future agents do not "fix" the design by collapsing the cache into a primary store.

### Related

- `src/issue_cache.py:IssueCache` — append-only JSONL store for derived records
- `src/caching_issue_store.py:CachingIssueStore` — read-through decorator wrapping `IssueStorePort`
- `src/issue_store.py:IssueStore` — GitHub-backed in-memory queue, still authoritative for stage routing
- `src/precondition_gate.py:PreconditionGate` — gates label transitions on cache records, never reverses GitHub
- `src/route_back.py:RouteBackCoordinator` — writes both label swap (GitHub) and audit record (cache)
- ADR-0002 (`docs/adr/0002-labels-as-state-machine.md`) — labels remain the authoritative state machine signal
- The Swamp lifecycle post — the contrasting pattern this ADR explicitly does not adopt

## Decision

**GitHub is the primary source of truth for issue state.** The local JSONL cache is an opt-in structured sidecar that stores HydraFlow's derived records and gates label transitions on them, but never replaces GitHub as the system of record.

### Authority split

| Concern | Authoritative store |
|---|---|
| Issue body, title, comments | GitHub |
| Pipeline stage (`hydraflow-plan`, `hydraflow-ready`, …) | GitHub labels |
| PR state, review submission, merge | GitHub |
| Versioned plan history (v1 → v2 → v3) | Local cache |
| Adversarial review findings (severity-tagged) | Local cache |
| Triage classification with routing outcome | Local cache |
| Bug reproduction outcome + test path | Local cache |
| Route-back counter and audit trail | Local cache + StateTracker |
| Anything humans interact with directly | GitHub |

### Operational invariants

1. **Labels still drive pickup.** Every phase reads `IssueStore.get_*` which polls GitHub via the in-memory queue routed by label. The cache never replaces this — it gates *whether* an issue picked up by the label state machine should actually be processed.

2. **The precondition gate is opt-in.** `HYDRAFLOW_PRECONDITION_GATE_ENABLED` defaults to `False`. Without the gate, HydraFlow runs exactly as it did before the cache work. With the gate, the cache becomes an additional check on top of the existing label-driven pickup, never a replacement.

3. **Route-back writes go to GitHub first.** `RouteBackCoordinator.route_back()` swaps the GitHub label and writes the cache audit record in the same operation. The label swap is what the next polling cycle reads — the cache record is for human audit and feedback context.

4. **The cache file is per-machine.** Cache contents are not synced across machines or processes. A fresh checkout on a new machine joins the pipeline immediately by reading GitHub labels; the cache rebuilds locally as the orchestrator runs.

### Why not invert the model

The Swamp pattern (datastore primary, GitHub projection) requires:

- A network-accessible datastore so multiple machines see the same state
- A reliable write path that updates the datastore before the GitHub label
- A migration story for existing in-flight issues
- A new dashboard read path that queries the datastore instead of GitHub
- A failure mode for "datastore down" that doesn't strand the pipeline

HydraFlow's deployment model (single orchestrator per repo, occasional machine swaps, no central infrastructure) doesn't justify any of that. The GitHub-first design means:

- **Multi-machine portability**: clone the repo on any machine with `gh` auth, run `make run`, the orchestrator immediately rejoins the pipeline by reading labels. No state migration, no datastore sync.
- **Graceful degradation**: a corrupted or missing cache file disables the gate (because no records exist) but does not break label-driven pickup. The pipeline keeps working in legacy mode.
- **Clean onboarding**: operators inspect issue state via the GitHub UI, not a separate dashboard. Labels are the lingua franca.
- **No new infrastructure**: the cache is a directory of JSONL files. No database, no service, no operational overhead.

### What the cache is for

The cache exists to make HydraFlow's *derived* state structured and queryable. GitHub stores the issue and the label; HydraFlow needs to know:

- Did this plan pass adversarial review? (severity-tagged findings)
- Is this bug actually reproducible? (test path + confidence)
- How many times has this issue been routed back? (counter for HITL escalation)
- Was this issue classified as a bug *and* actually routed to plan? (vs parked or sent to discover)

These are HydraFlow's own records, not GitHub state. Storing them as free-text comments and re-parsing them on every cycle is fragile (`_parse_gap_review` regex was the original motivating example). Storing them as structured JSONL records gives the precondition gate a reliable basis for decisions.

## Consequences

### Positive

- **Multi-machine portability**: any machine with `gh` auth can run the orchestrator. Cache is local cold-start state, not a sync requirement.
- **Backward compatibility**: gate defaults to off; existing label-driven workflows are unchanged.
- **Graceful degradation**: cache corruption disables enforcement but does not strand the pipeline.
- **No new infrastructure**: just a directory of JSONL files.
- **Structured derived state**: review findings, plan versions, route-back counters, and reproduction outcomes are all queryable by future tooling without re-parsing comments.
- **Clear authority**: every concern has one authoritative store; no ambiguous dual-write semantics.

### Negative

- **Cache is not shared across machines**: a route-back counter on machine A is invisible to machine B. In practice this doesn't matter because the orchestrator runs on one machine at a time per repo, but it would prevent multi-orchestrator deployments without additional work.
- **Two stores to reason about**: contributors need to know which store owns which concern. This ADR is the canonical reference.
- **Cache writes can race** with label swaps under transient `gh` failures (mitigated by `RouteBackCoordinator` rollback semantics in `_route_back.py`).

### Risks

- **Future contributor inverts the model**: someone could "improve" the design by collapsing label state into the cache. This ADR is the brake — any change that makes the cache authoritative for stage routing must supersede this ADR with a new one explaining the migration story for the operational invariants above.
- **Cache file grows unbounded**: append-only JSONL has no compaction. Mitigated by issue-scoped files (one per issue) and the index being a perf optimization. A long-term issue with thousands of plan iterations would need a separate compaction strategy; not in scope for the current cache work.

## Alternatives considered

### Full Swamp model (cache primary, GitHub projection)

Considered and rejected for the reasons above. The deployment model and operational invariants don't justify the complexity. If a future deployment scenario (multi-orchestrator, central operations) changes the calculus, supersede this ADR.

### Skip the cache entirely, store everything in GitHub comments

This was the pre-#6422 state. Rejected because regex-scraping comments is fragile and unstructured: a comment-format change breaks every consumer, version history is lost when comments are edited, and adversarial-review findings have no schema to enforce.

### Sync cache across machines via a separate service

Considered as a follow-up if multi-orchestrator deployments become a real need. Currently out of scope — no operational pressure exists, and adding it would compromise the "any machine with `gh` auth can join" property that makes the current design portable.
