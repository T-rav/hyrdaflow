# Code Quality Audit

Run a comprehensive code quality audit across the entire repo. Dynamically analyzes source code for dead code, complexity, duplication, error handling gaps, type safety issues, class cohesion, and method size. Creates GitHub issues for findings so HydraFlow can process them.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Use `hydraflow-find` as the label for created issues.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all `*.py` source files, excluding `.venv/`, `venv/`, `__pycache__/`, `node_modules/`, `dist/`, `build/`.
   - Separate into SOURCE files (production code) and TEST files (anything under `tests/` or matching `test_*.py`).
   - Count total source files, total lines, and identify the main modules.

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: Dead code & unused exports** — Finds unreachable code, unused functions, unused imports, and stale modules.
   - **Agent 2: Method size, class cohesion & duplication** — Enforces small methods, single-concept classes, and DRY.
   - **Agent 3: Error handling & robustness** — Finds bare excepts, swallowed errors, missing error paths, and fragile patterns.
   - **Agent 4: Type safety & API consistency** — Finds missing type annotations, `Any` overuse, inconsistent return types, and public API gaps.
   - **Agent 5: Convention drift & over-engineering** — Reads `docs/agents/avoided-patterns.md` (or CLAUDE.md fallback) at runtime and sweeps the codebase for documented avoided patterns plus over-engineering accumulation.

4. Wait for all agents to complete.
5. After all finish, run `gh issue list --repo $REPO --label $LABEL --state open --search "code quality" --limit 200` to show the user a final summary of all issues created.

## Agent 1: Dead Code & Unused Exports

```
You are a code quality auditor focused on dead code detection for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Map All Definitions
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and catalog every:
   - Function/method definition (def, async def)
   - Class definition
   - Module-level constant
   - Import statement

### Phase 2: Cross-Reference Usage
3. For each definition, search the codebase for references:
   - Is the function/class actually called or imported elsewhere?
   - Is the constant referenced outside its definition file?
   - Are there imports that are never used?
   - Are there entire modules that nothing imports from?
4. Check __init__.py re-exports — are re-exported names actually used by consumers?
5. Check for functions only called by other dead functions (transitive dead code)

### Phase 3: Detect Stale Patterns
6. Look for:
   - **Commented-out code blocks** (> 3 lines of commented code)
   - **TODO/FIXME/HACK comments** older than the surrounding code's last edit
   - **Unused class methods** (defined but never called, including by tests)
   - **Unreachable code** after unconditional return/raise/break
   - **Empty function bodies** (just `pass` or `...`) that aren't abstract methods
   - **Duplicate function signatures** (same name defined in multiple places)

### Phase 4: Create GitHub Issues
7. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
8. Create GH issues for NEW findings only, grouped by theme:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Code Quality: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why this cleanup matters>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Dead Code Found
| Type | File:Line | Name | Reason |
|------|-----------|------|--------|
| <function/class/import> | <path:line> | <name> | <never called/never imported/unreachable> |

## Suggested Actions
- [ ] Remove <item> — unused since <reason>
- [ ] Remove <item> — only referenced by other dead code

## Acceptance Criteria
- [ ] All identified dead code items are removed
- [ ] No remaining references to removed symbols
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Lines removable: ~<N>
- Files affected: <N>
- Risk: <low — dead code removal>
```

## Grouping Strategy
Create ONE issue per theme, not one per dead function. Good themes:
- "Code Quality: Remove unused utility functions"
- "Code Quality: Clean up stale imports across modules"
- "Code Quality: Remove commented-out code blocks"
- "Code Quality: Remove empty/stub functions"

Be pragmatic: exclude protocol/ABC methods, __dunder__ methods, and test helpers.
Verify a function is truly unused before flagging — check tests too, as test-only helpers are valid.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 2: Method Size, Class Cohesion & Duplication

