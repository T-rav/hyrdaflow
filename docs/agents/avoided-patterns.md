# Avoided Patterns

Common mistakes agents make in the HydraFlow codebase. These are semantic rules that linters and type checkers cannot catch — they require understanding the project's conventions and prior incidents. Read this doc before editing the areas each rule calls out.

This is the canonical location for avoided patterns. `CLAUDE.md` links here; do not duplicate rules back into `CLAUDE.md`. Sensors (`src/sensor_enricher.py`) and audit agents (`.claude/commands/hf.audit-code.md`) read this doc to coach agents during failures.

## Pydantic field additions without updating serialization tests

When you add a field to any model in `src/models.py` (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update ALL exact-match serialization tests.

- `model_dump()` assertions
- Expected key sets in smoke tests
- Any `assert result == {...}` that hard-codes the full model shape

**Why:** HydraFlow has strict exact-match tests that assert on the complete serialized dict. A new field breaks them silently during unrelated refactors, and CI flags it later as a mysterious regression.

**How to check:** After editing `models.py`, run `rg "<ModelName>" tests/` and confirm every match still passes.

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

## Falsy checks on optional objects

Never write `if not self._hindsight` to test whether an optional object is present. Falsy checks can fire unexpectedly on mock objects, empty collections, and objects that implement `__bool__`.

**Wrong:**

```python
if not self._hindsight:
    return None
```

**Right:**

```python
if self._hindsight is None:
    return None
```

**Why:** `Mock()` objects are truthy by default, but a `Mock()` configured with `spec=SomeClass` that has `__bool__` can be falsy, and ordinary values like empty lists or dicts trigger the wrong branch. Explicit `is None` makes the intent unambiguous and matches the type annotation contract (`X | None`).

## Underscore-prefixed names imported across modules

If a symbol is imported from another module, it is part of that module's public API and must not start with `_`. The leading underscore is Python's "module-internal" convention; crossing the boundary lies about the contract and trips pyright's `reportPrivateUsage` / unused-symbol warnings.

**Wrong:**

```python
# src/plugin_skill_registry.py
def _parse_plugin_spec(spec: str) -> tuple[str, str]: ...

# src/preflight.py
from plugin_skill_registry import _parse_plugin_spec  # crosses the boundary
```

**Right:**

```python
# src/plugin_skill_registry.py
def parse_plugin_spec(spec: str) -> tuple[str, str]: ...

# src/preflight.py
from plugin_skill_registry import parse_plugin_spec
```

**Why:** Pyright flags private-symbol imports and "defined but not used" warnings for `_`-prefixed names whose only consumers are other modules. Promotion to public is also a signal to future readers that the symbol is a load-bearing contract, not an implementation detail.

**How to check:** Any symbol imported across module boundaries must not start with `_`. If it does, rename or refactor in the same change.

## Writing a new test helper without checking conftest

Before adding a helper function to a test file, grep `tests/conftest.py` (and any `tests/helpers*.py`) for similar helpers. Shared test fixtures belong in conftest; duplicating a helper locally causes drift when one copy is updated and the other is not.

**Wrong:**

```python
# tests/test_my_feature.py
def _write_fake_skill(cache_root, marketplace, plugin, skill):
    skill_dir = cache_root / marketplace / plugin / "1.0.0" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\nbody\n")
```

(while `tests/conftest.py:write_plugin_skill` already does exactly this.)

**Right:**

```python
# tests/test_my_feature.py
from tests.conftest import write_plugin_skill
```

**Why:** Duplicated helpers drift silently. If `write_plugin_skill` in conftest gains a new parameter or changes its on-disk layout, the local copy stays stale and tests pass against a fiction.

**How to check:** Before adding any `def _<something>` in a test file, run `rg "def <name>" tests/conftest.py tests/helpers*.py` for semantically-similar helpers.

## `logger.error(value)` without a format string

Logging calls must pass a format string as the first argument and the variable as the second. Passing a variable directly treats the variable as the format template — if it ever contains `%s`, `%d`, or `{...}`, logging either misformats or raises `TypeError` at runtime.

**Wrong:**

```python
for failure in failures:
    logger.error(failure)  # failure is the format string — unsafe
```

**Right:**

```python
for failure in failures:
    logger.error("%s", failure)
```

**Why:** Latent logging-injection bug. `logger.error("got error: %s")` with a user-controlled string containing `%d` raises `TypeError: not enough arguments for format string` at runtime, not during testing. The `logger.error("%s", value)` form defers formatting to the logging machinery which handles it safely.

**How to check:** `rg "logger\.(error|warning|info|debug)\(\w+\)" src/` — every match should have a literal string as the first argument.

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

## `_name` for unused loop variables (prefer bare `_`)

Python's informal "unused by intent" convention is a bare `_`, not `_name`. Pyright and some strict linters treat `_name` as a named variable that happens to start with `_` and flag it as unused regardless.

**Wrong:**

```python
for _lang, name, marketplace in specs:
    install(name, marketplace)
# Pyright: "_lang" is not accessed
```

**Right:**

```python
for _, name, marketplace in specs:
    install(name, marketplace)
```

**Why:** Bare `_` is universally understood as "throwaway"; `_name` is not. Reserve `_name` only when documentation value is meaningful enough to keep a name alive. Otherwise use bare `_`.

**How to check:** `rg "for _[a-z]" src/` — each match should justify why the underscore-prefixed name is more readable than bare `_`.

---

## Adding a new avoided pattern

When you observe a new recurring agent failure:

1. Add a new `##` section to this doc with the same structure (wrong example, right example, why).
2. Consider adding a rule to `src/sensor_rules.py` so the sensor enricher surfaces the hint automatically on matching failures.
3. Consider whether `.claude/commands/hf.audit-code.md` Agent 5 (convention drift) should check for this pattern on its next sweep.

Documenting the pattern once in this file propagates it to all three surfaces.
