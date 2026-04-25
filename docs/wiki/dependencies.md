# Dependencies


## Circular Dependencies & Import Management

Use TYPE_CHECKING guards and deferred imports (PEP 563) to break circular dependencies at the import level. For runtime circular references between extracted classes, inject callback functions instead of class references (e.g., `get_progress=epic_reporter.get_progress`) to avoid circular imports and make dependency direction explicit in constructor signatures.

Manage optional dependencies through three-level degradation, structural typing with Protocols, and explicit API composition via optional parameters. When a helper feeds data into a pipeline (e.g., memory injection), wrap the entire body in `except Exception: # noqa: BLE001` with no re-raise—return a safe default instead. Failures in optional data collection must not interrupt the pipeline itself; this is especially important for optional features like Hindsight recall that degrade gracefully. Use modern generic syntax with `from __future__ import annotations` on Python 3.9+.

When extracting multiple coordinators from a god class, identify those with zero cross-dependencies and extract in parallel phases. Dependencies between extracted classes (e.g., 'ReviewVerdictHandler uses CIFixCoordinator') create phase ordering constraints. Map this as a task graph to prevent parallel work from being blocked.

After extracting duplicated code and removing unused imports, verify extraction completeness through two-stage verification: (1) check function signatures, return type hints, and other locations across the file to confirm imports are truly unused; (2) use targeted grep across the codebase for old names in imports, documentation, comments, dynamic imports, and test fixtures to prevent false positives. Deferred imports become cleanup signals when removing code—look for these as dead code markers.

Apply the single update point pattern: define artifacts once and import everywhere to prevent divergence. For FastAPI, register catch-all `/{path:path}` route last.

See also: Type Signatures as Backward-Compatibility Contracts — for communicating contract changes before implementation changes.


```json:entry
{"id":"01KQ11NX7QNTT50G9SENE613W0","title":"Circular Dependencies & Import Management","content":"Use TYPE_CHECKING guards and deferred imports (PEP 563) to break circular dependencies at the import level. For runtime circular references between extracted classes, inject callback functions instead of class references (e.g., `get_progress=epic_reporter.get_progress`) to avoid circular imports and make dependency direction explicit in constructor signatures.\n\nManage optional dependencies through three-level degradation, structural typing with Protocols, and explicit API composition via optional parameters. When a helper feeds data into a pipeline (e.g., memory injection), wrap the entire body in `except Exception: # noqa: BLE001` with no re-raise—return a safe default instead. Failures in optional data collection must not interrupt the pipeline itself; this is especially important for optional features like Hindsight recall that degrade gracefully. Use modern generic syntax with `from __future__ import annotations` on Python 3.9+.\n\nWhen extracting multiple coordinators from a god class, identify those with zero cross-dependencies and extract in parallel phases. Dependencies between extracted classes (e.g., 'ReviewVerdictHandler uses CIFixCoordinator') create phase ordering constraints. Map this as a task graph to prevent parallel work from being blocked.\n\nAfter extracting duplicated code and removing unused imports, verify extraction completeness through two-stage verification: (1) check function signatures, return type hints, and other locations across the file to confirm imports are truly unused; (2) use targeted grep across the codebase for old names in imports, documentation, comments, dynamic imports, and test fixtures to prevent false positives. Deferred imports become cleanup signals when removing code—look for these as dead code markers.\n\nApply the single update point pattern: define artifacts once and import everywhere to prevent divergence. For FastAPI, register catch-all `/{path:path}` route last.\n\nSee also: Type Signatures as Backward-Compatibility Contracts — for communicating contract changes before implementation changes.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T06:57:24.154748+00:00","updated_at":"2026-04-10T06:57:24.154755+00:00","valid_from":"2026-04-10T06:57:24.154748+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Data Schema Evolution & Transitive Dependency Tracking

Manage data schemas through changes using: embed schema_version in each JSON line for self-describing records; use Pydantic defaults so old records missing new fields deserialize without migration code. Scan transitive dependencies recursively when invalidating items, updating all ancestors to point to final successors with depth limits to prevent infinite loops. Format complete content before truncating to character limits; use unconditional overwrite for small files; use atomic writes with rotate_backups for natural versioning and recovery. For external APIs not returning memory IDs, use sha256(text)[:16] as synthetic content hashes for temporal tracking.


