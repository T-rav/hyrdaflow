# Architecture


## ADR Structure and Validation Checklist

Use standard ADR format with Date, Status, Title, Context, Decision, Rationale, and Consequences sections. Validate structurally first (missing sections, status format) then semantically (scope significance, contradiction audit). Verify all 7 sections exist before checking if decision contradicts existing Accepted ADRs. **Why:** structural checks catch format errors early; semantic checks catch logic contradictions that structure-only validation misses.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQR","title":"ADR Structure and Validation Checklist","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803403+00:00","updated_at":"2026-05-03T04:16:50.803613+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Source Citations and Runtime References in ADRs

Cite authoritative sources using module:function format without line numbers per CLAUDE.md; skip TYPE_CHECKING imports in citations. Reference runtime sources (src/config.py:all_pipeline_labels) instead of copying values into ADR documentation. Link to src/models.py JSON schema rather than pasting field types. **Why:** module:function format is stable across code edits; copying values causes drift when source changes.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQS","title":"Source Citations and Runtime References in ADRs","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803663+00:00","updated_at":"2026-05-03T04:16:50.803664+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Set ADR Status to 'Accepted' for Existing Implicit Patterns

Use Accepted status not just for new proposals but for documenting existing architectural patterns already in the codebase. Example: if loops already practice state persistence via DedupStore, document that in an Accepted ADR even if it was never formally proposed. **Why:** makes implicit architectural decisions visible and searchable for future maintainers.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQT","title":"Set ADR Status to 'Accepted' for Existing Implicit Patterns","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803676+00:00","updated_at":"2026-05-03T04:16:50.803677+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## ADR Superseding When Feature Is Removed

When a planned feature in an ADR is removed as dead code before implementation, set status to 'Superseded by removal' and cross-reference the removal issue. Example: ADR documents new loop → loop designed but dropped as dead code → set status to 'Superseded by removal' and link removal PR. **Why:** preserves architectural history and clarifies that re-implementing would be reattempting, not inventing.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQV","title":"ADR Superseding When Feature Is Removed","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803690+00:00","updated_at":"2026-05-03T04:16:50.803691+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Ghost Entries Indicate Stale Documentation Migrations

If an ADR README references a file or concept that doesn't exist in the codebase, it's a ghost entry signaling incomplete migration—validate documentation against filesystem reality. Example: README lists ADR about 'ThreePhaseEventBus' but code was refactored to 'EventBus'; update or remove stale references. **Why:** stale references confuse contributors and hide incomplete cleanup.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQW","title":"Ghost Entries Indicate Stale Documentation Migrations","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803703+00:00","updated_at":"2026-05-03T04:16:50.803705+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## LLM-Based Architecture Checks Need Conservative Scope

When implementing LLM architecture compliance checks (arch_compliance.py, hf.audit-architecture skill), use conservative language ('flag clear violations only'), disable-friendly config (max_attempts=1), and exempt sensitive modules (service_registry.py). **Why:** overly aggressive checks block every PR; conservative scope allows operators to control adoption and prevents false-positive blocking.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQX","title":"LLM-Based Architecture Checks Need Conservative Scope","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803712+00:00","updated_at":"2026-05-03T04:16:50.803715+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred Imports and Async Read-Then-Write Are Documented Acceptable

Don't flag intentional deferred imports (TYPE_CHECKING patterns) or async read-modify-write state patterns in architecture compliance checks; they're documented constraints, not violations. Example: `if TYPE_CHECKING: from module import Type` and StateTracker fetch-then-modify-write are intentional design patterns. **Why:** refactoring these patterns would require major changes; documenting as acceptable prevents false-positive flags.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQY","title":"Deferred Imports and Async Read-Then-Write Are Documented Acceptable","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803721+00:00","updated_at":"2026-05-03T04:16:50.803722+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture Tests Must Assert Content Not Just Structure

Tests checking layer assignments or module organization must verify actual content (correct module names in layers), not just that the structure exists. Example: don't assert layer labels exist; assert they contain the right module names. **Why:** structure-only assertion misses silent failures like empty layers or misassigned modules.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFQZ","title":"Architecture Tests Must Assert Content Not Just Structure","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803739+00:00","updated_at":"2026-05-03T04:16:50.803741+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Three-Layer Defense-in-Depth for Architecture Enforcement

Combine linter rules (ruff T20/T10 for debug code), AST validation scripts (per-function test coverage), and git hooks (commit format) rather than relying on single enforcement layer. Example: ruff catches print statements, AST validates test density, hooks verify message format. **Why:** single-layer enforcement misses complementary problems; multiple layers catch different violations.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR0","title":"Three-Layer Defense-in-Depth for Architecture Enforcement","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803752+00:00","updated_at":"2026-05-03T04:16:50.803753+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Claude Code Discovers Commands From Subprocess CWD

