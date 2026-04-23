# Test Audit

Run a comprehensive test quality audit across the entire repo. Analyzes test naming, structure, hygiene, factory usage, fluent builder patterns, anti-patterns, coverage gaps, and flaky patterns. Creates GitHub issues for findings so HydraFlow can process them.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Use `hydraflow-find` as the label for created issues.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all test files: `**/test_*.py`, `**/tests/conftest.py`, `**/tests/helpers.py`
   - Exclude `.venv/`, `venv/`, `__pycache__/`, `node_modules/`
   - Also find all UI test files: `ui/src/**/*.test.jsx`, `ui/src/**/*.test.js`
   - Count total test files and identify the test helper infrastructure

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: Test naming, structure & method size** — Checks naming conventions, 3As structure, single responsibility, small test methods, and organization.
   - **Agent 2: Anti-patterns, hygiene & flaky tests** — Detects over-mocking, weak assertions, duplicate helpers, flaky patterns, and test isolation issues.
   - **Agent 3: Factory/fixture gaps, builder enforcement & coverage** — Finds missing factories, enforces fluent builder pattern, checks coverage gaps, and missing edge case tests.

4. Wait for all agents to complete.
5. After all finish, run `gh issue list --repo $REPO --label $LABEL --state open --search "test quality" --limit 200` to show the user a final summary of all issues created.

## Agent 1: Test Naming, Structure & Method Size

```
You are a test quality auditor focused on naming, structure, and method size for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Read All Test Files
1. Use Glob to find all test files: tests/test_*.py, ui/src/**/*.test.jsx
2. Read each test file

### Phase 2: Audit Test Naming
3. Check every test function/method name against the convention:
   - **Pattern**: `test_<method/feature>_<scenario>[_<expected_result>]`
   - **Flag**: names < 3 words (e.g., `test_init`, `test_run`)
   - **Flag**: generic names (test_1, test_something, test_basic)
   - **Flag**: redundant "test" in name (test_user_test)
   - **Flag**: names that don't describe what's being tested
   For each violation, note: file path, line number, current name, suggested better name

### Phase 3: Audit 3As Structure (Arrange-Act-Assert)
4. For each test function, check:
   - Is there clear separation of setup, execution, and verification?
   - Is all arrange code before the act?
   - Are all assertions after the act?
   - Are phases mixed? (e.g., assertions interleaved with setup)
   - Does setup dominate the test? (> 60% of lines are setup — push into factories/fixtures)

### Phase 4: Enforce Small Test Methods
5. For each test function, check:
   - **Max 20 lines of logic** (excluding blank lines, comments, docstrings) — long tests are doing too much
   - **Max 1 act step** — if there are multiple "act" calls, split into separate tests
   - **Max 3 assertions on different attributes** — related assertions on the same result are OK, but testing unrelated things means split the test
   - **Zero assertions** — test does nothing useful, delete or fix
   - **Excessive setup in test body** — if arrange is > 10 lines, extract into a factory/fixture/helper
6. For each violation, provide: the file:line, current line count, and a concrete suggestion (e.g., "extract lines 5-15 into a `make_configured_runner()` factory")

### Phase 5: Audit Test Organization
7. Check file-level organization:
   - Are test classes used to group related tests?
   - Are tests organized to mirror source file structure?
   - Are there test files > 500 lines that should be split?
   - Are there test files with < 3 tests (too granular)?

### Phase 6: Create GitHub Issues
8. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
9. Create GH issues for NEW findings only, grouped by theme:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Test Quality: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why this test quality issue matters>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Findings
| Severity | File:Line | Test Name | Issue |
|----------|-----------|-----------|-------|
| <warning/suggestion> | <path:line> | <test_name> | <description> |

## Suggested Fixes
- [ ] <file:line> — Rename `test_init` to `test_<method>_<scenario>`
- [ ] <file:line> — Split test with 6 assertions into 3 focused tests
- [ ] <file:line> — Extract 12-line setup into `make_<object>()` factory
- [ ] <file:line> — Test is 35 lines — extract arrange into fixture, split act steps

## Acceptance Criteria
- [ ] All test methods follow `test_<method>_<scenario>` naming convention
- [ ] No test method exceeds 20 lines of logic
- [ ] Each test has exactly one act step
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Tests affected: <N>
- Readability improvement: <description>
```