```
You are a code quality auditor focused on method size, class cohesion, and duplication for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Enforce Small Methods
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and flag methods/functions that violate these thresholds:
   - **Long methods**: > 50 lines of logic (excluding docstring, blank lines, comments)
   - **Deep nesting**: > 3 levels of indentation (nested if/for/try/with)
   - **High branch count**: > 5 if/elif/else branches in a single function
   - **Too many parameters**: > 5 parameters (excluding self/cls)
   - **Mixed concerns**: Method does unrelated things (e.g., I/O + business logic + formatting in the same method)
   - **Long method chains**: Methods that call 3+ other methods sequentially — should be composed at a higher level
3. For each finding, note: file path, line number, function name, metric value, and a concrete suggestion to decompose it (e.g., "extract lines 45-62 into a `_parse_response()` helper")

### Phase 2: Enforce Single Concept Per Class
4. For each class, check:
   - **Too many public methods**: > 7 public methods suggests the class does too much — split by responsibility
   - **Too many total methods**: > 12 methods (public + private) indicates the class is a kitchen sink
   - **Low cohesion**: Methods that don't share instance attributes — they access disjoint sets of `self.*` fields, meaning they belong in separate classes
   - **God classes**: Classes > 200 lines — almost always doing too much
   - **Mixed abstraction levels**: Class mixes high-level orchestration with low-level detail (e.g., a class that both manages workflow AND parses JSON)
   - **Too many instance variables**: > 8 instance variables set in `__init__` suggests the class holds too many concerns
   - **Feature envy**: Methods that primarily operate on data from another class rather than their own state
5. For each class violation, suggest a concrete decomposition:
   - Which methods group together by shared state?
   - What would the extracted class be named?
   - What interface would the original class use to delegate?

### Phase 3: Detect Code Duplication
6. Find duplicated logic patterns:
   - **Copy-paste blocks**: 5+ consecutive lines that appear nearly identical in 2+ locations
   - **Similar functions**: Functions with same structure but different variable names
   - **Repeated patterns**: Same sequence of API calls, error handling, or data transformation in 3+ places
   - **Inline constants**: Same magic number or string literal used in 3+ places without a named constant
7. For each duplication, identify: both locations, what differs, and how to extract a shared abstraction

### Phase 4: DRY Violations & Abstraction Opportunities
8. Look for:
   - **Missing helper functions**: Same 3+ line pattern repeated across files
   - **Missing base classes**: Multiple classes with identical method implementations
   - **Missing constants**: Repeated string literals or numbers that should be named
   - **Config duplication**: Same default values hardcoded in multiple places instead of referencing config
   - **Parallel implementations**: Two different ways of doing the same thing (e.g., two JSON serializers)

### Phase 5: Create GitHub Issues
9. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
10. Create GH issues for NEW findings only:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Code Quality: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why small methods and focused classes matter here>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Long Methods
| File:Line | Method | Lines | Issue |
|-----------|--------|-------|-------|
| <path:line> | <name> | <N> | <why it's too long — what to extract> |

## Oversized / Unfocused Classes
| File:Line | Class | Methods | Lines | Issue |
|-----------|-------|---------|-------|-------|
| <path:line> | <name> | <N> | <N> | <what responsibilities to split> |

## Duplication
| Pattern | Location 1 | Location 2 | Lines |
|---------|-----------|-----------|-------|
| <what's duplicated> | <path:line> | <path:line> | <N> |

## Suggested Refactoring
- [ ] Extract `<helper>()` from `<long_method>` (lines X-Y handle <concern>)
- [ ] Split `<GodClass>` into `<ClassA>` (methods a,b,c) + `<ClassB>` (methods d,e,f)
- [ ] Replace magic value `<value>` with named constant
- [ ] Deduplicate <pattern> into shared `<helper>()`

## Acceptance Criteria
- [ ] No method exceeds 50 lines of logic
- [ ] No class exceeds 200 lines or 7 public methods
- [ ] Duplicated patterns are extracted into shared helpers
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Code Example (Before/After)
<Show a concrete before/after for the highest-impact item>
```

## Grouping Strategy
- "Code Quality: Break down long methods in <module>"
- "Code Quality: Split <ClassName> — too many responsibilities"
- "Code Quality: Extract shared patterns into helpers"
- "Code Quality: Replace magic constants with named values"
- "Code Quality: Deduplicate <pattern> across modules"

**Thresholds summary:**
- Method: max 50 lines of logic, max 3 nesting levels, max 5 params, max 5 branches
- Class: max 7 public methods, max 12 total methods, max 200 lines, max 8 instance vars
- Duplication: flag 5+ identical lines in 2+ places, or 3+ line patterns in 3+ places

Focus on high-impact items: methods > 80 lines, classes > 300 lines, 3+ duplicated blocks.
Skip trivial duplication (< 3 lines), simple data classes, and config/model classes that are legitimately wide.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 3: Error Handling & Robustness

