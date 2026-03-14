# RPI-Inspired Planning & Task Decomposition Improvements

**Status:** Draft
**Date:** 2026-03-13
**Source:** [agentpatterns/craft](https://github.com/agentpatterns/craft) RPI pattern analysis

---

## Problem

HydraFlow's planner produces free-form prose plans with bulleted "Implementation Steps."
The implementer receives this as a wall of text and must self-organize execution order,
decide what to test, and validate its own work. This leads to:

1. **Unstructured execution** — no dependency ordering within a plan, no parallelism signals
2. **Vague test guidance** — "Testing Strategy" section is aspirational, not actionable
3. **Single-agent blind spots** — the same agent writes code, writes tests, and self-reviews
4. **No research separation** — the planner explores and plans in one shot, limiting depth on complex issues

---

## Changes

### Phase 1: Structured Plan Format (Planner Prompt + Validation)

**Goal:** Replace free-form Implementation Steps with a dependency-aware task graph
and behavioral test specs.

**Files:** `src/planner.py`, `src/models.py`

#### 1.1 Add `## Task Graph` section to plan format

Replace the current `## Implementation Steps` with a structured task graph:

```markdown
## Task Graph

### P1 — Database Schema
**Files:** src/models.py (modify), migrations/0042_add_widget.py (create)
**Tests:**
- Creating a Widget with valid fields persists and returns an id
- Creating a Widget with a duplicate name raises IntegrityError
- Null required fields are rejected at the DB level
**Depends on:** (none)

### P2 — Core Logic
**Files:** src/widget_service.py (create), src/validators.py (modify)
**Tests:**
- WidgetService.create() with valid input returns a Widget
- WidgetService.create() with invalid input raises ValidationError
- WidgetService.list() returns only active widgets
**Depends on:** P1

### P3 — API Route
**Files:** src/routes/widgets.py (create), src/routes/__init__.py (modify)
**Tests:**
- POST /widgets with valid body returns 201 with {id, name}
- POST /widgets with missing name returns 400
- GET /widgets returns paginated list
**Depends on:** P2
```

**Key rules:**
- Phases use `P{N} — {Name}` format; lower numbers execute first
- Each phase lists files (create/modify), behavioral test specs, and dependencies
- Test specs are **behavioral** — describe observable outcomes, not test code
- Independent phases at the same level can execute in parallel (future)
- Max 6 phases per plan; if more are needed, the issue should be decomposed into an epic

#### 1.2 Update plan validation

Add to `PlannerRunner._validate_plan()`:

- `## Task Graph` is a required section (replacing `## Implementation Steps`)
- Must contain at least one `### P{N}` subsection
- Each phase must have `**Files:**` with at least one path reference
- Each phase must have `**Tests:**` with at least one behavioral spec
- Dependency references must be valid (no `Depends on: P5` if P5 doesn't exist)

#### 1.3 Preserve backward compatibility

- Accept both `## Implementation Steps` (legacy) and `## Task Graph` (new) during transition
- Planner prompt instructs to emit `## Task Graph`; validator accepts either
- Remove `## Implementation Steps` acceptance after rollout is stable

---

### Phase 2: Behavioral Test Specs (Planner Prompt)

**Goal:** Planner emits concrete, testable behavioral specs — not prose suggestions.

**Files:** `src/planner.py`

#### 2.1 Update planner instructions

Add to the plan prompt:

```
Each phase in the Task Graph MUST include behavioral test specifications.
These describe WHAT the code should do, not HOW to test it.

Good test specs (behavioral):
- "Splitting a total across N recipients preserves the original total"
- "POST /orders with empty cart returns 400 with error 'cart_empty'"
- "Deleting a parent cascades to children"

Bad test specs (implementation-level):
- "Test the create_order function"
- "Add unit tests for the service layer"
- "Mock the database and verify calls"

Each spec should be falsifiable — an implementer reading only the spec
should know exactly what assertion to write.
```

#### 2.2 Update implementer instructions

Modify `AgentRunner` prompt to reference task graph phases:

```
Follow the Task Graph in the plan. For each phase (P1, P2, P3...):
1. Write tests that encode the behavioral specs listed for that phase
2. Run tests — they should FAIL (you haven't implemented yet)
3. Implement the minimum code to make tests pass
4. Run the full test suite before moving to the next phase

Do NOT skip ahead to later phases before earlier ones pass.
```

---

### Phase 3: Research Step for Complex Issues (New Runner)

**Goal:** For high-complexity issues, run a focused research step before planning
to improve plan quality.

**Files:** `src/researcher.py` (new), `src/plan_phase.py`, `src/models.py`, `src/config.py`

#### 3.1 Add `ResearchRunner`

A new read-only runner that:
- Accepts an issue and the codebase
- Dispatches parallel exploration (up to 3 areas)
- Produces a research artifact with:
  - Relevant files and their roles
  - Existing patterns to follow
  - Constraints and integration points
  - Confidence ratings (High / Medium / Low) per finding
- Posts research as a comment on the issue (collapsed `<details>` block)

#### 3.2 Integrate into plan phase

```python
# plan_phase.py — before planning
if triage_result.complexity_score >= config.research_complexity_threshold:
    research = await researcher.research(issue)
    # Append research artifact to planner context
    plan = await planner.plan(issue, research_context=research)
else:
    plan = await planner.plan(issue)
```

#### 3.3 Config additions

```python
# config.py
research_enabled: bool = True
research_complexity_threshold: int = 7  # 1-10 scale, triggers research above this
research_max_areas: int = 3             # parallel exploration breadth
```

#### 3.4 Research artifact format

```markdown
## Research: {issue title}

**Depth:** Standard | **Date:** 2026-03-13

### Codebase Analysis
| Area | Key Files | Pattern | Confidence |
|------|-----------|---------|------------|
| Auth | src/auth.py, src/middleware.py | Decorator-based | High |
| DB   | src/models.py, migrations/ | Alembic + SQLAlchemy | High |

### Integration Points
- Auth middleware wraps all /api routes (src/middleware.py:42)
- Tests use factory pattern (tests/factories.py)

### Constraints
- No direct DB queries outside repository layer
- All new routes need OpenAPI schema annotations

### Open Questions
- [ ] Does the existing rate limiter handle WebSocket connections?
```

---

### Phase 4: Agent Isolation — RED/GREEN/VALIDATE (Future)

**Goal:** Separate test-writing, implementation, and validation into distinct agents
to prevent the "marking your own homework" problem.

**Files:** `src/agent.py`, `src/implement_phase.py`, `src/base_runner.py`

> **Note:** This is the highest-impact but highest-effort change. Park for later
> and prototype only after Phases 1-3 are stable.

#### 4.1 Three-agent model

| Step | Agent | Allowed | Forbidden |
|------|-------|---------|-----------|
| RED | test-writer | Create/modify test files only | Touch src/ implementation files |
| GREEN | implementer | Create/modify src/ files only | Touch test files |
| VALIDATE | validator | Run commands, read files | Modify any file |

#### 4.2 Per-phase execution loop

For each phase in the task graph:

```
1. RED agent receives behavioral test specs → writes failing tests
2. Verify tests fail (if they pass, halt — feature already exists or test is tautological)
3. GREEN agent receives failing tests + phase context → implements
4. VALIDATE agent runs full suite, reports pass/fail
5. On failure: create remediation task, retry (max 2 attempts)
6. On success: mark phase complete, advance to next
```

#### 4.3 Implementation considerations

- Each agent runs in the same worktree (sequential, not parallel)
- File-path allowlists enforced via pre-commit hook or agent prompt constraints
- Validation agent is strictly read-only + command execution
- Remediation tasks feed back into the RED/GREEN loop
- Execution log appended per phase for debugging

#### 4.4 Fallback

If agent isolation causes too many remediation loops (>4 per phase),
fall back to single-agent mode for that phase with a warning logged.

---

## Rollout Order

```
Phase 1 (Plan Format)     ← Do first. Highest leverage, lowest risk.
  │                          Changes planner prompts + validation only.
  │                          Implementer benefits immediately from structure.
  ▼
Phase 2 (Test Specs)      ← Do with Phase 1. Same files, complementary.
  │                          Improves test quality without new infra.
  ▼
Phase 3 (Research Step)   ← Do after 1+2 are stable. New runner + config.
  │                          Improves plan quality for complex issues.
  ▼
Phase 4 (Agent Isolation) ← Do last. Significant rearchitecture.
                             Requires Phases 1-2 to be working well
                             since task graph structure is prerequisite.
```

## Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Plan validation pass rate (first attempt) | ~70% | >85% | Track in session logs |
| Implementation quality fix loops | ~2.1 avg | <1.5 avg | Count pre-quality retries |
| Test coverage of new code | Variable | >80% per PR | `make test-cov` on PR |
| HITL escalation rate | ~15% | <10% | Dashboard metrics |
| Epic child plan consistency | Manual gap review | Automated via task graph deps | Gap review iteration count |
