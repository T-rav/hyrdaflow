# Architecture Audit

Run a comprehensive architectural boundary audit across the entire repo. Analyzes layer separation, dependency direction, domain purity, adapter thickness, interface design, and coupling patterns. Creates GitHub issues for findings so HydraFlow can process them.

Inspired by Ports & Adapters (Hexagonal Architecture) principles adapted to this codebase's layering.

## HydraFlow Layer Model

The codebase has four layers. Dependencies MUST flow inward only (higher layers depend on lower layers, never the reverse):

```
Layer 4 — Infrastructure/Adapters (I/O, external systems)
  pr_manager.py, worktree.py, merge_conflict_resolver.py,
  post_merge_handler.py, dashboard.py, dashboard_routes/

Layer 3 — Runners (subprocess orchestration, agent invocation)
  base_runner.py, agent.py, planner.py, reviewer.py,
  hitl_runner.py, triage_runner.py, runner_utils.py

Layer 2 — Application (phase coordination, workflow orchestration)
  orchestrator.py, plan_phase.py, implement_phase.py, review_phase.py,
  triage_phase.py, hitl_phase.py, phase_utils.py, pr_unsticker.py,
  base_background_loop.py,
  *_loop.py (background loops)

Layer 1 — Domain (pure data, business rules, no I/O)
  models.py, config.py

Cross-cutting (available to all, imports only from Domain):
  events.py, state/

Composition root (imports from ALL layers to wire dependencies):
  service_registry.py
```

**Dependency direction rule:** A module at layer N may import from layers 1..N but NEVER from layer N+1 or above. Cross-cutting modules may import from Layer 1 only. `service_registry.py` is the composition root — it imports from all layers by design and is exempt from direction checks.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Run `echo "$HYDRAFLOW_LABEL_FIND"` — if set, use it as the label for created issues. If empty, default to `hydraflow-find`.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all `*.py` source files, excluding `.venv/`, `venv/`, `__pycache__/`, `node_modules/`, `dist/`, `build/`, `tests/`.
   - Map each source file to its layer using the layer model above.
   - Build the import graph: for each file, extract all intra-project imports.

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: Layer boundary & dependency direction** — Checks that imports respect layer ordering.
   - **Agent 2: Domain purity & adapter thickness** — Checks domain pollution and overloaded adapters.
   - **Agent 3: Interface design & coupling** — Checks brittle interfaces, use-case coupling, and API boundaries.

4. Wait for all agents to complete.
5. After all finish, run `gh issue list --repo $REPO --label $LABEL --state open --search "architecture" --limit 200` to show the user a final summary of all issues created.

## Agent 1: Layer Boundary & Dependency Direction