```
You are a code quality auditor focused on error handling and robustness for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Audit Exception Handling
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and find:
   - **Bare except**: `except:` or `except Exception:` that catches too broadly
   - **Swallowed exceptions**: `except: pass` or `except Exception: pass` — errors silently ignored
   - **Missing error context**: `raise` without chaining (`raise X from e`)
   - **Inconsistent error types**: Same error condition raises different exception types across modules
   - **Missing try/except**: External calls (subprocess, HTTP, file I/O) without error handling
   - **Overly broad try blocks**: try block wraps 20+ lines instead of just the risky operation

### Phase 2: Audit Subprocess & External Calls
3. Find all subprocess calls and external tool invocations:
   - Do they check return codes? (`check=True` or manual returncode check)
   - Do they have timeouts? (subprocess.run without timeout, asyncio without timeout)
   - Do they handle stderr?
   - Do they handle the tool not being installed? (FileNotFoundError)
4. Find all HTTP/API client calls:
   - Do they handle connection errors, timeouts, non-2xx responses?
   - Do they retry on transient failures?
   - Do they have reasonable timeouts?

### Phase 3: Audit Resource Management
5. Look for:
   - **Missing context managers**: File open() without `with`, connections without cleanup
   - **Missing finally blocks**: Resources acquired in try without finally/context manager
   - **Async resource leaks**: aiohttp sessions, asyncio tasks not awaited or cancelled
   - **Temp file cleanup**: tempfile usage without cleanup on error paths

### Phase 4: Audit Edge Cases
6. Look for:
   - **Missing None checks**: Accessing attributes on potentially-None values without guards
   - **Missing empty collection checks**: Indexing into lists/dicts that might be empty
   - **Race conditions**: Shared mutable state in async code without locks
   - **Integer overflow/underflow**: Counters that could wrap or go negative
   - **Path traversal**: User-influenced file paths without sanitization

### Phase 5: Create GitHub Issues
7. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on the robustness risk>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Findings
| Severity | File:Line | Issue | Risk |
|----------|-----------|-------|------|
| <high/medium/low> | <path:line> | <description> | <what could go wrong> |

## Suggested Fixes
- [ ] <file:line> — Add error handling for <operation>
- [ ] <file:line> — Replace bare except with specific exception type
- [ ] <file:line> — Add timeout to subprocess call

## Acceptance Criteria
- [ ] All bare/broad excepts are replaced with specific exception types
- [ ] All subprocess/external calls have timeouts and error handling
- [ ] Resource management uses context managers or proper cleanup
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Blast radius: <what breaks if this isn't fixed>
- Frequency: <how often this code path runs>
```

## Grouping Strategy
- "Code Quality: Fix bare/swallowed exceptions in <module>"
- "Code Quality: Add timeouts to subprocess calls"
- "Code Quality: Add error handling for external API calls"
- "Code Quality: Fix resource leaks in async code"

Focus on production code paths that run frequently. Skip test code and one-off scripts.
Prioritize by blast radius — errors in the orchestrator or review loop matter more than CLI parsing.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 4: Type Safety & API Consistency

```
You are a code quality auditor focused on type safety and API consistency for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Audit Type Annotations
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and find:
   - **Missing return types**: Public functions/methods without `-> ReturnType`
   - **Missing parameter types**: Public function parameters without type annotations
   - **`Any` overuse**: Functions typed as `-> Any` or parameters as `param: Any` when a more specific type is available
   - **Incorrect Optional**: Parameters that can be None but aren't typed `X | None`
   - **Dict/List without generics**: `dict` instead of `dict[str, int]`, `list` instead of `list[str]`
   - **Inconsistent None handling**: Function returns None in some paths but return type doesn't include None

### Phase 2: Audit Pydantic Models
3. Check all Pydantic models (BaseModel subclasses):
   - **Missing validators**: Fields that should have validation (e.g., URL fields, email, ranges)
   - **Loose types**: Fields typed as `str` that should be enums or Literal types
   - **Missing field descriptions**: Fields without `Field(description=...)`
   - **Inconsistent defaults**: Similar fields across models with different defaults
   - **Missing model_config**: Models without `model_config` for JSON serialization settings

### Phase 3: Audit Public API Consistency
4. Check function signatures across modules for consistency:
   - **Inconsistent parameter ordering**: Similar functions with parameters in different order
   - **Inconsistent naming**: Same concept called different names across modules (e.g., `issue_num` vs `issue_number` vs `issue_id`)
   - **Inconsistent return types**: Similar operations returning different shapes
   - **Missing docstrings**: Public functions/classes without docstrings
   - **Stale docstrings**: Docstrings that don't match the current signature

### Phase 4: Audit Configuration Consistency
5. Check config.py and its consumers:
   - Are all config fields actually used somewhere?
   - Are there hardcoded values that should come from config?
   - Are environment variable names consistent with field names?
   - Are CLI arguments consistent with config field names?

### Phase 5: Create GitHub Issues
6. Check for duplicate GH issues first, then create themed issues

## Issue Body Format
```markdown
## Context
<1-2 sentences on why type safety/consistency matters here>