Claude Code discovers commands from subprocess's cwd/.claude/commands/, not invoking process; commands must be installed in every workspace/fork where they'll run. Example: agents spawned in worktrees need command copies in that worktree's .claude/commands/. **Why:** subprocess sandboxes are isolated; environments don't inherit parent process state.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR1","title":"Claude Code Discovers Commands From Subprocess CWD","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803759+00:00","updated_at":"2026-05-03T04:16:50.803762+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## hf.* Namespace Isolation with .gitignore Entries

Use hf.* prefix namespace isolation (hf.audit-code.md, hf.*.md patterns) plus .gitignore entries to prevent agent-generated files from polluting target repos. Example: agents generate hf.audit-findings.md, not audit_findings.md; .gitignore lists hf.*.md. **Why:** prevents merge conflicts and accidental commits to user repos.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR2","title":"hf.* Namespace Isolation with .gitignore Entries","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803769+00:00","updated_at":"2026-05-03T04:16:50.803770+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Unified Discovery Across Multiple Registration Mechanisms

When code registers via multiple mechanisms (dict, tuple, function registry), use set union to discover all entries and prevent gaps. Built-in hf.* patterns take priority over extra patterns. Example: discover loops via union of (bg_loop_registry dict, loop_factories tuple, docs/arch/functional_areas.yml). **Why:** multiple registration paths can diverge; unified discovery catches missing entries.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR3","title":"Unified Discovery Across Multiple Registration Mechanisms","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803776+00:00","updated_at":"2026-05-03T04:16:50.803780+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Path Traversal Guard for extra_tool_dirs

Validate extra_tool_dirs paths don't escape the repo boundary. Example: extra_tool_dirs = ['/opt/safe/tools'], never /etc or other system paths. **Why:** prevents accidental or intentional access to sensitive paths outside the repo.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR4","title":"Path Traversal Guard for extra_tool_dirs","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803787+00:00","updated_at":"2026-05-03T04:16:50.803790+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pre-Flight Validation and Escalation Pattern

Insert validation checks after environment setup but before main work; return early with WorkerResult(success=False) and escalate to HITL via escalator on failure. Example: before running agent pipeline, validate state files exist and credentials work. **Why:** separates precondition checking from implementation logic without entangling them.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR5","title":"Pre-Flight Validation and Escalation Pattern","topic":null,"source_type":"plan","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803797+00:00","updated_at":"2026-05-03T04:16:50.803798+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prevent Scope Creep While Maintaining Correctness

Implementation plans are guidelines, not barriers. If necessary correctness fixes fall outside scope, document the deviation and defer separate problems to future issues. Never defer fixes when partial solutions leave latent bugs—fix all instances at once. **Why:** partial fixes compound into hidden bugs later; correctness takes precedence over scope.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR6","title":"Prevent Scope Creep While Maintaining Correctness","topic":null,"source_type":"plan","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803805+00:00","updated_at":"2026-05-03T04:16:50.803806+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Model Duplication Across Codebase Suggests Ownership Clarity Issue

Duplicate Pydantic/dataclass versions in separate files (adr_pre_validator.py, precheck.py) with canonical versions in models.py indicate unclear model ownership. Future work should establish which file owns each model and whether duplicates reflect intentional isolation or consolidation debt. **Why:** duplicate models diverge silently during refactoring, causing hidden bugs.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR7","title":"Model Duplication Across Codebase Suggests Ownership Clarity Issue","topic":null,"source_type":"plan","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803815+00:00","updated_at":"2026-05-03T04:16:50.803816+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Validate Diagram References Point to Existing Code

Architecture diagrams (e.g., .likec4 files) can reference non-existent test files or code paths, creating confusion about implementation status. Before merging diagram changes, validate all references (test files, classes, modules) actually exist. **Why:** dangling references in diagrams confuse future maintainers about what's implemented.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR8","title":"Validate Diagram References Point to Existing Code","topic":null,"source_type":"review","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803821+00:00","updated_at":"2026-05-03T04:16:50.803822+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hindsight Client Cleanup Ownership Must Be Explicit

HindsightClient instances used in server modules need clear ownership semantics and explicit cleanup paths. Resource leaks compound across request lifecycles. Example: document who owns each HindsightClient instance and when it's explicitly closed; don't rely on GC. **Why:** implicit cleanup is unreliable and can exhaust connection pools.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFR9","title":"Hindsight Client Cleanup Ownership Must Be Explicit","topic":null,"source_type":"review","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803827+00:00","updated_at":"2026-05-03T04:16:50.803828+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create Regression Test Files Before Documentation Reference

