# ADR-0055: OpenTelemetry Instrumentation as the Telemetry Layer

## Status

Accepted

## Date

2026-05-06

## Enforced by

`tests/architecture/test_otel_invariants.py`, `tests/regressions/test_otel_disabled_is_noop.py`, `tests/scenarios/test_telemetry_e2e.py`

## Context

Before this ADR, HydraFlow had Sentry for exception capture and a JSONL-based `trace_collector` for subprocess transcripts, but no distributed tracing. This blocked evidence-driven investigation across phase boundaries — "why was issue #1234 slow?" was un-answerable in a single view because work happens across loop ticks, runner subprocess calls, and port boundaries that have no shared causal context.

The dark-factory premise (CLAUDE.md, [`docs/wiki/dark-factory.md`](../wiki/dark-factory.md)) requires the system to detect its own ops issues and file them as `hydraflow-find` GitHub issues for the factory to fix. That detection must be data-driven (anomaly detection, BubbleUp-style attribution, latency outlier flagging) — but you cannot detect what you cannot query, and you cannot query what you cannot ingest. This ADR establishes the ingest layer.

This ADR governs **Phase A** of a two-phase rollout. Phase B (anomaly → issue pipeline, the SentryLoop analogue) is deferred to a separate spec, designed from real trace data once Phase A has been running.

## Decision

HydraFlow uses **OpenTelemetry (OTLP/HTTP) → Honeycomb** as its distributed-tracing backbone, with four load-bearing rules:

1. **OTel is a layer, not a refactor.** Decorators (`@runner_span()`, `@loop_span()`, `@port_span(name)`) wrap existing methods. No public signature changes. Behavior is byte-identical when `config.otel_enabled=False`.

2. **Feature-gated at boot.** `init_otel(config)` is called once from `server.py:main()` after `_init_sentry`. The flag is read once; there are no per-request "is OTel on?" branches. When disabled, the global tracer is OTel's no-op tracer.

3. **All `hf.*` attributes flow through `add_hf_context()`.** Single source of truth for attribute names — Phase B's anomaly queries and any future Honeycomb dashboard depend on attribute names being stable. Architecture invariant `test_hf_attrs_only_set_via_helper` enforces this.