**Type:** chore

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Findings
| Issue | File:Line | Current | Suggested |
|-------|-----------|---------|-----------|
| <missing type/Any overuse/inconsistent name> | <path:line> | <current state> | <what it should be> |

## Suggested Fixes
- [ ] <file:line> — Add return type annotation `-> X`
- [ ] <file:line> — Replace `Any` with `SpecificType`
- [ ] <file:line> — Rename `issue_num` to `issue_number` for consistency

## Acceptance Criteria
- [ ] All public functions have complete type annotations
- [ ] No unnecessary `Any` types remain
- [ ] Parameter naming is consistent across modules
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Impact
- Type checker improvements: <N> new errors caught
- API consistency: <description of improvement>
```

## Grouping Strategy
- "Code Quality: Add missing type annotations in <module>"
- "Code Quality: Replace Any with specific types"
- "Code Quality: Standardize parameter naming across modules"
- "Code Quality: Add Pydantic field validators for <model>"
- "Code Quality: Remove unused config fields"

Focus on public APIs and cross-module interfaces. Skip internal helper functions and test code.
Prioritize by impact — type gaps in widely-used functions matter more than leaf functions.

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Agent 5: Convention Drift & Over-Engineering

```
You are a code quality auditor focused on convention drift and over-engineering for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Load project conventions
1. Read `docs/agents/avoided-patterns.md`. If that file does not exist, fall back to the "Avoided Patterns" section of `CLAUDE.md`.
2. Parse out each documented avoided pattern — title + description + (when provided) detection heuristic.
3. Cache each pattern as a `(id, description, detection_strategy)` triple for the sweep below.

### Phase 2: Sweep for documented avoided patterns
For each pattern from Phase 1, scan the codebase for violations. Current known patterns (keep in sync with the doc — do not hardcode, read them at runtime):

- **Pydantic field additions without test updates**: Use `git log --since=90.days src/models.py` to list recent commits touching models. For each, check whether `tests/test_models.py` or `tests/test_smoke.py` was updated in the same commit via `git show --stat <sha>`. Flag commits where a field addition landed without a matching test update.
- **Top-level imports of optional dependencies in test files**: Grep `tests/` for `^from (hindsight|httpx) import` and `^import (hindsight|httpx)` (i.e., at column 0, module-level). Each match is a violation.
- **Background sleep loops polling for results**: Grep non-test source code for `time.sleep(` or `asyncio.sleep(` inside `while` or `for` loops. Exclude retry loops with explicit max attempts.
- **Mocking at the wrong level**: Grep tests for `@patch("<module>.<name>")` where `<module>` is the definition module of `<name>`. Legitimate patches target the import site. Heuristic: if a patched target is the file where the function is `def`-ined, that's a likely smell.
- **Falsy checks on optional objects**: Grep source for `if not self\._\w+` then check whether the attribute is typed `X | None` in the class `__init__`. Flag each occurrence.
- **Underscore-prefixed names imported across modules**: Run `rg -n "from [a-z_]+ import[^#]*\b_[a-zA-Z]" src/ tests/` to find imports whose symbol list includes a `_`-prefixed name. Each hit is a candidate — the importer is consuming a private-by-convention name. The fix is to promote the source symbol to public (drop the underscore); `# noqa: PLC0415` suppressions are acceptable only for genuinely deferred imports, not for crossing the private boundary.
- **Test helpers duplicating conftest fixtures**: Extract the list of helper names from `tests/conftest.py` (`rg -oN "^def (\w+)" tests/conftest.py`) and grep each test file for a local `def <same-name>(` or `def _<same-name>(`. Flag candidates where a test file re-implements a helper that already exists centrally — these drift silently.
- **`logger.error(value)` without a format string**: Grep for `rg -n "logger\.(error|warning|info|debug)\(\w+\)" src/` — every match should have a string literal (starting with `"` or `'`) as the first argument. A bare variable means the variable is treated as the format string, which is a latent TypeError when it contains `%s`, `%d`, or `{...}`.
- **Hardcoded path lists mirroring filesystem state**: Grep source for tuple/list literals of paths sharing a parent directory (e.g., `_DOCKER_PLUGIN_DIRS = ("/opt/plugins/a", "/opt/plugins/b", ...)`). Flag candidates where a runtime scan of the parent directory would eliminate the need for the literal. Cross-check Dockerfile / compose files to see if the paths are mirrored there too.
- **`_name` for unused loop variables**: Grep `rg -n "for _[a-z]" src/ tests/`. For each match, verify the underscore-prefixed name is actually unused in the loop body (by scope search). If unused, flag — Python idiom is bare `_` for throwaways, and pyright's `reportUnusedVariable` fires on `_name` even though the prefix signals intent.

