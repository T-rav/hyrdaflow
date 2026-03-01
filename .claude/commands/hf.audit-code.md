# Code Quality Audit

Run a comprehensive code quality audit across the entire repo. Dynamically analyzes source code for dead code, complexity, duplication, error handling gaps, type safety issues, and architectural problems. Creates GitHub issues for findings so HydraFlow can process them.

## Instructions

1. **Resolve configuration** before doing anything else:
   - Run `echo "$HYDRAFLOW_GITHUB_REPO"` — if set, use it as the target repo (e.g., `owner/repo`). If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
   - Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"` — if set, use it as the issue assignee. If empty, extract the owner from the repo slug (the part before `/`).
   - Run `echo "$HYDRAFLOW_LABEL_PLAN"` — if set, use it as the label for created issues. If empty, default to `hydraflow-plan`.
   - Store resolved values as `$REPO`, `$ASSIGNEE`, `$LABEL`.

2. **Discover project structure:**
   - Use Glob to find all `*.py` source files, excluding `.venv/`, `venv/`, `__pycache__/`, `node_modules/`, `dist/`, `build/`.
   - Separate into SOURCE files (production code) and TEST files (anything under `tests/` or matching `test_*.py`).
   - Count total source files, total lines, and identify the main modules.

3. **Launch agents in parallel** using `Task` with `run_in_background: true` and `subagent_type: "general-purpose"`:
   - **Agent 1: Dead code & unused exports** — Finds unreachable code, unused functions, unused imports, and stale modules.
   - **Agent 2: Complexity & duplication** — Finds overly complex functions, duplicated logic, and DRY violations.
   - **Agent 3: Error handling & robustness** — Finds bare excepts, swallowed errors, missing error paths, and fragile patterns.
   - **Agent 4: Type safety & API consistency** — Finds missing type annotations, `Any` overuse, inconsistent return types, and public API gaps.

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

## Dead Code Found
| Type | File:Line | Name | Reason |
|------|-----------|------|--------|
| <function/class/import> | <path:line> | <name> | <never called/never imported/unreachable> |

## Suggested Actions
- [ ] Remove <item> — unused since <reason>
- [ ] Remove <item> — only referenced by other dead code

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

## Agent 2: Complexity & Duplication

```
You are a code quality auditor focused on complexity and duplication for the project at {repo_root}.

## Configuration
- GitHub repo: {REPO}
- Assignee: {ASSIGNEE}
- Label: {LABEL}

## Steps

### Phase 1: Identify Complex Functions
1. Use Glob to find all *.py source files (exclude tests/, .venv/, __pycache__/)
2. Read each source file and identify functions that are overly complex:
   - **Long functions**: > 50 lines (excluding docstring and blank lines)
   - **Deep nesting**: > 4 levels of indentation (nested if/for/try/with)
   - **High branch count**: > 8 if/elif/else branches in a single function
   - **Too many parameters**: > 6 parameters (excluding self/cls)
   - **Mixed concerns**: Function does unrelated things (e.g., I/O + business logic + formatting)
   For each finding, note: file path, line number, function name, metric value, why it's problematic

### Phase 2: Detect Code Duplication
3. Find duplicated logic patterns:
   - **Copy-paste blocks**: 5+ consecutive lines that appear nearly identical in 2+ locations
   - **Similar functions**: Functions with same structure but different variable names
   - **Repeated patterns**: Same sequence of API calls, error handling, or data transformation in 3+ places
   - **Inline constants**: Same magic number or string literal used in 3+ places without a named constant
4. For each duplication, identify: both locations, what differs, and how to extract a shared abstraction

### Phase 3: DRY Violations & Abstraction Opportunities
5. Look for:
   - **Missing helper functions**: Same 3+ line pattern repeated across files
   - **Missing base classes**: Multiple classes with identical method implementations
   - **Missing constants**: Repeated string literals or numbers that should be named
   - **Config duplication**: Same default values hardcoded in multiple places instead of referencing config
   - **Parallel implementations**: Two different ways of doing the same thing (e.g., two JSON serializers)

### Phase 4: Create GitHub Issues
6. Check for duplicate GH issues first:
   gh issue list --repo {REPO} --label {LABEL} --state open --search "<key terms>"
7. Create GH issues for NEW findings only:
   gh issue create --repo {REPO} --assignee {ASSIGNEE} --label {LABEL} --title "Code Quality: <theme>" --body "<details>"

## Issue Body Format
```markdown
## Context
<1-2 sentences on why reducing complexity/duplication matters here>

## Findings
| Issue | File:Line | Function/Block | Metric |
|-------|-----------|---------------|--------|
| <long function/duplication/deep nesting> | <path:line> | <name> | <value> |

## Suggested Refactoring
- [ ] Extract <helper function> from <locations> — <what it does>
- [ ] Split <long function> into <sub-functions>
- [ ] Replace magic value `<value>` with named constant

## Code Example (Before/After)
<Show a concrete before/after for the highest-impact item>
```

## Grouping Strategy
- "Code Quality: Reduce function complexity in <module>"
- "Code Quality: Extract shared patterns into helpers"
- "Code Quality: Replace magic constants with named values"
- "Code Quality: Deduplicate <pattern> across modules"

Focus on high-impact items: functions > 80 lines, 3+ duplicated blocks, deeply nested logic.
Skip trivial duplication (< 3 lines) and acceptable complexity (simple long switch-like patterns).

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

## Findings
| Severity | File:Line | Issue | Risk |
|----------|-----------|-------|------|
| <high/medium/low> | <path:line> | <description> | <what could go wrong> |

## Suggested Fixes
- [ ] <file:line> — Add error handling for <operation>
- [ ] <file:line> — Replace bare except with specific exception type
- [ ] <file:line> — Add timeout to subprocess call

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

## Findings
| Issue | File:Line | Current | Suggested |
|-------|-----------|---------|-----------|
| <missing type/Any overuse/inconsistent name> | <path:line> | <current state> | <what it should be> |

## Suggested Fixes
- [ ] <file:line> — Add return type annotation `-> X`
- [ ] <file:line> — Replace `Any` with `SpecificType`
- [ ] <file:line> — Rename `issue_num` to `issue_number` for consistency

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

## Important Notes
- Each agent should read files directly (no spawning sub-agents)
- Each agent should check `gh issue list` before creating any issue to avoid duplicates
- All issues should use the resolved `$REPO`, `$ASSIGNEE`, and `$LABEL`
- Group related findings into single themed issues — don't create one issue per finding
- Title format: "Code Quality: <theme>" for consistency
- Be pragmatic: focus on high-impact items that meaningfully improve code quality
- Skip nitpicks, style preferences, and issues already caught by ruff/pyright
- Don't duplicate what linters already catch — focus on semantic issues that require understanding the code