4. **Telemetry never alters business control flow.** Every span operation goes through a `_safe_*` helper that catches its own exceptions and logs without re-raising. Business exceptions are always re-raised. Regression-tested: `test_otel_disabled_is_noop.py` (with no provider registered) and `test_runner_span_swallows_telemetry_exception` (with the SDK's `Span.set_attribute` monkeypatched to raise).

### Trace boundaries

A trace = one unit of issue work (per-phase invocation), not per-HTTP-request and not per-`SessionLog`. Mega-traces spanning the whole issue lifecycle break Honeycomb's UI; per-phase trace roots with consistent `hf.issue` attributes let you reconstruct the lifecycle via grouping.

| Trace root | Where | Required attributes |
|---|---|---|
| `hf.runner.{phase}` | `BaseRunner._execute` | `hf.issue`, `hf.phase`, `hf.session_id`, `hf.repo`, `hf.runner`, `hf.model`, `hf.attempt` |
| `hf.loop.{name}` | `BaseBackgroundLoop._execute_cycle` | `hf.loop`, `hf.tick`, `hf.interval_s`, `hf.success` |
| auto FastAPI | HTTP handlers | OTel semantic conventions |

### Subprocess Claude calls

`stream_claude_process()` subprocesses get a single span (`hf.subprocess.claude`) on the runner side. Tool-call milestones from `trace_collector`'s parsed events become span events on that span — not child spans. No traceparent injection into the inner `claude -p` binary; the cost-per-tool-call breakdown is preserved as `claude.tool` span events with `claude.duration_ms` attributes.

### Cardinality budget

Allow-list enforced by `validate_attr()` (rejects unknown high-cardinality keys). Bounded namespaces: `hf.phase`, `hf.runner`, `hf.loop`, `git.subcommand`, `exception.slug`. High-cardinality-but-useful: `hf.issue`, `hf.session_id`, `gh.pr_number`, `trace.id`. Banned: full diffs, full prompts, anything resembling PII.

### Exception classification

`reraise_on_credit_or_bug()` tags the active span with `error=true` and a static `exception.slug` (looked up via `slug_for(exc)`) before re-raising. Slugs are low-cardinality, greppable identifiers seeded from known categories (`err-credit-exhausted`, `err-subprocess-timeout`, `err-permission-denied`, etc.) and grow from production data in Phase B.

### Sentry coexistence

Sentry stays as-is during Phase A. The decision to retire / consolidate / unify is **deferred to Phase B**, made from data once Phase B's `HoneycombLoop` has been running for ≥30 days. Three paths exist (keep both, retire Sentry, retire SentryLoop); choosing prematurely defeats the data-driven framing.

## Consequences

**Gained:**
- Per-phase trace waterfalls in Honeycomb (`hf.runner.{phase}` roots with port + subprocess children).
- Cross-phase causal grouping via `hf.issue`, `hf.session_id`.
- BubbleUp-ready dimensionality on every span (the `hf.*` attribute set is curated for this).
- Architecture invariant catches drift if anyone removes a decorator, sets `hf.*` directly, or introduces a bare `asyncio.create_task` in an instrumented file.

**Cost paid:**
- New always-installed deps: 5 OTel packages (api, sdk, exporter-otlp-proto-http, instrumentation-fastapi/httpx/asyncio/logging). When `otel_enabled=False`, they load lazily and incur no runtime cost beyond import-time.
- One additional environment variable (`HONEYCOMB_API_KEY`) and one feature flag (`HYDRAFLOW_OTEL_ENABLED`) operators must set. `.env.sample` documents both.
- Honeycomb event volume estimate: ~1.8M/month at current scale (well under the 20M-events-per-month free tier). If volume grows past 10M/month, add Refinery tail sampling — explicitly out of Phase A scope.

**Out of scope (deferred):**
- Phase B: `HoneycombLoop` (anomaly → `hydraflow-find` GitHub issue pipeline).
- Refinery tail sampling.
- Cross-subprocess W3C traceparent injection into `claude -p`.
- Retiring Sentry — decision deferred to Phase B with 30 days of trace data.
- Honeycomb meta-health board (currently the meta-failures from §7 of the spec route through Sentry).

## Touchpoints with other ADRs

- **ADR-0001 (Five Concurrent Async Loops)** — phase runners are now decorated trace roots; loop ticks are decorated trace roots. No semantic change to the loop architecture itself.
- **ADR-0029 (Caretaker Loop Pattern)** — the future `HoneycombLoop` (Phase B) will be a caretaker loop following this pattern; not introduced here.
- **ADR-0044 (Workflow Skills)** — Phase A used the standard brainstorming → writing-plans → subagent-driven-development → requesting-code-review flow.
- **ADR-0051 (Iterative Production-Readiness Review)** — full-ceremony reviewer subagents caught 8 real issues during Phase A implementation (see PR #8473 description).

## Source-file citations

The following files carry this ADR's decisions and must be kept in sync with any supersession:

- `src/telemetry/__init__.py` — package marker; re-exports `init_otel`, `shutdown_otel`, `slug_for`.
- `src/telemetry/otel.py` — `init_otel(config)` feature-gated SDK bootstrap, `shutdown_otel()` flush, OTLP/HTTP exporter to Honeycomb, auto-instrumentation registration (FastAPI, httpx, asyncio, logging).
- `src/telemetry/spans.py` — `runner_span`, `loop_span`, `port_span` decorators; `add_hf_context()` helper (single source of truth for `hf.*` attributes); `validate_attr()` cardinality guard; `_safe_*` exception-isolating helpers; `_get_tracer()` lru_cache for Tracer-per-scope.
- `src/telemetry/slugs.py` — `EXCEPTION_SLUGS` mapping + `slug_for(exc)` lookup; unknown → `err-unclassified`.
- `src/telemetry/subprocess_bridge.py` — `bridge_event_to_span()` adapts `trace_collector` parsed events to OTel span events.
- `src/config.py` — `otel_enabled`, `otel_endpoint`, `otel_service_name`, `otel_environment` fields + env overrides (`HYDRAFLOW_OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `HF_ENV`).
- `src/server.py` — `init_otel(config)` call after `_init_sentry()` in `main()`.
- `src/base_runner.py` — `BaseRunner._execute` decorated with `@runner_span()`; `phase` property bridges `_phase_name` ClassVar.
- `src/base_background_loop.py` — `BaseBackgroundLoop._execute_cycle` decorated with `@loop_span()`; `name` property bridges `_worker_name`.
- `src/pr_manager.py` — `PRManager.create_pr/merge_pr/create_issue/push_branch` decorated with `@port_span(...)`.
- `src/workspace.py` — `WorkspaceManager.create/merge_main` decorated with `@port_span(...)`.
- `src/exception_classify.py` — `reraise_on_credit_or_bug()` tags active span with `error=true` + `exception.slug` before re-raise (best-effort; never alters classify behavior).
- `src/events.py` — `EventBus.publish` calls `span.add_event("hf.event", ...)` on active span (best-effort).
- `src/trace_collector.py` — `_record_inner` calls `bridge_event_to_span` on every parsed subprocess event (lazy imports to avoid circular dependency).
- `src/mockworld/fakes/fake_honeycomb.py` — `FakeHoneycomb` test fake wrapping `InMemorySpanExporter`; mirrors the `FakeSentry`/`FakeGitHub` convention.
- `tests/scenarios/fakes/mock_world.py` — `MockWorld.honeycomb` property exposes the fake.
- `tests/conftest.py` — `_reset_otel_tracer_provider` autouse fixture clears `_TRACER_PROVIDER` + `_get_tracer.cache_clear()` between tests.
- `.env.sample` — OpenTelemetry / Honeycomb block documents the four operator-settable knobs.
- `pyproject.toml` — 7 OpenTelemetry packages added to `[project.dependencies]`.
- `docs/superpowers/specs/2026-05-02-otel-honeycomb-phase-a-design.md` — full design spec.
- `docs/superpowers/plans/2026-05-02-otel-honeycomb-phase-a.md` — TDD implementation plan.
- `tests/architecture/test_otel_invariants.py` — enforces decorator placement, `hf.*` helper-only attribute setting, no bare `asyncio.create_task` in instrumented files, parallel-unit-test rule for new fakes.
- `tests/regressions/test_otel_disabled_is_noop.py` — locks in byte-identical behavior with no provider.
- `tests/scenarios/test_telemetry_e2e.py` — end-to-end span shape verification using `MockWorld` + `FakeHoneycomb`.
- `tests/test_telemetry_*.py` — unit tests for slugs, spans, otel-init, subprocess-bridge.
