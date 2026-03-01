# Test Audit

Run a comprehensive test quality audit across the entire repo. Analyzes test naming, structure, factory usage, anti-patterns, coverage gaps, and flaky patterns. Creates GitHub issues for findings so HydraFlow can process them.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Run `echo "$HYDRAFLOW_LABEL_PLAN"` — if set, use it as the label for created issues. If empty, default to `hydraflow-plan`.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all test files: `**/test_*.py`, `**/tests/conftest.py`, `**/tests/helpers.py`
   - Exclude `.venv/`, `venv/`, `__pycache__/`, `node_modules/`
   - Also find all UI test files: `ui/src/**/*.test.jsx`, `ui/src/**/*.test.js`
   - Count total test files and identify the test helper infrastructure

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: Test naming & structure** — Checks naming conventions, 3As structure, single responsibility, and organization.
   - **Agent 2: Anti-patterns & flaky tests** — Detects over-mocking, weak assertions, flaky patterns, and test isolation issues.
   - **Agent 3: Factory/fixture gaps & coverage** — Finds missing factories, repeated setup, coverage gaps, and missing edge case tests.

4. Wait for all agents to complete.
5. After all finish, run `gh issue list --repo $REPO --label $LABEL --state open --search "test quality" --limit 200` to show the user a final summary of all issues created.

## Agent 1: Test Naming & Structure

```
You are a test quality auditor focused on naming and structure for the project at {repo_root}.

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

### Phase 4: Audit Single Responsibility
5. For each test, count assertions:
   - Flag tests with > 3 assertions testing **different** attributes (related assertions on the same result are OK)
   - Suggest splitting into focused tests
   - Note tests with zero assertions (test does nothing useful)

### Phase 5: Audit Test Organization
6. Check file-level organization:
   - Are test classes used to group related tests?
   - Are tests organized to mirror source file structure?
   - Are there test files > 500 lines that should be split?
   - Are there test files with < 3 tests (too granular)?

### Phase 6: Create GitHub Issues
7. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
8. Create GH issues for NEW findings only, grouped by theme:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Test Quality: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why this test quality issue matters>

## Findings
| Severity | File:Line | Test Name | Issue |
|----------|-----------|-----------|-------|
| <warning/suggestion> | <path:line> | <test_name> | <description> |

## Suggested Fixes
- [ ] <file:line> — Rename `test_init` to `test_<method>_<scenario>`
- [ ] <file:line> — Split test with 6 assertions into 3 focused tests
- [ ] <file:line> — Move setup into factory method

## Impact
- Tests affected: <N>
- Readability improvement: <description>
```

## Grouping Strategy
- "Test Quality: Improve test naming in <module>"
- "Test Quality: Fix 3As structure violations"
- "Test Quality: Split multi-assertion tests"
- "Test Quality: Reorganize large test files"

Focus on tests that are genuinely hard to understand or maintain. Skip minor naming quibbles.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 2: Anti-Patterns & Flaky Tests