Don't reference regression test files in architecture documentation before they exist. Create the actual test file first, then reference it in docs/architecture diagrams. **Why:** dangling references signal incomplete implementation and confuse maintainers about what's actually tested.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRA","title":"Create Regression Test Files Before Documentation Reference","topic":null,"source_type":"review","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803833+00:00","updated_at":"2026-05-03T04:16:50.803835+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture Diagram Scope Can Exceed Implementation Plan

Diagrams may be updated during implementation (e.g., adding .likec4 files) without being listed in the original plan. This is acceptable but should be tracked as documentation scope, not core implementation. Example: plan covers feature X; implementer also adds .likec4 diagrams during code review. **Why:** separates architectural documentation updates from feature code in review.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRB","title":"Architecture Diagram Scope Can Exceed Implementation Plan","topic":null,"source_type":"review","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803839+00:00","updated_at":"2026-05-03T04:16:50.803843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Trust Fleet — Lights-Off Background Loop Pattern

HydraFlow runs 10 autonomous trust loops (corpus_learning, contract_refresh, staging_bisect, principles_audit, flake_tracker, skill_prompt_eval, fake_coverage_auditor, rc_budget, wiki_rot_detector, trust_fleet_sanity) plus 2 subsystems making every concern individually observable, killable, and escalatable. Each loop is a BaseBackgroundLoop subclass with standard 8-checkpoint wiring, gates every tick on LoopDeps.enabled_cb, deduplicates via DedupStore, escalates via hitl-escalation label, and tolerates startup imperfection. No single loop failure kills orchestrator; meta-observer + dead-man-switch make fleet self-supervising. **Why:** independent loops with fault isolation enable resilient autonomous operation.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRC","title":"Trust Fleet — Lights-Off Background Loop Pattern","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803848+00:00","updated_at":"2026-05-03T04:16:50.803849+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DedupStore + Reconcile-on-Close Pattern

Trust loops file one issue per anomaly (not one per tick). Pattern: (1) compute stable dedup_key (test_id, sha, plan_name); (2) check if key in self._dedup.get(); skip if found; (3) on file success, self._dedup.add(key); (4) every tick calls _reconcile_closed_escalations: list closed hitl-escalation issues via gh, parse dedup key from title/body, remove from DedupStore. DedupStore is filesystem-backed JSON set (.hydraflow/<loop>/dedup.json). Example: flake_tracker reconciles closed flake issues so the same test can refile if flake recurs. **Why:** prevents duplicate issues while allowing re-filing after operator closes.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRD","title":"DedupStore + Reconcile-on-Close Pattern","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803854+00:00","updated_at":"2026-05-03T04:16:50.803855+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Eight-Checkpoint Loop Wiring Checklist

Adding a BaseBackgroundLoop requires edits across 8 locations: (1) service_registry.py, (2) orchestrator.py, (3) UI constants, (4-5) dashboard routes (2 files), (6) test scenarios, (7) functional_areas.yml, (8) arch regeneration. Alternatively, use make scaffold-loop to auto-generate all edits. **Why:** missing any checkpoint causes silent runtime failures—loop won't run, can't be killed, and won't be testable.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRE","title":"Eight-Checkpoint Loop Wiring Checklist","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803860+00:00","updated_at":"2026-05-03T04:16:50.803861+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Loop Wiring Auto-Discovery Test

Test test_loop_wiring_completeness.py auto-discovers all BaseBackgroundLoop subclasses in src/ and asserts each is registered across all 8 checkpoints. This prevents incomplete manual wiring from slipping past review. **Why:** synchronizing 8 locations manually is error-prone; automated discovery catches omissions early.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRF","title":"Loop Wiring Auto-Discovery Test","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803867+00:00","updated_at":"2026-05-03T04:16:50.803869+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Auto-Revert on RC Red — Four-Guardrail Policy

StagingBisectLoop auto-reverts on confirmed RC red with four guardrails: (1) Flake filter—re-run make bisect-probe against same SHA; if passes, increment flake_reruns_total and dedup. (2) Bisect attribution—git bisect between last_green_rc_sha and red SHA to yield culprit SHA. (3) One auto-revert per cycle—blocks second revert; first triggers hitl-escalation. (4) Revert PR auto-merge—labels [hydraflow-find, auto-revert, rc-red-attribution] flow through standard reviewer path. **Why:** guardrails prevent reverting transient flakes while ensuring attribution.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRG","title":"Auto-Revert on RC Red — Four-Guardrail Policy","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803874+00:00","updated_at":"2026-05-03T04:16:50.803875+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Per-Loop Telemetry — emit_loop_subprocess_trace