```json:entry
{"id":"01KQ11NX7QNTT50G9SENE613W1","title":"Data Schema Evolution & Transitive Dependency Tracking","content":"Manage data schemas through changes using: embed schema_version in each JSON line for self-describing records; use Pydantic defaults so old records missing new fields deserialize without migration code. Scan transitive dependencies recursively when invalidating items, updating all ancestors to point to final successors with depth limits to prevent infinite loops. Format complete content before truncating to character limits; use unconditional overwrite for small files; use atomic writes with rotate_backups for natural versioning and recovery. For external APIs not returning memory IDs, use sha256(text)[:16] as synthetic content hashes for temporal tracking.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T06:57:24.154763+00:00","updated_at":"2026-04-10T06:57:24.154764+00:00","valid_from":"2026-04-10T06:57:24.154763+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Type Signatures as Backward-Compatibility Contracts

Update function signatures to reflect new stricter types (e.g., `phase: PipelineStage | Literal[""]`) before modifying callers. Existing call sites with hardcoded string literals continue working via StrEnum coercion, making the signature change the primary integration point. Type signatures communicate contract changes to callers before implementation changes are made.

_Source: #6335 (review)_


```json:entry
{"id":"01KQ11NX7QNTT50G9SENE613W2","title":"Type Signatures as Backward-Compatibility Contracts","content":"Update function signatures to reflect new stricter types (e.g., `phase: PipelineStage | Literal[\"\"]`) before modifying callers. Existing call sites with hardcoded string literals continue working via StrEnum coercion, making the signature change the primary integration point. Type signatures communicate contract changes to callers before implementation changes are made.","topic":null,"source_type":"review","source_issue":6335,"source_repo":null,"created_at":"2026-04-10T06:57:24.154767+00:00","updated_at":"2026-04-10T06:57:24.154768+00:00","valid_from":"2026-04-10T06:57:24.154767+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Top-level imports of optional dependencies in test files

Never write `from hindsight import Bank` at module level in tests. `httpx`, `hindsight`, and similar optional packages are not guaranteed to be installed in every environment.

**Wrong:**

```python
# tests/test_something.py
from hindsight import Bank  # module-level — fails import if hindsight not installed

class TestSomething:
    def test_x(self):
        bank = Bank()
```

**Right:**

```python
# tests/test_something.py
class TestSomething:
    def test_x(self):
        from hindsight import Bank  # deferred — only imports when the test runs
        bank = Bank()
```

**Why:** Top-level imports run at collection time. If the optional dep is missing, the entire test file fails to collect, hiding every test in it from the report.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBC","title":"Top-level imports of optional dependencies in test files","content":"Never write `from hindsight import Bank` at module level in tests. `httpx`, `hindsight`, and similar optional packages are not guaranteed to be installed in every environment.\n\n**Wrong:**\n\n```python\n# tests/test_something.py\nfrom hindsight import Bank  # module-level — fails import if hindsight not installed\n\nclass TestSomething:\n    def test_x(self):\n        bank = Bank()\n```\n\n**Right:**\n\n```python\n# tests/test_something.py\nclass TestSomething:\n    def test_x(self):\n        from hindsight import Bank  # deferred — only imports when the test runs\n        bank = Bank()\n```\n\n**Why:** Top-level imports run at collection time. If the optional dep is missing, the entire test file fails to collect, hiding every test in it from the report.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793217+00:00","updated_at":"2026-04-25T00:47:19.793218+00:00","valid_from":"2026-04-25T00:47:19.793217+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Self-Improving Harness

This branch imports selected assets from `affaan-m/everything-claude-code` and wires them into HydraFlow's existing hook discipline.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249Q","title":"Self-Improving Harness","content":"This branch imports selected assets from `affaan-m/everything-claude-code` and wires them into HydraFlow's existing hook discipline.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794385+00:00","updated_at":"2026-04-25T00:47:19.794386+00:00","valid_from":"2026-04-25T00:47:19.794385+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Imported Skills

Installed under `.codex/skills/`:

- `continuous-learning-v2`
- `eval-harness`
- `verification-loop`
- `strategic-compact`
- `skill-stocktake`


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249R","title":"Imported Skills","content":"Installed under `.codex/skills/`:\n\n- `continuous-learning-v2`\n- `eval-harness`\n- `verification-loop`\n- `strategic-compact`\n- `skill-stocktake`","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794392+00:00","updated_at":"2026-04-25T00:47:19.794393+00:00","valid_from":"2026-04-25T00:47:19.794392+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Runtime Loop

HydraFlow now runs two additional hooks:

- `PostToolUse` -> `.claude/hooks/hf.observe-session.sh`
  - Captures minimal tool metadata (tool, file path, bash verb, session ID)
  - Writes JSONL to `.claude/state/self-improve/observations.jsonl`
- `Stop` -> `.claude/hooks/hf.session-retro.sh`
  - Generates per-session retros in `.claude/state/self-improve/session-retros/`
  - Appends index entries to `.claude/state/self-improve/memory-candidates.md`
  - Emits actionable suggestions tied to imported skills

Runtime artifacts are ignored via `.gitignore` (`.claude/state/`).


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249S","title":"Runtime Loop","content":"HydraFlow now runs two additional hooks:\n\n- `PostToolUse` -> `.claude/hooks/hf.observe-session.sh`\n  - Captures minimal tool metadata (tool, file path, bash verb, session ID)\n  - Writes JSONL to `.claude/state/self-improve/observations.jsonl`\n- `Stop` -> `.claude/hooks/hf.session-retro.sh`\n  - Generates per-session retros in `.claude/state/self-improve/session-retros/`\n  - Appends index entries to `.claude/state/self-improve/memory-candidates.md`\n  - Emits actionable suggestions tied to imported skills\n\nRuntime artifacts are ignored via `.gitignore` (`.claude/state/`).","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794397+00:00","updated_at":"2026-04-25T00:47:19.794398+00:00","valid_from":"2026-04-25T00:47:19.794397+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
