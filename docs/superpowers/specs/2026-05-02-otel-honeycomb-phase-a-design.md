# OTel Honeycomb Instrumentation — Phase A Design

**Date:** 2026-05-02
**Status:** Draft (pre-plan)
**Scope:** Phase A only — instrumentation + verification. Phase B (anomaly → issue pipeline) is a separate spec, designed from the trace data Phase A produces.
**Related:** Sentry pattern in `src/server.py:_init_sentry()` and `src/sentry_loop.py` (template for Phase B).

## 1. Problem & Goal

HydraFlow has Sentry for exception capture and a JSONL-based `trace_collector` for subprocess transcripts, but no distributed tracing. This blocks evidence-driven investigation across phases, makes "why was issue #1234 slow?" un-answerable in a single view, and prevents Phase B from existing at all (you cannot detect "critical ops issues" you cannot query).

**Phase A goal:** wire OpenTelemetry into HydraFlow such that every phase invocation, every background-loop tick, and every external-I/O call (PR, git, HTTP) emits a span to Honeycomb, with consistent `hf.*` business attributes that downstream queries and Phase B will rely on.

**Non-goals for Phase A:**
- Phase B's anomaly-detection / issue-creation loop (separate spec).
- Retiring Sentry (revisit at start of Phase B from data).
- Tail sampling / Refinery (premature given current volume).
- Cross-subprocess W3C traceparent propagation into the inner Claude CLI.

## 2. Architectural Rules

Three rules govern every implementation choice in this spec; they exist so that telemetry stays a passive layer rather than a refactor:

1. **OTel is a layer, not a refactor.** Decorators wrap existing methods. No public signature changes. When `otel_enabled=False`, behavior is byte-identical to today.
2. **Feature gate is binary at startup.** `config.otel_enabled` is read once in `main()`; there are no per-request "is OTel on?" branches. When disabled, the global tracer is OTel's no-op tracer.
3. **All `hf.*` attributes flow through one helper** (`spans.add_hf_context(span, ...)`). This is the ubiquitous-language rule (CLAUDE.md / ADR-0044 P2.9) applied to telemetry — Phase B and any future Honeycomb query depends on attribute names being stable.

## 3. Trace Boundaries

A trace = "one unit of issue work" (Q2 decision: option B).

| Trace root | Where | Required attributes |
|---|---|---|
| `hf.runner.{phase}` | `BaseRunner._execute()` | `hf.issue`, `hf.phase`, `hf.session_id`, `hf.repo`, `hf.runner`, `hf.model`, `hf.attempt` |
| `hf.loop.{name}` | `BaseBackgroundLoop._do_work()` | `hf.loop`, `hf.tick`, `hf.interval_s`, `hf.success` |
| FastAPI auto root | HTTP handlers | OTel semantic conventions + `hf.session_id` if present in headers |