## Grouping Strategy
- "Test Quality: Improve test naming in <module>"
- "Test Quality: Fix 3As structure violations"
- "Test Quality: Split multi-assertion tests"
- "Test Quality: Break down oversized test methods"
- "Test Quality: Reorganize large test files"

**Thresholds:**
- Test method: max 20 lines of logic, max 1 act, max 3 unrelated assertions
- Arrange block: max 10 lines in test body (rest goes to factories/fixtures)
- Test file: max 500 lines

Focus on tests that are genuinely hard to understand or maintain. Skip minor naming quibbles.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 2: Anti-Patterns, Hygiene & Flaky Tests

```
You are a test quality auditor focused on anti-patterns, hygiene, and flakiness for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Read All Test Files
1. Use Glob to find all test files: tests/test_*.py, tests/conftest.py, tests/helpers.py
2. Read each file

### Phase 2: Detect Duplicate Helpers & DRY Violations
3. This is a HIGH PRIORITY check. Find:
   - **Duplicate helper functions**: Same or near-identical helper function defined in multiple test files (e.g., `make_config()` in test_a.py AND test_b.py)
   - **Duplicate fixture definitions**: Same fixture defined in multiple conftest.py files or test files instead of a shared conftest
   - **Copy-pasted setup blocks**: Identical arrange code (5+ lines) repeated across tests in different files
   - **Inconsistent helper naming**: Same factory/helper with different names across files (e.g., `create_runner()` vs `make_runner()` vs `build_runner()`)
   - **Helpers that should be in helpers.py**: Helper functions defined inline in test files that are used by 2+ files
4. For each finding: list ALL locations of the duplicate, and suggest where the canonical version should live (helpers.py, conftest.py, or a new shared module)

### Phase 3: Detect Mocking Anti-Patterns
5. Find:
   - **Over-mocking**: Mocking private/internal methods (`patch.object(x, '_private_method')`) instead of testing behavior
   - **Excessive mock depth**: 4+ levels of nested `with patch(...)` blocks
   - **Incomplete mock setup**: MagicMock without return_value or side_effect where the return value matters
   - **Mock leakage**: Mocks applied at module level or class level that affect other tests
   - **Wrong patch target**: Patching the definition site instead of the import site
   For each finding, note: file, line, what's being mocked, and the better approach

### Phase 4: Detect Weak Assertions
6. Find:
   - **Always-true assertions**: `assert True`, `assert result` (only checks truthiness)
   - **Too generic**: `assert x is not None` when specific value should be checked
   - **Missing assertions**: Test functions with no assert statements at all
   - **Overly permissive**: `assert status in [200, 401, 403, 404, 500]`
   - **String containment only**: `assert "error" in str(result)` instead of checking specific error type/message

### Phase 5: Detect Flaky Patterns & Hygiene Issues
7. Find:
   - **time.sleep()**: Sleeping in tests instead of async/mock timing
   - **Random without seed**: Non-deterministic test behavior
   - **Order dependency**: Tests that rely on other tests running first (shared state via class attributes)
   - **Real system calls**: Actual file I/O, network calls, subprocess without mocking
   - **Timestamp sensitivity**: Tests that compare exact timestamps (break across time zones or slow CI)
   - **Global state mutation**: Tests that modify module-level globals without cleanup
   - **Missing cleanup/teardown**: Tests that create temp files, directories, or state without cleaning up (no `tmp_path`, no `teardown`, no context manager)
   - **Leaked state between tests**: Mutable class-level attributes, module-level caches modified without reset
   - **Import side effects**: Test imports that trigger real initialization (database connections, file creation)

### Phase 6: Detect Isolation Issues
8. Find:
   - **Shared mutable fixtures**: Fixtures returning mutable objects shared across tests
   - **Missing cleanup**: Tests that create files/dirs without teardown
   - **Import side effects**: Test imports that trigger real initialization
   - **Class-level state**: Test classes with mutable class attributes

### Phase 7: Create GitHub Issues
9. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on the anti-pattern risk>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Duplicate Helpers (if found)
| Helper | Location 1 | Location 2 | Suggested Home |
|--------|-----------|-----------|----------------|
| <name> | <file:line> | <file:line> | <helpers.py / conftest.py> |

## Anti-Patterns
| Severity | File:Line | Pattern | Risk |
|----------|-----------|---------|------|
| <critical/warning> | <path:line> | <description> | <what could go wrong> |

## Hygiene Issues
| File:Line | Issue | Fix |
|-----------|-------|-----|
| <path:line> | <missing cleanup / leaked state / etc.> | <specific fix> |

## Suggested Fixes
- [ ] <file:line> — Move `make_config()` to helpers.py (duplicated in 3 files)
- [ ] <file:line> — Replace `patch.object(x, '_method')` with behavior test
- [ ] <file:line> — Add cleanup for temp directory created at line N
- [ ] <file:line> — Replace `time.sleep(1)` with async await

## Acceptance Criteria
- [ ] Duplicate helpers are consolidated into a single shared location
- [ ] No over-mocking of private methods remains
- [ ] All tests have proper cleanup/teardown for resources
- [ ] No flaky patterns (sleep, random without seed, order dependency)
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Flaky test risk: <high/medium/low>
- DRY violations: <N duplicate helpers across M files>
- False positive risk: <description>
```