Trust loops emit JSON trace per subprocess call via trace_collector.emit_loop_subprocess_trace(loop, command, duration_ms, returncode), flowing through same pipeline as inference traces. Per-loop cost join in build_per_loop_cost (src/dashboard_routes/_cost_rollups.py) attributes LLM cost + wall-clock seconds back to originating loop. Waterfall view and cost row in /api/trust/fleet's loops array let operators see fleet operability + machinery cost together. **Why:** per-loop cost visibility drives operator decisions about which loops to run.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRH","title":"Per-Loop Telemetry — emit_loop_subprocess_trace","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803881+00:00","updated_at":"2026-05-03T04:16:50.803882+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never Write Sleep Loops Waiting for Background Tasks

Never write `sleep(N)` inside a loop waiting for a test suite or background process. Wrong: `while not result_file.exists(): time.sleep(5)`. Right: use run_in_background with single command and wait on notification, or run command in foreground awaiting directly. **Why:** sleep loops waste wall-clock, mask failures, and provide no structured feedback; harness exposes explicit background-task primitives.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRJ","title":"Never Write Sleep Loops Waiting for Background Tasks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803887+00:00","updated_at":"2026-05-03T04:16:50.803888+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mocking at the Wrong Level

Patch functions at their **import site**, not their **definition site**. If src/base_runner.py contains `from hindsight import recall_safe`, the name `recall_safe` is a local binding. Patching `hindsight.recall_safe` leaves the local binding unchanged; patch at `base_runner.recall_safe` instead. **Why:** Python imports bind names into importing module's namespace; patching definition module only affects explicit callers, not local-import callers.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRK","title":"Mocking at the Wrong Level","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803893+00:00","updated_at":"2026-05-03T04:16:50.803894+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hardcoded Path Lists That Duplicate Filesystem State

When multiple files (Dockerfile, Python constant, docs) must agree on a list of paths/names, scan the authoritative source at runtime instead of hardcoding a parallel list that can drift. Wrong: _DOCKER_PLUGIN_DIRS tuple hardcoded in Python while Dockerfile lists them separately. Right: def _plugin_dir_flags() → dynamically enumerate _PRE_CLONED_PLUGIN_ROOT.iterdir(). **Why:** two sources of truth decay; dynamic enumeration eliminates drift.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRM","title":"Hardcoded Path Lists That Duplicate Filesystem State","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803899+00:00","updated_at":"2026-05-03T04:16:50.803899+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Adding a New Avoided Pattern

When you observe a new recurring agent failure: (1) add ## section to gotchas.md with wrong/right examples + why; (2) consider adding rule to src/sensor_rules.py so sensor enricher surfaces hint automatically; (3) consider whether hf.audit-code Agent 5 should check pattern on next sweep. **Why:** documenting once propagates to all three surfaces (docs, sensors, audit).


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRN","title":"Adding a New Avoided Pattern","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803905+00:00","updated_at":"2026-05-03T04:16:50.803907+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use make scaffold-loop to Generate Loop Boilerplate

When creating a new BaseBackgroundLoop, run `make scaffold-loop` to generate boilerplate—it handles all wiring automatically. Example: `make scaffold-loop --name my_loop` generates complete loop class with imports and stubs. **Why:** manual wiring across 8 checkpoints is error-prone; scaffolding ensures completeness and prevents drift.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRP","title":"Use make scaffold-loop to Generate Loop Boilerplate","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803912+00:00","updated_at":"2026-05-03T04:16:50.803913+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Restart Safety for self._ State in Background Loops

Any self._ state affecting behavior across cycles must either (1) persist via StateTracker or DedupStore (survives restart), (2) be rehydrated from external source on first _do_work() cycle (e.g., fetch from GitHub API), or (3) be explicitly documented as ephemeral with comment. Example: `self._loop_count = 0  # ephemeral: lost on restart` documents temporary state. **Why:** loops survive restarts; state must be designed for that or explicitly marked as ephemeral.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRQ","title":"Restart Safety for self._ State in Background Loops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803918+00:00","updated_at":"2026-05-03T04:16:50.803919+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Daily Cost-Cap Kill-Switch

HydraFlow honors HYDRAFLOW_DAILY_COST_BUDGET_USD env var. When rolling-24h LLM spend exceeds cap, CostBudgetWatcherLoop calls BGWorkerManager.set_enabled(name, False) for ~23 caretaker workers; only pre-enabled workers killed. Records disabled set in state.cost_budget_killed_workers for recovery—re-enables ONLY loops it killed when spending drops. Operator conflation gotcha: all gated workers appear disabled during breach; manually re-enabling will be re-killed next tick. Operators wanting permanent off should set per-loop kill-switch env var. **Why:** cost discipline prevents unbounded LLM spend while preserving operator recovery control.


```json:entry
{"id":"01KQP0V9KK99G77287P414NFRR","title":"Daily Cost-Cap Kill-Switch","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:16:50.803925+00:00","updated_at":"2026-05-03T04:16:50.803926+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
