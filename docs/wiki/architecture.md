# Architecture


## Ubiquitous Language Reference

Names that load-bearing pipeline code uses. Use these literal names, not paraphrases. Each links to the topic file where the concept is treated in depth.

- **HydraFlowConfig** — central Pydantic config (50+ env-var overrides), built by `runtime_config.load_runtime_config()`. See [`architecture-state-persistence.md`](architecture-state-persistence.md).
- **StateData** — JSON-backed crash-recovery payload for the orchestrator's per-issue state. Carried by `StateTracker`. See [`architecture-state-persistence.md`](architecture-state-persistence.md).
- **SessionLog** — append-only per-issue session record (phase transitions, runner outputs). See [`architecture-state-persistence.md`](architecture-state-persistence.md).
- **WorkspacePort** — Port that abstracts the workspace lifecycle (worktree create/destroy, git ops). Adapters implement it; runners call it. See [`architecture-layers.md`](architecture-layers.md).
- **AgentRunner**, **PlannerRunner**, **ReviewRunner** — three subprocess-spawning runners that drive the implementation, planning, and review phases. Share `BaseSubprocessRunner` plumbing. See [`architecture-async-control.md`](architecture-async-control.md).
- **WorktreeManager** — owner of git-worktree lifecycle (create, mark in-use, garbage-collect). See [`architecture-async-control.md`](architecture-async-control.md).
- **RepoWikiLoop** — caretaker loop that keeps `docs/wiki/` fresh from live pipeline events ([ADR-0029](../adr/0029-caretaker-loop-pattern.md), [ADR-0032](../adr/0032-per-repo-wiki-knowledge-base.md)).
- **RepoWikiStore** — persistence layer for the repo wiki entries (JSONL + Markdown round-trip). See [`architecture-state-persistence.md`](architecture-state-persistence.md).
- **DiagramLoop** — caretaker loop that regenerates the system-topology Markdown+Mermaid every 4h ([ADR-0029](../adr/0029-caretaker-loop-pattern.md)).
- **MockWorld** — in-process fake-adapter set (FakeGitHub, FakeWorkspace, FakeLLM, FakeIssueStore, FakeIssueFetcher) used by sandbox-tier scenario tests ([ADR-0052](../adr/0052-sandbox-tier-scenarios.md)).

When CLAUDE.md adds a term to its ubiquitous-language vocabulary, it must show up here so the principles audit (P2.9) and any agent looking it up can resolve to real context.


## ADR Documentation: Format, Citations, Validation, and Superseding

ADRs use markdown with structured sections: Date, Status, Title, Context, Decision, Rationale, Consequences. Validation checklist: structural checks first (missing sections, status format), then semantic checks (scope significance, contradiction audit). Source citations use module:function format without line numbers per CLAUDE.md. Set status to Accepted for documenting existing implicit patterns, not just new proposals. Reference authoritative runtime sources (e.g., src/config.py:all_pipeline_labels) instead of copying definitions to avoid drift. Skip TYPE_CHECKING imports in citations since they're compile-time-only. Ghost entries (README listing files that don't exist) indicate stale migrations—validate documentation against filesystem reality. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts without duplicating work.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W6","title":"ADR Documentation: Format, Citations, Validation, and Superseding","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849581+00:00","updated_at":"2026-04-10T03:41:18.849582+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture Compliance and Quality Enforcement

LLM-based architecture checks (arch_compliance.py, hf.audit-architecture skill) risk blocking every PR if prompts are too aggressive. Mitigations: (1) use conservative language ('only flag clear violations'); (2) default disable-friendly config (max_attempts=1); (3) exempt composition root (service_registry.py) explicitly; (4) focus on judgment-based checks that static tools cannot detect. Deferred imports are intentional per CLAUDE.md and should never be flagged. Async read-then-write patterns (fetch state, modify, write back) are a pre-existing limitation from original _run_gh calls and acceptable as known-constraint. Tests checking presence must assert content, not just structure (e.g., verify module names in layer assignments, not just that layer labels exist). Complement with defense-in-depth enforcement via three layers: linter rules (ruff T20/T10 for debug code), AST-based validation scripts (per-function test coverage), git hooks (commit message format). Pre-commit hook runs only make lint-check (intentional gap—agent pipeline and pre-push hook cover push path). This progressive hardening pattern prevents enforcement from blocking developers while maintaining quality standards. See also: Layer Architecture for compliance targets.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W7","title":"Architecture Compliance and Quality Enforcement","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849585+00:00","updated_at":"2026-04-10T03:41:18.849586+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Workspace Isolation and Command Discovery via CWD