## Grouping Strategy
- "Test Quality: Deduplicate test helpers across files"
- "Test Quality: Fix over-mocking in <module> tests"
- "Test Quality: Replace weak assertions with specific checks"
- "Test Quality: Fix flaky test patterns (sleep/random/order)"
- "Test Quality: Fix test isolation and cleanup issues"

Prioritize by risk: duplicate helpers and flaky tests are the most dangerous — they cause confusion during multi-file refactors and false CI signals.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 3: Factory/Fixture Gaps & Coverage

```
You are a test quality auditor focused on test infrastructure and coverage gaps for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Inventory Test Infrastructure
1. Read tests/helpers.py and tests/conftest.py to catalog:
   - All existing factory functions/classes
   - All existing fixtures
   - All existing builder patterns
   - Helper utilities (make_config, make_state, etc.)
2. Note what each factory/fixture creates and how it's used

### Phase 2: Find Missing Factories
3. For each test file, identify repeated object creation:
   - Same constructor call with similar args in 3+ tests → needs factory
   - Same mock setup repeated in 3+ tests → needs mock factory
   - Same dict/config construction in 3+ tests → needs builder
   - Complex arrange blocks (> 10 lines of setup) that could be a one-liner with a factory
4. Cross-reference with existing helpers.py — is the factory already there but not used?

### Phase 3: Enforce Fluent Builder Pattern
5. For each existing factory and builder in helpers.py/conftest.py, check:
   - **Fluent API required**: Builders for objects with 3+ optional fields MUST use fluent `.with_<field>()` chaining syntax, NOT `**kwargs` dicts
   - **Pattern**: `BuilderClass().with_x(val).with_y(val).build()` — each `.with_*()` returns `self`, `.build()` returns the constructed object
   - **Flag**: Factory functions using `**overrides` dict pattern for objects with 3+ configurable fields — these should be converted to fluent builders
   - **Flag**: Builders that exist but don't return `self` from setter methods (broken chain)
   - **Flag**: Builders missing a `.build()` terminal method
   - **Flag**: Builders with inconsistent method naming (mixing `.set_x()`, `.with_x()`, `.x()` styles — standardize on `.with_x()`)
   - **Flag**: Test files that construct complex objects inline instead of using an available builder
6. For each finding, provide: file:line, current pattern, and a concrete builder skeleton:
   ```python
   class <Object>Builder:
       def __init__(self):
           self._field = <default>
       def with_<field>(self, value) -> "<Object>Builder":
           self._field = value
           return self
       def build(self) -> <Object>:
           return <Object>(field=self._field)
   ```
7. Check that tests USE the fluent syntax for readability:
   - **Good**: `ConfigBuilder().with_repo("owner/repo").with_dry_run(True).build()`
   - **Bad**: `make_config(repo="owner/repo", dry_run=True)` (when builder exists)
   - **Bad**: `ConfigBuilder().build()` with manual attribute assignment after

### Phase 4: Find Coverage Gaps
8. For each source module, check if corresponding tests exist:
   - Every public function/method should have at least one test
   - Every error path (except/raise) should have a test
   - Every branch (if/elif/else) should have at least one test per path
   - Every Pydantic model should have validation tests
9. Identify untested modules (source files with no corresponding test file)
10. Identify undertested modules (test file exists but < 50% of public functions tested)

### Phase 5: Find Missing Edge Case Tests
11. For each tested function, check if edge cases are covered:
   - Empty inputs (empty string, empty list, empty dict, None)
   - Boundary values (0, -1, MAX_INT, empty collection)
   - Error conditions (network failure, file not found, permission denied)
   - Concurrent access (if async code)
   - Large inputs (if the function processes collections)

### Phase 6: Audit Fixture Hygiene
12. Check:
   - Are fixtures scoped correctly? (session vs function vs module)
   - Are there fixtures in test files that should be in conftest.py?
   - Are there conftest fixtures that are only used by one test file?
   - Are there fixture chains that are too deep? (fixture depends on fixture depends on fixture)
   - Are fixtures doing too much? (> 15 lines — split into factory + fixture wrapper)

### Phase 7: Create GitHub Issues
13. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on the test infrastructure gap>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Missing Factories
| Object | Used In | Times Repeated | Suggested Factory |
|--------|---------|---------------|-------------------|
| <HydraFlowConfig(...)> | <test_a, test_b, test_c> | <5> | <make_config() in helpers.py> |

## Builder Pattern Violations
| File:Line | Current Pattern | Issue | Suggested Fix |
|-----------|----------------|-------|---------------|
| <path:line> | `make_config(**overrides)` | kwargs factory with 5+ fields | Convert to `ConfigBuilder().with_x().build()` |
| <path:line> | `FooBuilder().set_x()` | Inconsistent naming | Rename to `.with_x()` |

## Coverage Gaps
| Source File | Public Functions | Tested | Untested |
|-------------|-----------------|--------|----------|
| <module.py> | <10> | <6> | <fn_a, fn_b, fn_c, fn_d> |

## Suggested Fixes
- [ ] Add `make_<object>()` factory to helpers.py for <repeated pattern>
- [ ] Convert `make_<object>(**overrides)` to fluent `<Object>Builder` class
- [ ] Add tests for <untested_function> in <source_file>
- [ ] Add edge case tests for <function>: empty input, None, error path

## Acceptance Criteria
- [ ] Repeated object construction patterns use shared factories
- [ ] Factories with 3+ optional fields use fluent builder pattern
- [ ] All identified coverage gaps have corresponding tests
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Builder Skeleton
```python
class <Object>Builder:
    def __init__(self):
        self._field_a = <default>
        self._field_b = <default>

    def with_<field_a>(self, value: <type>) -> "<Object>Builder":
        self._field_a = value
        return self

    def with_<field_b>(self, value: <type>) -> "<Object>Builder":
        self._field_b = value
        return self

    def build(self) -> <Object>:
        return <Object>(field_a=self._field_a, field_b=self._field_b)
```
```

## Grouping Strategy
- "Test Quality: Add missing factories for <pattern>"
- "Test Quality: Convert kwargs factories to fluent builders"
- "Test Quality: Fix builder pattern violations"
- "Test Quality: Add tests for untested functions in <module>"
- "Test Quality: Add edge case tests for <module>"
- "Test Quality: Clean up fixture organization"

Focus on high-value gaps: untested error paths in critical modules, repeated setup that slows test writing.
Skip trivial getters/setters and private helper functions.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Important Notes
- Each agent should read files directly (no spawning sub-agents)
- Each agent should check `gh issue list` before creating any issue to avoid duplicates
- All issues should use the resolved `$REPO`, `$ASSIGNEE`, and `$LABEL`
- Group related findings into single themed issues — don't create one issue per test
- Title format: "Test Quality: <theme>" for consistency
- Be pragmatic: focus on issues that genuinely hurt test reliability, not style preferences
- Don't duplicate what ruff/pyright already catch — focus on semantic test quality issues
- Skip the test-audit agent type — use general-purpose agents that can create GitHub issues