```
You are a test quality auditor focused on anti-patterns and flakiness for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Read All Test Files
1. Use Glob to find all test files: tests/test_*.py, tests/conftest.py, tests/helpers.py
2. Read each file

### Phase 2: Detect Mocking Anti-Patterns
3. Find:
   - **Over-mocking**: Mocking private/internal methods (`patch.object(x, '_private_method')`) instead of testing behavior
   - **Excessive mock depth**: 4+ levels of nested `with patch(...)` blocks
   - **Incomplete mock setup**: MagicMock without return_value or side_effect where the return value matters
   - **Mock leakage**: Mocks applied at module level or class level that affect other tests
   - **Wrong patch target**: Patching the definition site instead of the import site
   For each finding, note: file, line, what's being mocked, and the better approach

### Phase 3: Detect Weak Assertions
4. Find:
   - **Always-true assertions**: `assert True`, `assert result` (only checks truthiness)
   - **Too generic**: `assert x is not None` when specific value should be checked
   - **Missing assertions**: Test functions with no assert statements at all
   - **Overly permissive**: `assert status in [200, 401, 403, 404, 500]`
   - **String containment only**: `assert "error" in str(result)` instead of checking specific error type/message

### Phase 4: Detect Flaky Patterns
5. Find:
   - **time.sleep()**: Sleeping in tests instead of async/mock timing
   - **Random without seed**: Non-deterministic test behavior
   - **Order dependency**: Tests that rely on other tests running first (shared state via class attributes)
   - **Real system calls**: Actual file I/O, network calls, subprocess without mocking
   - **Timestamp sensitivity**: Tests that compare exact timestamps (break across time zones or slow CI)
   - **Global state mutation**: Tests that modify module-level globals without cleanup

### Phase 5: Detect Isolation Issues
6. Find:
   - **Shared mutable fixtures**: Fixtures returning mutable objects shared across tests
   - **Missing cleanup**: Tests that create files/dirs without teardown
   - **Import side effects**: Test imports that trigger real initialization
   - **Class-level state**: Test classes with mutable class attributes

### Phase 6: Create GitHub Issues
7. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on the anti-pattern risk>

## Findings
| Severity | File:Line | Pattern | Risk |
|----------|-----------|---------|------|
| <critical/warning> | <path:line> | <description> | <what could go wrong> |

## Suggested Fixes
- [ ] <file:line> — Replace `patch.object(x, '_method')` with behavior test
- [ ] <file:line> — Add `assert result.status == 200` instead of `assert result`
- [ ] <file:line> — Replace `time.sleep(1)` with async await

## Impact
- Flaky test risk: <high/medium/low>
- False positive risk: <description>
```

## Grouping Strategy
- "Test Quality: Fix over-mocking in <module> tests"
- "Test Quality: Replace weak assertions with specific checks"
- "Test Quality: Fix flaky test patterns (sleep/random/order)"
- "Test Quality: Fix test isolation issues"

Prioritize by risk: flaky tests and false positives are more dangerous than style issues.

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

### Phase 3: Find Coverage Gaps
5. For each source module, check if corresponding tests exist:
   - Every public function/method should have at least one test
   - Every error path (except/raise) should have a test
   - Every branch (if/elif/else) should have at least one test per path
   - Every Pydantic model should have validation tests
6. Identify untested modules (source files with no corresponding test file)
7. Identify undertested modules (test file exists but < 50% of public functions tested)

### Phase 4: Find Missing Edge Case Tests
8. For each tested function, check if edge cases are covered:
   - Empty inputs (empty string, empty list, empty dict, None)
   - Boundary values (0, -1, MAX_INT, empty collection)
   - Error conditions (network failure, file not found, permission denied)
   - Concurrent access (if async code)
   - Large inputs (if the function processes collections)

### Phase 5: Audit Fixture Hygiene
9. Check:
   - Are fixtures scoped correctly? (session vs function vs module)
   - Are there fixtures in test files that should be in conftest.py?
   - Are there conftest fixtures that are only used by one test file?
   - Are there fixture chains that are too deep? (fixture depends on fixture depends on fixture)

### Phase 6: Create GitHub Issues
10. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on the test infrastructure gap>

## Missing Factories
| Object | Used In | Times Repeated | Suggested Factory |
|--------|---------|---------------|-------------------|
| <HydraFlowConfig(...)> | <test_a, test_b, test_c> | <5> | <make_config() in helpers.py> |

## Coverage Gaps
| Source File | Public Functions | Tested | Untested |
|-------------|-----------------|--------|----------|
| <module.py> | <10> | <6> | <fn_a, fn_b, fn_c, fn_d> |

## Suggested Fixes
- [ ] Add `make_<object>()` factory to helpers.py for <repeated pattern>
- [ ] Add tests for <untested_function> in <source_file>
- [ ] Add edge case tests for <function>: empty input, None, error path

## Factory Skeleton
```python
def make_<object>(**overrides):
    defaults = { ... }
    defaults.update(overrides)
    return <Object>(**defaults)
```
```

## Grouping Strategy
- "Test Quality: Add missing factories for <pattern>"
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