Claude Code discovers commands from subprocess cwd's .claude/commands/, not from invoking process. Commands must be installed into every workspace, not just source repo. Pre-flight validation (before subprocess launch) catches stale commands due to external state changes. Defense-in-depth prevents agent commits to target repos: combine .gitignore hf.*.md entries + hf.* prefix namespace isolation. Built-in hf.* patterns always take priority over extra patterns in deduplication. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. Path traversal guard required for extra_tool_dirs to verify they don't escape repo boundary. See also: Dynamic Discovery for convention patterns.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W8","title":"Workspace Isolation and Command Discovery via CWD","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849589+00:00","updated_at":"2026-04-10T03:41:18.849590+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pre-Flight Validation and Escalation Pattern

Insert validation checks after environment setup but before main work. Return early with WorkerResult(success=False) on failure and escalate to HITL via escalator. This pattern cleanly separates precondition checking from implementation logic without entangling them. See also: Idempotency Guards for post-execution validation, Prevent Scope Creep for validation as design constraint.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W9","title":"Pre-Flight Validation and Escalation Pattern","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849593+00:00","updated_at":"2026-04-10T03:41:18.849594+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prevent Scope Creep While Maintaining Correctness

Implementation plans are guidelines, not barriers. If necessary correctness fixes fall outside plan scope, document the deviation and rationale. Scope deferral with tracking issues prevents scope creep: defer separate problems to future issues rather than expanding current scope. However, never defer fixes when partial/incomplete fixes leave latent bugs. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones. Pre-mortem identification of failure modes helps design mitigations upfront and prevents rework.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WA","title":"Prevent Scope Creep While Maintaining Correctness","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849596+00:00","updated_at":"2026-04-10T03:41:18.849597+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Model Duplication Across Codebase Suggests Ownership Clarity Issue

Duplicate Pydantic/dataclass versions exist in separate files (adr_pre_validator.py, precheck.py) with canonical dataclasses in models.py. This pattern suggests either missing consolidation or unclear model ownership. Technical debt observation: future work should establish which file owns each model and whether duplicates indicate technical debt or deliberate isolation boundaries. Consider this during next refactoring pass or architectural review.

_Source: #6312 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WF","title":"Model Duplication Across Codebase Suggests Ownership Clarity Issue","topic":null,"source_type":"plan","source_issue":6312,"source_repo":null,"created_at":"2026-04-10T03:41:18.852333+00:00","updated_at":"2026-04-10T03:41:18.852336+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Validate diagram references point to existing code

Architecture diagrams (e.g., .likec4 files) can reference non-existent test files or code paths, creating confusion about implementation status. Before merging diagram changes, validate that all references (test files, classes, modules) actually exist in the codebase. This caught tests referenced but never created.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XH","title":"Validate diagram references point to existing code","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671687+00:00","updated_at":"2026-04-10T05:36:08.671694+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hindsight client cleanup ownership must be explicit

HindsightClient instances used in server modules need clear ownership semantics and cleanup paths. Resource leaks in clients compound across request lifecycles. Scope clients tightly and ensure they're explicitly closed, don't rely on GC.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XJ","title":"Hindsight client cleanup ownership must be explicit","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671709+00:00","updated_at":"2026-04-10T05:36:08.671710+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create regression test files before documentation reference

Don't reference regression test files in architecture documentation before they exist. Create the actual test file first, then reference it. Dangling references in diagrams signal incomplete implementation and confuse future maintainers.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XK","title":"Create regression test files before documentation reference","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671712+00:00","updated_at":"2026-04-10T05:36:08.671713+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture diagram scope can exceed implementation plan

Diagrams may be updated during implementation (e.g., adding .likec4 files) without being listed in the original plan. This is acceptable but should be tracked as documentation scope, not core implementation. Separate architectural updates from feature code in review.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XM","title":"Architecture diagram scope can exceed implementation plan","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671715+00:00","updated_at":"2026-04-10T05:36:08.671716+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Trust Fleet — Lights-Off Background Loop Pattern