```
You are an architecture auditor focused on layer boundaries and dependency direction for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Layer Assignment

Assign each source file to a layer:

| Layer | Files | Role |
|-------|-------|------|
| 1 — Domain | models.py, config.py | Pure data models, business rules, no I/O |
| 2 — Application | orchestrator.py, *_phase.py, phase_utils.py, pr_unsticker.py, base_background_loop.py, *_loop.py | Workflow coordination, phase management |
| 3 — Runners | base_runner.py, agent.py, planner.py, reviewer.py, hitl_runner.py, triage_runner.py, runner_utils.py | Agent subprocess management |
| 4 — Infrastructure | pr_manager.py, worktree.py, merge_conflict_resolver.py, post_merge_handler.py, dashboard.py, dashboard_routes/ | I/O, external tools, HTTP endpoints |
| X — Cross-cutting | events.py, state/ | Shared infrastructure (imports only from Layer 1) |
| CR — Composition root | service_registry.py | Wires all layers; exempt from direction checks |

## Steps

### Phase 1: Build Import Graph
1. Use Glob to find all *.py source files in src/ (exclude tests/, .venv/, __pycache__/)
2. Read each source file and extract all import statements that reference other project modules
3. For each import, record: source_file, source_layer, imported_module, imported_layer
4. Assign layer numbers per the table above. Files not in the table: infer from directory and naming pattern, or flag as "unassigned"

### Phase 2: Check Dependency Direction
5. For each import edge, check:
   - **Upward violation**: Layer N imports from layer N+1 or higher (CRITICAL — breaks architecture)
   - **Cross-cutting pollution**: events.py, state/*.py importing from Layer 2+ (should only import Layer 1)
   - **Lateral coupling**: Two modules at the same layer importing each other (circular — suggests missing abstraction)
   - **Skip-layer**: Layer 2 importing directly from Layer 4, bypassing Layer 3 (suggests missing intermediary)
6. service_registry.py is the composition root — it wires all layers by design and is exempt from direction checks

### Phase 3: Check Circular Dependencies
7. From the import graph, detect cycles:
   - Direct cycles: A imports B, B imports A
   - Transitive cycles: A → B → C → A
   - For each cycle, note all participants and which edge should be broken

### Phase 4: Check Layer Isolation
8. For each layer, verify:
   - **Domain (Layer 1)**: Zero imports from Layers 2-4. No subprocess, no HTTP, no file I/O beyond Pydantic model loading. No asyncio primitives.
   - **Application (Layer 2)**: No direct subprocess calls, no `gh` CLI invocations, no HTTP requests. Delegates all I/O to Runners or Infrastructure.
   - **Runners (Layer 3)**: Should not directly query GitHub API or manage git worktrees — delegates to Infrastructure.
   - **Infrastructure (Layer 4)**: Should not contain business logic (workflow decisions, state transitions, retry policies).

### Phase 5: Create GitHub Issues
9. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
10. Create GH issues for NEW findings only, grouped by theme:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Architecture: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why this boundary violation matters>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Layer Violations
| Severity | Source (Layer) | Imports (Layer) | Import Statement | Why It's Wrong |
|----------|---------------|-----------------|------------------|----------------|
| <critical/warning> | <file (N)> | <file (M)> | <import line> | <N imports from M where M > N> |

## Circular Dependencies
| Cycle | Files | Breaking Edge |
|-------|-------|---------------|
| <A → B → A> | <files> | <which import to remove/invert> |

## Suggested Fixes
- [ ] <file:line> — Move <function> to Layer <N> or introduce interface/protocol
- [ ] <file:line> — Replace direct import with callback/event pattern
- [ ] <file:line> — Extract I/O into adapter, keep business logic in application layer

## Acceptance Criteria
- [ ] No upward dependency violations remain
- [ ] No circular imports between layers
- [ ] Cross-cutting modules import only from Domain
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Layer Diagram
<ASCII diagram showing the violation and the fix>
```

## Grouping Strategy
- "Architecture: Fix upward dependency violations in <module>"
- "Architecture: Break circular imports between <A> and <B>"
- "Architecture: Remove I/O from application layer in <module>"
- "Architecture: Remove business logic from infrastructure layer in <module>"

Focus on critical violations (upward deps, circular imports). Skip minor lateral imports between closely related modules at the same layer.

Return a summary of all findings grouped by severity, with GH issue URLs created.
```

## Agent 2: Domain Purity & Adapter Thickness

```
You are an architecture auditor focused on domain purity and adapter thickness for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Anti-Pattern Definitions

Six architectural anti-patterns to detect (adapted from Ports & Adapters / Hexagonal Architecture):

1. **Domain Pollution** — External/infrastructure types leak into domain models
2. **Anemic Entities** — Domain models are pure data bags with logic scattered elsewhere
3. **Overloaded Adapters** — Infrastructure modules contain business logic
4. **Schema-First Design** — Persistence schema drives domain model shape
5. **Brittle Interfaces** — Public APIs accept raw primitives instead of typed wrappers
6. **Feature Envy** — Functions that primarily operate on another module's data

## Steps