Phase trace roots are siblings of each other across the issue lifecycle (not nested). To see "everything that happened to issue #1234," group by `hf.issue` across traces; do not collapse phases into one mega-trace (Q2 option C, rejected — breaks Honeycomb's waterfall UI).

## 4. Components

### 4.1 New module: `src/telemetry/`

| File | Responsibility |
|---|---|
| `otel.py` | `init_otel(config)` (feature-gated, lazy SDK imports), `shutdown_otel()` (atexit hook, flushes ≤5s), credential redaction parallel to Sentry's `_scrub` |
| `spans.py` | Decorators (`@runner_span`, `@loop_span`, `@port_span`), `add_hf_context()` helper, attribute allow-list with `validate_attr()` |
| `slugs.py` | Exception → `exception.slug` mapping, seeded from `exception_classify.py`. Unknown exceptions → `err-unclassified`. |
| `subprocess_bridge.py` | Adapter from `trace_collector` parsed events → `span.add_event("claude.tool", {tool, duration_ms, ...})` on the active subprocess span |

### 4.2 Touched modules

| File | Change |
|---|---|
| `src/server.py` | Call `init_otel(config)` after `_init_sentry`, register `atexit(shutdown_otel)` |
| `src/config.py` | New fields: `otel_enabled` (bool), `otel_endpoint` (str), `otel_service_name` (str), `otel_environment` (str). Env overrides per existing `_ENV_*_OVERRIDES` tables. |
| `src/base_runner.py` | Decorate `_execute` with `@runner_span()`; span name resolved at call time as `f"hf.runner.{self.phase}"` (the runner instance carries its phase). Thread `hf.*` attributes via `add_hf_context` |
| `src/base_background_loop.py` | Decorate `_do_work` with `@loop_span()`; span name resolved at call time as `f"hf.loop.{self.name}"` (each loop instance has a stable `name`) |
| `src/pr_manager.py` | Decorate `create_pr`, `merge_pr`, `create_issue`, `push_branch` with `@port_span("hf.port.pr.{method}")` |
| `src/workspace.py` | Decorate `run_git` with `@port_span("hf.port.workspace.git")` |
| `src/exception_classify.py` | `reraise_on_credit_or_bug` sets `exception.slug` + `error=true` on the active span before re-raise |
| `src/events.py` | `EventBus.publish()` calls `span.add_event("hf.event", {hf.event.type: ...})` on active span (no new spans) |
| `src/trace_collector.py` | Existing JSONL output unchanged; emit parallel span events via `subprocess_bridge` |

### 4.3 Auto-instrumentation registered

`opentelemetry-instrumentation-fastapi`, `-httpx`, `-requests`, `-asyncio`, `-logging`. These provide the skeleton for free. No code changes beyond calling `XInstrumentor().instrument()` in `init_otel`.

### 4.4 Cardinality budget

| Bounded attrs | `hf.phase` (4) · `hf.runner` (~8) · `hf.loop` (~30) · `git.subcommand` (~10) · `exception.slug` (~20) · `gh.dry_run` (2) |
| Useful-high-cardinality | `hf.issue`, `hf.session_id`, `gh.pr_number`, `trace.id` |
| **Banned** (rejected by `validate_attr()`) | full git diffs, full LLM prompts/responses, file paths beyond repo-relative, anything matching PII heuristics |

## 5. Data Flow

```
ImplementPhase processes issue #1234
  └─ runner.run(...)
       └─ @runner_span → trace root: hf.runner.implement
            attrs: hf.issue=1234, hf.phase=implement, hf.session_id=…
            ├─ EventBus.publish(PHASE_CHANGE)            → span.add_event("hf.event")
            ├─ workspace.run_git("checkout", …)          → child: hf.port.workspace.git
            ├─ stream_claude_process()                   → child: hf.subprocess.claude
            │     └─ trace_collector parsed events       → span.add_event("claude.tool") per turn
            │     on subprocess exit: subprocess.exit_code, .tokens_in/out, .cost_usd, .duration_ms
            ├─ pr_manager.create_pr(…)                   → child: hf.port.pr.create_pr
            └─ on exit:
                 ✓ success: hf.success=true, span.status=OK
                 ✗ exception: reraise_on_credit_or_bug(exc)
                                 → exception.slug=…, error=true, span.status=ERROR
                                   span.record_exception(exc)
       BatchSpanProcessor flushes every 5s or 512 spans → OTLP/HTTP → Honeycomb
```

Background loops emit a parallel trace per `_do_work()` tick. They never share a parent with phase runners.

### 5.1 Subprocess Claude calls (Q3 decision: option B)

The `claude -p` subprocess gets a single span (`hf.subprocess.claude`) on the runner side. Tool-call milestones from `trace_collector`'s parsed events become span events on that span — not child spans. Existing JSONL output is preserved untouched (different concern: subprocess transcript persistence). No traceparent injection into the subprocess.

## 6. Configuration

Four new fields on `HydraFlowConfig`:

| Field | Env var | Default | Notes |
|---|---|---|---|
| `otel_enabled` | `HYDRAFLOW_OTEL_ENABLED` | `False` | Master switch |
| `otel_endpoint` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `https://api.honeycomb.io` | Standard OTel env var; SDK appends `/v1/traces`. EU users override to `https://api.eu1.honeycomb.io` |
| `otel_service_name` | `OTEL_SERVICE_NAME` | `hydraflow` | Standard OTel env var preserved |
| `otel_environment` | `HF_ENV` (existing) | `local` | Mapped to `deployment.environment` resource attribute |

Honeycomb ingest key is **not** a config field. It's a credential read from `HONEYCOMB_API_KEY` env var (gitignored `.env`). Treated like `SENTRY_DSN`.

Single Honeycomb dataset across environments; filter by `deployment.environment` (Q5c decision).

## 7. Failure Modes

Telemetry must never break HydraFlow. Every failure mode below has a documented "app keeps running" path.

| # | Failure | Behavior |
|---|---|---|
| 1 | `HONEYCOMB_API_KEY` missing while `otel_enabled=true` | Log WARN once, no-op tracer, continue |
| 2 | OTLP endpoint unreachable / 5xx | SDK retries with backoff; queue cap 2048; drops silently after cap |
| 3 | OTLP returns 401/403 | ERROR once, suppress further log spam, increment Sentry counter `otel.auth_failed` |
| 4 | `init_otel()` itself raises | Caught in `main()`, ERROR with traceback to Sentry, no-op tracer remains in place (OTel SDK default before any provider is registered), app continues. No extra disable flag needed — the decorator stack against a no-op tracer is already the off-state. |
| 5 | A decorator raises (telemetry bug) | `_safe_*` helpers swallow telemetry exceptions; wrapped business call always runs and re-raises business exceptions |
| 6 | Span queue full | `otel.dropped_spans` counter; WARN every 60s if non-zero |
| 7 | Async context lost across `create_task()` | Architecture-test invariant flags bare `asyncio.create_task` in instrumented modules |
| 8 | Subprocess Claude crashes | `exception.slug=err-subprocess-crashed`, status=ERROR, handled by wrapping runner span |
| 9 | Honeycomb rate-limits us | SDK respects `Retry-After`; bursts drop; `otel.rate_limited` counter ticks |
| 10 | Cardinality explosion | `validate_attr()` rejects unknown high-cardinality attrs against allow-list; logs WARN |

The decorator skeleton enforcing #5:

```python
def runner_span(name):
    def decorator(fn):
        async def wrapper(self, *a, **kw):
            span_ctx = _safe_start_span(name, self)   # never raises
            try:
                return await fn(self, *a, **kw)
            except Exception as exc:
                _safe_record_error(span_ctx, exc)     # never raises
                raise                                  # business exception always re-raised
            finally:
                _safe_end_span(span_ctx)              # never raises
        return wrapper
    return decorator
```

Visibility into these meta-failures (#6, #9) lives in Sentry during Phase A. Phase B may move them onto a Honeycomb meta-health board.

### 7.1 Volume estimate

| Source | Spans/day | Spans/month |
|---|---|---|
| Phase runners (50 issues × 4 phases × 5 spans) | 1,250 | ~38k |
| Background loops (30 loops × tick/min) | 43,200 | ~1.3M |
| FastAPI requests (~5,000 × 3) | 15,000 | ~450k |
| **Total** | ~60k/day | **~1.8M/month** |

Comfortably under Honeycomb's 20M-events-per-month free tier. No sampling needed for Phase A. If volume grows past 10M/month we add Refinery tail sampling — but on these estimates we won't.

## 8. Testing Strategy

| Layer | File | Purpose | Count |
|---|---|---|---|
| Unit (decorators) | `tests/test_telemetry_spans.py` | Wrap correctly, return values unchanged, exceptions re-raised, attrs set | ~15 |
| Unit (init/config) | `tests/test_telemetry_otel_init.py` | No-op when disabled, fails safe when key missing, env overrides | ~8 |
| Unit (slug catalog) | `tests/test_telemetry_slugs.py` | Each known exception → its slug, unknown → `err-unclassified` | ~5 |
| Unit (subprocess bridge) | `tests/test_telemetry_subprocess_bridge.py` | `trace_collector` events become span events with right shape | ~6 |
| Unit (FakeHoneycomb) | `tests/test_fake_honeycomb.py` | Capture, find, reset, shutdown | ~8 |
| MockWorld smoke | `tests/test_mockworld_honeycomb_wiring.py` | Provider installed, captured/reset works, shutdown restores no-op | ~3 |
| Integration | `tests/scenarios/test_telemetry_e2e.py` | Full phase → assert trace shape (1 root + N children, attrs, error path) | ~5 |
| Architecture | `tests/architecture/test_otel_invariants.py` | All `BaseRunner` subclasses decorated; no bare `asyncio.create_task` in instrumented files; `hf.*` only via `add_hf_context()`; new fakes have parallel unit tests | ~5 |
| Regression | `tests/regressions/test_otel_disabled_is_noop.py` | With `otel_enabled=false`, decorator stack is byte-identical to no decorators | 1 |

Two patterns specific to OTel testing:

1. **`InMemorySpanExporter` for assertions.** OTel SDK's own test exporter, installed via fixtures. No real OTLP calls in any test.
2. **Real OTLP only in dev verification.** `init_otel()` is never called in tests. Verification against `api.honeycomb.io` is manual + MCP-driven before PR merge (see §10).

### 8.1 MockWorld extension

New fake matching the existing convention (`FakeGitHub`, `FakeSentry`, `FakeClock`):

```python
# tests/scenarios/fakes/fake_honeycomb.py
class FakeHoneycomb:
    """Captures OTel spans during scenario tests. Replaces the real OTLP exporter."""

    def __init__(self): ...
    @property
    def captured_spans(self) -> list[ReadableSpan]: ...
    def find_spans(self, *, name=None, attrs=None) -> list[ReadableSpan]: ...
    def trace_for_issue(self, issue_num: int) -> list[ReadableSpan]: ...

    def assert_trace_shape(self, issue_num: int, *, expected_root: str, expected_children: list[str]): ...
    def assert_no_orphan_spans(self): ...
    def assert_attribute_present(self, span_name: str, attr_key: str): ...

    def reset(self): ...
    def shutdown(self): ...   # restores no-op tracer provider
```

`MockWorld.__init__` instantiates it; `world.honeycomb` exposes it; teardown calls `shutdown()`. Existing scenarios that don't reference `world.honeycomb` are unaffected.

## 9. Out-of-scope (Phase B and later)

- Anomaly detection / `HoneycombLoop` (the Sentry-Loop analogue).
- BubbleUp-style attribute differencing.
- Refinery tail sampling.
- Cross-subprocess traceparent injection into `claude -p`.
- Retiring Sentry. Decision deferred until Phase B has 30 days of trace data, at which point we choose between (A) keep both, (B) retire Sentry, (C) keep Sentry passively, retire `SentryLoop`.
- Honeycomb meta-health board for items §7 #6 / #9.

## 10. Verification Bar (before declaring Phase A complete)

Per `superpowers:verification-before-completion`:

1. `make quality` (CLAUDE.md required)
2. `pytest tests/test_telemetry_*` — all green
3. `pytest tests/scenarios/test_telemetry_e2e.py`
4. `pytest tests/architecture/test_otel_invariants.py`
5. Run HydraFlow locally with `HYDRAFLOW_OTEL_ENABLED=true` + real `HONEYCOMB_API_KEY`
6. Trigger one phase invocation against any test issue; wait ~10s for batch flush
7. Via Honeycomb MCP (after OAuth):
   - `get_workspace_context` — confirm `hydraflow` dataset created
   - `find_columns hf.*` — confirm `hf.issue`, `hf.phase`, `hf.session_id` present
   - `run_query: HEATMAP duration_ms WHERE service.name=hydraflow last 1h` — expect ≥1 trace root
   - `run_query: trace.id WHERE hf.issue=<that issue> last 1h` — expect 1 root + N children, no orphans
8. Capture verification queries and results in PR description.

## 11. Open Questions

None blocking implementation. Two deferred to Phase B:

- Severity thresholds for "critical ops issue" (we don't know yet — Phase B is designed from data).
- Dedup strategy across SentryLoop and the future HoneycombLoop (only matters once HoneycombLoop exists).

## 12. Decisions Log

| # | Decision | Rationale |
|---|---|---|
| Q1 | Two PRs in sequence (Phase A then B), not bundled | Phase B's "critical" thresholds need real data |
| Q2 | Trace root per phase invocation, not per request or per session | Best fit for HydraFlow's domain; mega-traces break Honeycomb UI |
| Q3 | Subprocess Claude = single span + `add_event` from `trace_collector` | ~95% of value, no traceparent fragility |
| Q4 | Spans on runners/loops/PR/git ports; events for EventBus; attrs only for IssueStore | Cardinality + readability |
| Q5a | SDK init in `src/telemetry/otel.py`, called from `server.py:main()` | Mirrors `_init_sentry` |
| Q5b | No sampling for Phase A | Volume estimate well under free tier |
| Q5c | Single dataset, env via `deployment.environment` resource attr | Standard OTel pattern |
| Q5d | Honeycomb MCP via OAuth (US region), registered | OAuth avoids second key |
| Sentry coexistence | Keep Sentry as-is for Phase A; revisit at Phase B | Defers decision until evidence exists |