HydraFlow runs 10 autonomous trust loops + 2 non-loop subsystems (ADR-0045) that make every automated concern individually observable, killable, and escalatable without a human in the loop. The 10 loops: corpus_learning (skill-escape synthesis), contract_refresh (cassette refresh PRs), staging_bisect (auto-revert on RC red), principles_audit (ADR-0044 drift), flake_tracker (RC flake detection), skill_prompt_eval (weekly adversarial gate), fake_coverage_auditor (un-cassetted methods), rc_budget (wall-clock bloat), wiki_rot_detector (broken cites), trust_fleet_sanity (meta-observer). The 2 subsystems: discover-completeness/shape-coherence evaluator gates (§4.10) and the cost-rollups + diagnostics waterfall (§4.11). Every loop must (1) be a BaseBackgroundLoop subclass with the standard 8-checkpoint wiring; (2) gate every tick on LoopDeps.enabled_cb (ADR-0049); (3) persist dedup via DedupStore keyed on the anomaly; (4) escalate only via the hitl-escalation label; (5) tolerate environment imperfection on startup (broken gh, missing Makefile target, stale credentials → log + skip, never raise). The dark-factory property: no single loop failure can kill the orchestrator; the meta-observer + dead-man-switch make the fleet self-supervising through one bounded meta-layer. See also: Kill-Switch Convention; DedupStore + Reconcile Pattern; Five-Checkpoint Loop Wiring; Meta-Observability with Bounded Recursion.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XHY","title":"Trust Fleet — Lights-Off Background Loop Pattern","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022648+00:00","updated_at":"2026-04-25T00:40:54.022794+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DedupStore + Reconcile-on-Close Pattern

Trust loops file one issue per anomaly (not one per tick). Pattern: (1) compute a stable dedup_key on the anomaly (test_id, sha, plan_name, etc.); (2) check if key in self._dedup.get(); if so, skip filing; (3) on file success, self._dedup.add(key); (4) every tick first calls _reconcile_closed_escalations: lists closed hitl-escalation issues via gh issue list, parses the dedup key from the issue title/body, removes those keys from DedupStore so the next anomaly with the same key re-files. The DedupStore is a filesystem-backed JSON set under .hydraflow/<loop>/dedup.json. Always wrap self._dedup.get() in set(...) before mutating in a loop body — DedupStore returns the backing set, not a copy. Loops that handle terminal events (corpus_learning consumes skill-escape issues; staging_bisect processes a red SHA) don't need reconcile-on-close — once processed, stays processed. Loops that handle ongoing anomalies (flake_tracker, rc_budget, wiki_rot_detector) MUST reconcile so an operator closing the issue clears the counter and lets the loop refile if the anomaly recurs. See also: HITL Escalation Channel; Trust Fleet Pattern.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ0","title":"DedupStore + Reconcile-on-Close Pattern","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022843+00:00","updated_at":"2026-04-25T00:40:54.022844+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Eight-Checkpoint Loop Wiring