### Phase 1: Audit Domain Purity (models.py, config.py)
1. Read models.py and config.py thoroughly
2. Check for **Domain Pollution**:
   - Do domain models import or reference infrastructure types? (httpx.Response, asyncio.Task, subprocess types, GitHub API response shapes)
   - Do domain models contain serialization logic for a specific transport? (JSON, protobuf, etc. beyond Pydantic's built-in)
   - Do domain models reference external service IDs that couple them to a specific provider?
   - Are there `# type: ignore` comments hiding infrastructure type leakage?
3. Check for **Anemic Entities**:
   - Do Pydantic models have meaningful methods, or are they just field containers?
   - Is validation logic embedded in the models (via validators, `model_validator`, `field_validator`) or scattered in callers?
   - Are business rules (e.g., "an issue can only transition from plan to implement") encoded in the model, or reimplemented in every phase?
   - Are there utility functions elsewhere that should be methods on the domain model?
   - Note: not all models need rich behavior — pure data transfer objects are fine. Flag only models that SHOULD encapsulate logic but don't.

### Phase 2: Audit Adapter Thickness (Infrastructure Layer)
4. Read pr_manager.py, worktree.py, merge_conflict_resolver.py, post_merge_handler.py, dashboard_routes/
5. Check for **Overloaded Adapters**:
   - Do infrastructure modules contain business logic? (workflow decisions, retry policies, state transitions)
   - Do they make decisions about WHAT to do, rather than just HOW to do it?
   - Do they reference phase-level concepts (issue lifecycle, review verdicts)?
   - Are there if/else chains in adapters that encode business rules?
   - Rule of thumb: adapters should be thin translation layers. If you removed the adapter and replaced it with a different one (e.g., GitLab instead of GitHub), would you lose business logic?
6. Check for **Schema-First Design**:
   - Does the state.json structure drive how domain models are shaped?
   - Are domain model field names dictated by a database schema or API response?
   - Is there a mismatch where domain models have fields that only exist for persistence convenience?

### Phase 3: Audit Interface Design
7. Read public function signatures across all layers
8. Check for **Brittle Interfaces**:
   - Functions with 5+ primitive parameters (str, int, bool) instead of a typed request/config object
   - Functions where adding a new option means changing every caller's signature
   - Functions that accept `**kwargs` and pass them through without type safety
   - Phase/runner APIs that accept raw dicts instead of typed Pydantic models
9. Check for **Feature Envy**:
   - Functions that mostly access fields from an object they receive as a parameter, rather than their own state
   - Utility functions that should be methods on the object they primarily operate on
   - Cross-module functions that deeply inspect another module's internal data structures

### Phase 4: Naming Consistency
10. Check naming conventions across layers:
    - Are types that cross layer boundaries consistently named? (e.g., *Result for outcomes, *Config for configuration, *Payload for events)
    - Are conversion functions consistently named? (e.g., `from_*` for constructing from external data, `to_*` for serializing)
    - Are there naming collisions where the same concept has different names in different layers?

### Phase 5: Create GitHub Issues
11. Check for duplicate GH issues first:
    gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
12. Create GH issues for NEW findings only, grouped by anti-pattern:
    gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Architecture: <anti-pattern>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on the architectural risk>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Anti-Pattern Findings
| Anti-Pattern | File:Line | Current | Problem | Suggested Fix |
|-------------|-----------|---------|---------|---------------|
| <Domain Pollution/Anemic Entity/etc.> | <path:line> | <current code> | <why it's wrong> | <what to do> |

## Suggested Fixes
- [ ] <file:line> — Move <logic> from adapter into domain model method
- [ ] <file:line> — Replace primitive params with <TypedRequest> object
- [ ] <file:line> — Extract business rule from <adapter> into <phase/domain>
- [ ] <file:line> — Add validation method to <Model> (currently scattered in 3 callers)

## Acceptance Criteria
- [ ] Domain models contain no infrastructure imports
- [ ] Adapters contain no business logic (workflow decisions, state transitions)
- [ ] Public APIs use typed objects, not primitive sprawl
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Portability: <how much easier to swap infrastructure>
- Testability: <how much easier to unit-test domain logic>
- Maintainability: <how much clearer are the boundaries>
```

## Grouping Strategy
- "Architecture: Remove infrastructure types from domain models"
- "Architecture: Enrich anemic domain models with validation logic"
- "Architecture: Extract business logic from adapters"
- "Architecture: Replace brittle primitive interfaces with typed objects"
- "Architecture: Fix feature envy — move logic to owning module"

Be pragmatic:
- Small utility functions don't need full hexagonal purity
- Config objects are legitimately wide — don't flag config.py for having many fields
- Pydantic models that are pure DTOs are fine as data bags — only flag models that SHOULD have behavior
- Focus on violations that would cause real problems during refactoring, testing, or infrastructure swaps

Return a summary of all findings grouped by anti-pattern, with GH issue URLs created.
```

## Agent 3: Interface Design & Coupling

```
You are an architecture auditor focused on interface design and module coupling for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Audit Use-Case Isolation
1. Read all phase files (*_phase.py) and the orchestrator
2. Check for **Use-Case Coupling**:
   - Do phases call other phases directly? (PlanPhase calling ImplementPhase methods = tight coupling)
   - Do phases share mutable state beyond what the orchestrator manages?
   - Do phases reach into each other's internal data structures?
   - Are there shared functions in phase_utils.py that encode phase-specific logic instead of genuinely shared concerns?
   - Each phase should independently coordinate its domain objects. Inter-phase communication should go through the orchestrator, event bus, or state tracker — not direct imports.
3. Check for **Orchestrator Overreach**:
   - Does the orchestrator contain business logic that belongs in a phase? (e.g., deciding whether an issue is ready, computing review verdicts)
   - Does it reach into runner internals?
   - It should coordinate phases, not do their work.

### Phase 2: Audit Runner Boundaries
4. Read all runner files (base_runner.py, agent.py, planner.py, reviewer.py)
5. Check for **Runner Coupling**:
   - Do runners import from or reference other runners? (AgentRunner should not know about ReviewRunner)
   - Do runners directly call infrastructure modules (pr_manager, worktree) instead of receiving them as injected dependencies?
   - Do runners make phase-level decisions? (A runner should execute work, not decide what issue to work on next)
6. Check for **Leaky Abstractions**:
   - Do runner results expose subprocess internals (return codes, stderr) to callers?
   - Do phase coordinators need to parse runner output format? (Runner should return typed results)
   - Are there places where callers catch runner-internal exceptions?

### Phase 3: Audit Event Bus Usage
7. Read events.py and all event publishers/subscribers
8. Check for **Event Anti-Patterns**:
   - **Event-carried state transfer**: Events carrying full objects instead of IDs (coupling publisher schema to subscriber)
   - **Command events**: Events that tell a subscriber what to do (should be informational, not imperative)
   - **Missing events**: State transitions that happen silently without events (breaks dashboard observability)
   - **Event handler side effects**: Subscribers that modify shared state in response to events (hidden coupling)
   - **Event type explosion**: Too many event types for variations of the same concept

### Phase 4: Audit Dependency Injection
9. Read service_registry.py and check:
   - Are there services constructed outside the registry? (Scattered `__init__` calls instead of centralized wiring)
   - Are there services that create their own dependencies instead of receiving them? (new PRManager() inside a phase instead of receiving it)
   - Is the registry passed around as a god-object, or are individual services injected? (Passing the whole registry is a service locator anti-pattern)
   - Are there optional dependencies that silently degrade instead of failing fast at startup?

### Phase 5: Audit Cross-Layer Data Flow
10. Trace the data flow for key operations:
    - Issue triage: How does an issue enter the system and reach the triage phase?
    - Implementation: How does a plan get to the implementation agent?
    - Review: How does review feedback reach the implementer for retry?
    For each flow, check:
    - Is data transformed at each layer boundary, or does a raw GitHub API response travel from adapter to domain?
    - Are there places where intermediate layers just pass data through without adding value? (suggests wrong layer assignment)
    - Are there places where data is re-fetched instead of passed? (suggests missing data flow)

### Phase 6: Create GitHub Issues
11. Check for duplicate GH issues first:
    gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
12. Create GH issues for NEW findings only:
    gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Architecture: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on the coupling/design risk>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Coupling Findings
| Type | Source | Target | How | Why It's Wrong |
|------|--------|--------|-----|----------------|
| <direct call/shared state/leaked abstraction> | <module> | <module> | <import/access> | <creates tight coupling because...> |

## Event Bus Issues (if any)
| Issue | Event Type | Publisher | Problem |
|-------|-----------|-----------|---------|
| <command event/state transfer/missing event> | <type> | <module> | <description> |

## DI Issues (if any)
| Issue | Module | Current | Suggested |
|-------|--------|---------|-----------|
| <self-created dep/god object/silent degrade> | <module> | <current pattern> | <injected pattern> |

## Suggested Fixes
- [ ] <file:line> — Replace direct phase call with event/orchestrator coordination
- [ ] <file:line> — Inject <service> instead of constructing it
- [ ] <file:line> — Return typed result from runner instead of raw subprocess output
- [ ] <file:line> — Add event for <state transition> to enable dashboard tracking

## Acceptance Criteria
- [ ] Phases do not directly call other phases
- [ ] Runners do not make phase-level decisions
- [ ] Event payloads carry IDs, not full objects
- [ ] All services are wired through the registry
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)
```

## Grouping Strategy
- "Architecture: Decouple phases — remove direct inter-phase calls"
- "Architecture: Fix runner boundary violations"
- "Architecture: Clean up event bus anti-patterns"
- "Architecture: Centralize service construction in registry"
- "Architecture: Fix leaky abstractions in runner results"

Focus on coupling that would cause cascading changes during refactoring. Skip cosmetic coupling between closely related modules that genuinely belong together.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Important Notes
- Each agent should read files directly (no spawning sub-agents)
- Each agent should check `gh issue list` before creating any issue to avoid duplicates
- All issues should use the resolved `$REPO`, `$ASSIGNEE`, and `$LABEL`
- Group related findings into single themed issues — don't create one issue per violation
- Title format: "Architecture: <theme>" for consistency
- Be pragmatic: hexagonal purity is a goal, not a religion. Flag violations that cause real pain (hard to test, hard to refactor, cascading changes) — not theoretical impurity
- service_registry.py is exempt from dependency direction rules — it's the composition root
- Skip test files entirely — architectural rules apply to production code only
- Don't flag Pydantic model_validator / field_validator as "logic in domain" — that IS the right place for validation