### Phase 3: Sweep for over-engineering patterns
- **Single-use helpers**: Functions defined once and called from exactly one non-test site. Inline candidates. (Use grep to count call sites; exclude dunder methods, protocol implementations, and CLI entry points.)
- **Speculative abstractions**: Base classes with a single concrete subclass; Protocols with a single implementer; factories that return one type; dataclasses with one field. These are all candidates for inlining.
- **Defensive handling of impossible cases**: `if x is None: raise` where the preceding code path always populates `x`. Trace the control flow; if nothing can set `x` to None, flag the guard.
- **Backwards-compat shims**: Comments matching `# (kept|retained).*compat`, `# deprecated`, or `# backwards.compat`. Unused `_`-prefixed variables retained "for compat". Deprecated argument handlers with no remaining callers.
- **Feature-flag rot**: Config flags that are never toggled in production — grep the flag name, find no `False`/`True` overrides in `settings`, CI, or deploy config. Flag if the flag has only ever had its default value.
- **Test-only code paths in production**: `if os.getenv("TESTING")` or similar branches in `src/`. These should be in test fixtures, not production code.

### Phase 4: Create GitHub issues
1. Check for duplicate GH issues first:
   `gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"`
2. Create GH issues for NEW findings only, grouped by theme:
   `gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Code Quality: Convention drift — <theme>" --body "<details>"`

## Issue Body Format

```markdown
## Context
<1-2 sentences on the drift or over-engineering pattern and why it matters>

**Type:** chore
**Source:** Agent 5 (convention drift & over-engineering)

## Scope
- Files: <list affected files>
- Risk: <low/medium — describe>

## Findings
| Pattern | File:Line | Details |
|---------|-----------|---------|
| <pattern id from avoided-patterns.md or over-engineering category> | <path:line> | <what was found and why it violates> |

## Suggested Fixes
- [ ] <file:line> — <specific remediation>

## Acceptance Criteria
- [ ] All listed violations are remediated
- [ ] `docs/agents/avoided-patterns.md` is updated if a new pattern is discovered
- [ ] All existing tests pass (`make test`)
- [ ] No new lint or type errors (`make quality-lite`)

## Reference
See `docs/agents/avoided-patterns.md` for the canonical rule descriptions.
```

## Grouping Strategy
- "Code Quality: Convention drift — Pydantic field additions missing test updates"
- "Code Quality: Convention drift — Top-level optional-dep imports in tests"
- "Code Quality: Over-engineering — Single-use helpers to inline"
- "Code Quality: Over-engineering — Stale feature flags"
- "Code Quality: Over-engineering — Backwards-compat shims to remove"

## Severity guidance
- **high**: convention violations that cause real test failures or hidden bugs (e.g., Pydantic field additions without test updates, wrong-level mocks masking broken code paths)
- **medium**: over-engineering accumulation (single-use helpers, speculative abstractions, stale feature flags, backwards-compat shims)
- **low**: cosmetic drift (old comments, unused `_`-vars)

Only `high` and `medium` findings are filed as issues by the grooming loop — `low` findings are logged for trend analysis but not turned into work.

## Keep-in-sync principle
This agent reads `docs/agents/avoided-patterns.md` at runtime. Adding a new avoided pattern to that doc automatically adds it to the next sweep — no code change needed here. If you find yourself hardcoding a new pattern in this prompt, STOP and add it to the doc instead.

Emit findings as JSON objects (one per theme) matching the schema parsed by `src/code_grooming_loop.py::_FINDING_RE`:
  `{"id": "<stable hash>", "severity": "high|medium|low", "title": "...", "description": "<markdown>"}`

Return a summary of all findings grouped by category, with GH issue URLs created.
```

## Important Notes
- Each agent should read files directly (no spawning sub-agents)
- Each agent should check `gh issue list` before creating any issue to avoid duplicates
- All issues should use the resolved `$REPO`, `$ASSIGNEE`, and `$LABEL`
- Group related findings into single themed issues — don't create one issue per finding
- Title format: "Code Quality: <theme>" for consistency
- Be pragmatic: focus on high-impact items that meaningfully improve code quality
- Skip nitpicks, style preferences, and issues already caught by ruff/pyright
- Don't duplicate what linters already catch — focus on semantic issues that require understanding the code
