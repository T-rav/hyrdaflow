"""Seed rule registry for :mod:`sensor_enricher`.

Each rule is a triple of (id, trigger, hint). Rules fire when tool
output is captured from a subprocess and match either a file-change
pattern or an error-regex pattern.

Rules seeded here mirror the rule bullets in
``docs/wiki/gotchas.md``. Adding a new avoided pattern?
Add both a section to that doc AND a rule here — the sensor enricher
will surface the hint the next time the matching failure occurs.

Part of the harness-engineering foundations (#6426).
"""

from __future__ import annotations

from sensor_enricher import ANY_TOOL, ErrorPattern, FileChanged, Rule

__all__ = ["SEED_RULES"]


SEED_RULES: list[Rule] = [
    Rule(
        id="pydantic-field-tests",
        tool=ANY_TOOL,
        trigger=FileChanged("src/models.py"),
        hint=(
            "You modified `src/models.py`. Pydantic field additions "
            "commonly break exact-match serialization tests. Grep `tests/` "
            "for the model name and update `model_dump()` assertions and "
            "expected-key sets in smoke tests. "
            "See docs/wiki/gotchas.md — 'Pydantic field "
            "additions without updating serialization tests'."
        ),
    ),
    Rule(
        id="optional-dep-toplevel-import",
        tool="pytest",
        trigger=ErrorPattern(
            r"ModuleNotFoundError.*(hindsight|httpx)"
            r"|ImportError.*(hindsight|httpx)"
        ),
        hint=(
            "An optional dependency (hindsight/httpx) failed to import at "
            "collection time. Move the import inside the test method "
            "instead of a module-level `from ... import ...`. "
            "See docs/wiki/gotchas.md — 'Top-level imports of "
            "optional dependencies in test files'."
        ),
    ),
    Rule(
        id="background-loop-wiring",
        tool=ANY_TOOL,
        trigger=FileChanged("src/*_loop.py"),
        hint=(
            "You modified a background loop module. The wiring "
            "completeness test (tests/test_loop_wiring_completeness.py) "
            "enforces entries in src/service_registry.py, src/orchestrator.py, "
            "src/ui/src/constants.js, src/dashboard_routes/_common.py, and "
            "src/config.py. Confirm all five are updated before committing. "
            "See docs/wiki/architecture.md."
        ),
    ),
    Rule(
        id="mock-wrong-patch-site",
        tool="pytest",
        trigger=ErrorPattern(
            r"AssertionError.*call_count|assert.*called_with|"
            r"AttributeError.*Mock object has no attribute"
        ),
        hint=(
            "Mock assertion failures often indicate patching at the wrong "
            "level. Patch functions at their IMPORT site (the module that "
            "does `from X import Y`), not at their DEFINITION site (module "
            "X itself). Python imports bind names into the importing "
            "module's namespace; a patch at the definition site does not "
            "affect local bindings. "
            "See docs/wiki/gotchas.md — 'Mocking at the wrong level'."
        ),
    ),
    Rule(
        id="falsy-optional-check",
        tool="pytest",
        # Match the actual code anti-pattern (`if not self._field`) appearing
        # in failure tracebacks or source snippets, NOT generic `is None`
        # assertion lines or NoneType tracebacks (which appear in countless
        # unrelated failures and would produce noisy hints).
        trigger=ErrorPattern(r"if not self\._\w+|if not self\.\w+:"),
        hint=(
            "Optional-attribute errors often come from `if not self._x` "
            "style falsy checks on values typed `X | None`. Mock objects "
            "are truthy by default, and some objects implement `__bool__`, "
            "so the falsy branch does not fire reliably. Use explicit "
            "`if self._x is None:` instead. "
            "See docs/wiki/gotchas.md — 'Falsy checks on "
            "optional objects'."
        ),
    ),
    Rule(
        id="private-symbol-cross-module",
        tool=ANY_TOOL,
        # Pyright's "\"_name\" is not accessed" warning fires both for
        # genuinely unused locals AND for private-by-convention names that
        # are only consumed by other modules. The fix differs:
        #   - cross-module consumer → promote to public (no underscore)
        #   - genuinely unused → rename to bare ``_``
        trigger=ErrorPattern(r'"_\w+" is not accessed|reportPrivateUsage'),
        hint=(
            "Pyright flagged a `_`-prefixed name as unaccessed or privately "
            "imported. If the name is consumed from another module, promote "
            "it to public (drop the leading underscore). If it's a truly "
            "unused loop/positional variable, rename to bare `_`. "
            "See docs/wiki/gotchas.md — 'Underscore-prefixed "
            "names imported across modules' and '`_name` for unused loop "
            "variables'."
        ),
    ),
    Rule(
        id="logger-format-typeerror",
        tool=ANY_TOOL,
        # Happens when logger.error(value) is called with a value that
        # contains `%s`, `%d`, or `{...}` — the logging machinery treats
        # the value as a format string and the arg count mismatches.
        trigger=ErrorPattern(
            r"TypeError: not enough arguments for format string"
            r"|TypeError: not all arguments converted during string formatting"
        ),
        hint=(
            "This TypeError usually means a logger call passed a variable "
            "as the format string (e.g. `logger.error(msg)` instead of "
            '`logger.error("%s", msg)`). Pass a literal format string '
            "first, the values after. "
            "See docs/wiki/gotchas.md — '`logger.error(value)` "
            "without a format string'."
        ),
    ),
    Rule(
        id="dockerfile-python-constant-drift",
        tool=ANY_TOOL,
        # Dockerfiles frequently mirror Python constants (baked-in plugin
        # dirs, tool paths, etc.). Changing one without updating the other
        # creates silent drift.
        trigger=FileChanged("Dockerfile*"),
        hint=(
            "You modified a Dockerfile. If this Dockerfile bakes in paths, "
            "plugin lists, or tool locations that Python code references, "
            "check whether a parallel Python constant needs updating — or "
            "better, replace the constant with a runtime scan of the "
            "authoritative source. "
            "See docs/wiki/gotchas.md — 'Hardcoded path lists "
            "that duplicate filesystem state'."
        ),
    ),
]
