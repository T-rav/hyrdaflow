# Integration Test Audit

Run a comprehensive integration test audit across the entire repo. Dynamically discovers external dependencies in source code, inventories existing integration tests, identifies coverage gaps, flags ugly/outdated tests, and creates GitHub issues for findings.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Run `echo "$HYDRAFLOW_LABEL_PLAN"` — if set, use it as the label for created issues. If empty, default to `hydraflow-plan`.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all `*.py` source files, excluding `.venv/`, `venv/`, `__pycache__/`, `node_modules/`, `dist/`, `build/`.
   - Separate into SOURCE files and TEST files (any file under a `tests/` or `test/` directory, or matching `test_*.py`).
   - Identify external dependencies by scanning source files for: subprocess calls, HTTP clients, database connections, message queues, file I/O, external CLI tools, API clients.

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: External dependency mapping & gap analysis** — Maps all external dependencies in source code, cross-references with existing integration tests.
   - **Agent 2: Test quality & anti-pattern detection** — Reviews existing tests for ugly patterns, false integration tests, and outdated code.
   - **Agent 3: Cross-module integration gaps** — Identifies integration points between modules and missing end-to-end test coverage.

4. Wait for all agents to complete.
5. After all finish, run `gh issue list --repo $REPO --label $LABEL --state open --search "integration test" --limit 200` to show the user a final summary of all issues created.

## Agent 1: External Dependency Mapping & Gap Analysis

```
You are an integration test auditor for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Map External Dependencies
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and catalog every external dependency:
   - **Subprocess calls**: asyncio.create_subprocess_exec, subprocess.run, os.system
   - **CLI tools**: git, gh, claude, docker, npm, make, or any other CLI invocations
   - **HTTP clients**: httpx, requests, aiohttp, urllib calls to external services
   - **Database**: SQLAlchemy, pymysql, psycopg2, sqlite3, Redis, Qdrant
   - **File I/O**: Reading/writing state files, config files, log files
   - **Message queues**: Celery, RabbitMQ, Kafka
   - **External APIs**: Any API client calls (OpenAI, Slack, GitHub API, etc.)
   For each dependency, note: file path, line number, method name, what it calls, error handling

### Phase 2: Inventory Existing Integration Tests
3. Read all test files. Catalog every test marked @pytest.mark.integration or that tests real external interactions
4. For each existing test, note: what external dependency it exercises, whether it uses real services or mocks

### Phase 3: Gap Analysis
5. Cross-reference Phase 1 dependencies against Phase 2 test coverage
6. Identify external interaction paths with ZERO integration test coverage
7. Identify tests that claim to be "integration" but are fully mocked

### Phase 4: Create GitHub Issues
8. For each finding, check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
9. Create GH issues for NEW findings only, grouped by theme:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Integration Test: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why this integration test matters>

## External Dependencies Not Covered
| Dependency | File:Line | Method | What It Calls |
|------------|-----------|--------|---------------|
| <name> | <path:line> | <method> | <endpoint/operation> |

## Suggested Test Scenarios
- [ ] <scenario 1>
- [ ] <scenario 2>

## Notes
- Priority: <high/medium/low based on blast radius>
```

## Grouping Strategy
Create ONE issue per theme, not one per missing test. Good themes:
- "Integration Test: subprocess/CLI tool interactions"
- "Integration Test: file I/O and state persistence"
- "Integration Test: HTTP/API client calls"
- "Integration Test: database/cache operations"

Be pragmatic: focus on high-blast-radius gaps. External API tests are expensive — note them but mark as low priority.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 2: Test Quality & Anti-Pattern Detection

```
You are a test quality auditor focused on integration test anti-patterns for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Read All Test Files
1. Use Glob to find all test files (test_*.py, *_test.py, conftest.py)
2. Read each file

### Phase 2: Detect Anti-Patterns
Flag these patterns:
- **"Always-pass" tests**: Tests that catch errors and still pass (defeating the purpose)
- **False integration tests**: Marked @pytest.mark.integration but fully mocked
- **Fixture duplication**: Same fixtures defined in multiple test files instead of conftest
- **Overly permissive assertions**: assert status in [200, 401, 403, 404, 500]
- **Dead tests**: @pytest.mark.skip or pytest.skip() with no plan to re-enable
- **Module-level hacks**: sys.modules or sys.path manipulation at import time
- **Hardcoded paths/URLs**: Service URLs or file paths hardcoded instead of parameterized
- **Real time.sleep()**: Sleeping in tests instead of using async/mock timing
- **Missing error path tests**: Only happy path tested for external interactions
- **Excessive mocking depth**: 4+ levels of nested `with patch(...)` blocks

### Phase 3: Create GitHub Issues
3. Check for duplicates, then create themed issues:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Integration Test: <anti-pattern theme>" --body "<details>"

Be pragmatic — only flag patterns that actually hurt test reliability or maintainability.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 3: Cross-Module Integration Gaps

```
You are an integration test auditor focused on cross-module interactions for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Map Module Boundaries
1. Read all source files and identify how modules interact:
   - Which modules call functions/classes from other modules?
   - What are the key data flows (e.g., CLI → orchestrator → agent → subprocess)?
   - What shared state exists (config, event bus, state tracker)?

### Phase 2: Identify Integration Seams
2. For each cross-module interaction, check:
   - Is there a test that exercises both modules together (not just mocked)?
   - Are error propagation paths tested across module boundaries?
   - Are configuration changes tested end-to-end?

### Phase 3: Infrastructure Gaps
3. Check for:
   - Missing `make test-integration` or equivalent target
   - Missing docker-compose.test.yml for isolated integration testing (if applicable)
   - Inconsistent test directory structure
   - Missing shared conftest fixtures for integration tests

### Phase 4: Create GitHub Issues
4. Check for duplicates, then create themed issues:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Integration Test: <theme>" --body "<details>"

Focus on the highest-value integration gaps — where module boundaries are most likely to break.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Important Notes
- Each agent should read files directly (no spawning sub-agents)
- Each agent should check `gh issue list` before creating any issue to avoid duplicates
- All issues should use the resolved `$REPO`, `$ASSIGNEE`, and `$LABEL`
- Group related findings into single themed issues — don't create one issue per missing test
- Title format: "Integration Test: <theme>" for consistency
- For confirmed bugs found during audit, use title format: "Bug: <description>"
- Be pragmatic: external API tests are expensive — note them but mark as low priority. Focus on subprocess calls, file I/O, and inter-module interactions as high priority.