Adding a new BaseBackgroundLoop requires synchronized edits in eight places — miss one and the loop may not run, may not be operator-controllable, may not be tested, or will trip a CI drift gate. The eight checkpoints: (1) src/service_registry.py — dataclass field + build_services instantiation; (2) src/orchestrator.py bg_loop_registry dict + loop_factories tuple; (3) src/ui/src/constants.js EDITABLE_INTERVAL_WORKERS set + SYSTEM_WORKER_INTERVALS dict; (4) src/dashboard_routes/_common.py _INTERVAL_BOUNDS dict; (5) tests/scenarios/catalog/test_loop_instantiation.py + test_loop_registrations.py loops list + a tests/scenarios/test_<name>_scenario.py file + tests/scenarios/catalog/loop_registrations.py `_BUILDERS` entry + tests/orchestrator_integration_utils.py SimpleNamespace `services.<name>_loop = FakeBackgroundLoop()`; (6) src/dashboard_routes/_control_routes.py _bg_worker_defs entry (label + description) AND _INTERVAL_WORKERS membership — without this, /api/system/workers won't return the loop and the System tab UI won't render its kill-switch toggle (missed in PR #8390, fixed in #8416); (7) **docs/arch/functional_areas.yml** — the loop's class name MUST appear under exactly one area's `loops:` list; tests/architecture/test_functional_area_coverage.py is a hard gate (introduced PR #8434 with the Architecture Knowledge System; missed in PR #8447 follow-up, caught in `make quality` on PricingRefreshLoop branch); (8) **`uv run python -m arch.runner --emit`** to regenerate docs/arch/generated/* after step (7); the curated/generated drift guard (tests/architecture/test_curated_drift.py, also from PR #8434) is a hard gate that fails CI if generated docs don't match the source-of-truth extractors. Auto-discovery test at tests/test_loop_wiring_completeness.py walks src/*_loop.py and asserts every loop is wired in all checkpoints — run it to catch drift. See also: Kill-Switch Convention; Background Loops and Skill Infrastructure.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ2","title":"Eight-Checkpoint Loop Wiring","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022859+00:00","updated_at":"2026-04-26T20:55:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":2}
```


## Auto-Revert on RC Red — Four-Guardrail Policy

StagingBisectLoop auto-reverts on confirmed RC red with four guardrails (ADR-0048, extends ADR-0042's two-tier branch model). (1) Flake filter: re-run `make bisect-probe` against the same SHA; if the probe passes, increment flake_reruns_total, dedup the SHA, no revert. (2) Bisect attribution: git bisect between last_green_rc_sha and red SHA with `make bisect-probe` as the is-broken predicate, yielding a culprit SHA written into the revert PR body. (3) One auto-revert per cycle: state.get_auto_reverts_in_cycle(); after the first revert, _check_guardrail_and_maybe_escalate fires hitl-escalation + rc-red-attribution-unsafe (matching ADR-0048 §3 exactly — earlier code used the wrong label `rc-red-bisect-exhausted`, fixed in #8390). (4) Revert PR auto-merge: labels `[hydraflow-find, auto-revert, rc-red-attribution]`, flows through the standard reviewer + auto-merge path with no special privileges; an 8-hour watchdog (_check_pending_watchdog) fires rc-red-verify-timeout if the next RC isn't green. The probe MUST use asyncio.create_subprocess_exec (not subprocess.run) because long probes (up to 2700s) on a sync call freeze the event loop — caught in #8390 review. See also: Trust Fleet Pattern; Two-Tier Branch Model.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ5","title":"Auto-Revert on RC Red — Four-Guardrail Policy","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022885+00:00","updated_at":"2026-04-25T00:40:54.022886+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Per-Loop Telemetry — emit_loop_subprocess_trace

Trust loops emit a JSON trace per subprocess call via trace_collector.emit_loop_subprocess_trace(loop, command, duration_ms, returncode). The trace flows through the same telemetry pipeline as inference traces, joined by timestamp in build_per_loop_cost (src/dashboard_routes/_cost_rollups.py) to attribute LLM cost + wall-clock seconds back to the originating loop. The waterfall view at /api/diagnostics/waterfall shows per-loop overlay. The per-loop cost row joins into /api/trust/fleet's loops array (cost_usd, tokens_in, tokens_out, llm_calls fields) so operators see fleet operability + machinery cost on the same pane (spec §4.11.3). Cost rollup failures are caught and reported as zero — an outage in the cost pipeline never takes down the trust dashboard. See also: Trust Fleet Pattern; Meta-Observability.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ6","title":"Per-Loop Telemetry — emit_loop_subprocess_trace","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022895+00:00","updated_at":"2026-04-25T00:40:54.022896+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Spawning background sleep loops to poll for results

Never write `sleep(N)` inside a loop waiting for a test suite or background process to finish.

**Wrong:**

```python
while not result_file.exists():
    time.sleep(5)
```

**Right:**

- Use `run_in_background` with a single command and wait on the notification.
- Run the command in the foreground and await its completion directly.

**Why:** Sleep loops waste wall clock, mask failures, and provide no structured feedback. The harness exposes explicit background-task primitives for this exact purpose — use them.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBD","title":"Spawning background sleep loops to poll for results","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793224+00:00","updated_at":"2026-04-25T00:47:19.793225+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mocking at the wrong level

Patch functions at their **import site**, not their **definition site**.

If `src/base_runner.py` contains `from hindsight import recall_safe`, then within `base_runner` the name `recall_safe` is a local binding. Patching `hindsight.recall_safe` at the definition module leaves the local binding unchanged and the mock is never hit.

**Wrong:**

```python
with patch("hindsight.recall_safe") as mock_recall:
    runner.run()  # runner's local `recall_safe` binding is unaffected
```

**Right:**

```python
with patch("base_runner.recall_safe") as mock_recall:
    runner.run()  # patches the binding the runner actually calls
```

**Why:** Python imports bind names into the importing module's namespace. A patch at the definition module only affects callers that go through that module explicitly, not callers that imported the name locally.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBE","title":"Mocking at the wrong level","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793237+00:00","updated_at":"2026-04-25T00:47:19.793238+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hardcoded path lists that duplicate filesystem state

When multiple files (Dockerfile, Python constant, documentation) must agree on a list of paths or names, scan the authoritative source at runtime instead of hardcoding a parallel list that can drift.

**Wrong:**

```python
# src/agent_cli.py
_DOCKER_PLUGIN_DIRS: tuple[str, ...] = (
    "/opt/plugins/claude-plugins-official",
    "/opt/plugins/superpowers",
    "/opt/plugins/lightfactory",
)
# Dockerfile.agent-base clones these three — but if a fourth is added
# there, this tuple silently stays wrong.
```

**Right:**

```python
# src/agent_cli.py
_PRE_CLONED_PLUGIN_ROOT = Path("/opt/plugins")

def _plugin_dir_flags() -> list[str]:
    if not _PRE_CLONED_PLUGIN_ROOT.is_dir():
        return []
    flags: list[str] = []
    for entry in sorted(_PRE_CLONED_PLUGIN_ROOT.iterdir()):
        if entry.is_dir():
            flags.extend(["--plugin-dir", str(entry)])
    return flags
```

**Why:** Two sources of truth decay. Every time someone edits the Dockerfile, CI passes but the Python list falls behind. Dynamic enumeration of the filesystem (or a single config source) eliminates the drift.

**How to check:** Any hardcoded list that mirrors filesystem layout, Dockerfile state, or config file contents should raise a flag — can it be computed at runtime from the source of truth?


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBK","title":"Hardcoded path lists that duplicate filesystem state","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793271+00:00","updated_at":"2026-04-25T00:47:19.793272+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Adding a new avoided pattern

When you observe a new recurring agent failure:

1. Add a new `##` section to this doc with the same structure (wrong example, right example, why).
2. Consider adding a rule to `src/sensor_rules.py` so the sensor enricher surfaces the hint automatically on matching failures.
3. Consider whether `.claude/commands/hf.audit-code.md` Agent 5 (convention drift) should check for this pattern on its next sweep.

Documenting the pattern once in this file propagates it to all three surfaces.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBN","title":"Adding a new avoided pattern","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793282+00:00","updated_at":"2026-04-25T00:47:19.793283+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background Loop Guidelines

When creating a new background loop (`BaseBackgroundLoop` subclass):

1. **Use `make scaffold-loop`** to generate boilerplate — it handles all wiring.

2. **Restart safety.** Any `self._` state that affects behavior across cycles must either:
   - Be persisted via `StateTracker` or `DedupStore` (survives restart)
   - Be rehydrated from an external source (GitHub API) on first `_do_work()` cycle
   - Be explicitly documented as ephemeral with a `# ephemeral: lost on restart` comment

3. **Wiring checklist** (automated by `tests/test_loop_wiring_completeness.py`):
   - `src/service_registry.py` — dataclass field + `build_services()` instantiation
   - `src/orchestrator.py` — entry in `bg_loop_registry` dict
   - `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`
   - `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`
   - `src/config.py` — interval Field + `_ENV_INT_OVERRIDES` entry

Missing any of these five entries will cause `test_loop_wiring_completeness` to fail. Add them all in the same commit.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBP","title":"Background Loop Guidelines","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793357+00:00","updated_at":"2026-04-25T00:47:19.793358+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Daily Cost-Cap Kill-Switch

HydraFlow honors a global `HYDRAFLOW_DAILY_COST_BUDGET_USD` env var. When the rolling-24h LLM spend exceeds the cap, `CostBudgetWatcherLoop` (5-min tick) calls `BGWorkerManager.set_enabled(name, False)` for ~23 caretaker workers (the curated `_TARGET_WORKERS` list) — only those that were enabled at kill time, so operator-pre-disabled workers are skipped and not claimed. It records the disabled set in `state.cost_budget_killed_workers` so that recovery (rolling-24h sliding window drops back below cap, typically as old high-cost inferences age out) re-enables ONLY the loops it killed. Default `daily_cost_budget_usd = None` means unlimited (no kills). The watcher itself is not in the target set so it can detect recovery; the pipeline loops (triage/plan/implement/review) are also not gated — their cost discipline is via per-issue caps, not the global gate.

**Operator-conflation gotcha:** while the cap is breached, all gated workers appear as ‘disabled’ in the dashboard worker toggles (the watcher’s kills go through the same `set_enabled` path operators use). If an operator manually re-enables a worker during the kill window, the watcher will re-kill it on the next tick. If an operator manually disables a worker AFTER the watcher has killed it, the watcher will still re-enable it on recovery — there’s no way to distinguish "operator disabled this after our kill" from "this was just our kill" without an event log of (name, source, timestamp). Operators wanting a permanent off should set the loop’s per-loop kill-switch env var in addition to the dashboard toggle. See also: Eight-Checkpoint Loop Wiring; cost_budget_alerts.py (alert-only sibling).


```json:entry
{"id":"01KQ6EM4XSPGH58SJXRA27YBDR","title":"Daily Cost-Cap Kill-Switch","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-26T00:00:00.000000+00:00","updated_at":"2026-04-26T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
