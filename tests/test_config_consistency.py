"""Factory validation: config fields, env var overrides, and interval bounds are consistent.

Parses ``src/config.py`` for ``_ENV_INT_OVERRIDES``, ``_ENV_STR_OVERRIDES``, and
``_ENV_FLOAT_OVERRIDES`` tables plus ``HydraFlowConfig`` Field definitions. Verifies:

1. Interval fields (``*_interval``) in the override tables appear in ``_INTERVAL_BOUNDS``
2. Override table field names match actual ``HydraFlowConfig`` model fields

Uses regex-based parsing -- no imports from the config module.

Ref: gh-5907
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# ---------------------------------------------------------------------------
# Interval fields that intentionally lack _INTERVAL_BOUNDS entries.
# These are config-only intervals not exposed for dashboard editing.
# ---------------------------------------------------------------------------
_INTERVAL_BOUNDS_SKIP: set[str] = {
    "data_poll_interval",
    "dependabot_merge_interval",
    "report_issue_interval",
    "epic_monitor_interval",
    "epic_sweep_interval",
    "workspace_gc_interval",
    "runs_gc_interval",
    "health_monitor_interval",
    "sentry_poll_interval",
    # Dark-launched; the StagingPromotionLoop is not yet wired (flag-gated).
    "staging_promotion_interval",
}


def _parse_override_table(text: str, table_name: str) -> list[tuple[str, str]]:
    """Extract (field_name, env_var) pairs from a named override table.

    Matches the pattern: ("field_name", "ENV_VAR", default),
    Handles multi-line entries where field_name and env_var may be on separate lines.
    """
    # Find the start of the table assignment, then use bracket-counting to find the end
    # Handles type annotations like: _TABLE: list[tuple[str, str, int]] = [
    start_pattern = rf"{re.escape(table_name)}[^=]*=\s*\["
    start_match = re.search(start_pattern, text)
    if not start_match:
        return []
    # Count brackets to find the matching ]
    depth = 1
    pos = start_match.end()
    while pos < len(text) and depth > 0:
        if text[pos] == "[":
            depth += 1
        elif text[pos] == "]":
            depth -= 1
        pos += 1
    block = text[start_match.end() : pos - 1]
    # Extract all (field, env_var) pairs from tuples
    return re.findall(r'\(\s*"(\w+)"\s*,\s*"(\w+)"', block)


def _parse_config_fields() -> set[str]:
    """Extract all field names from HydraFlowConfig class definition."""
    text = (SRC / "config.py").read_text()
    # Match lines like:  field_name: int = Field(...)  or  field_name: str = "default"
    # within the class body. We look for attribute-style definitions.
    fields: set[str] = set()
    in_class = False
    for line in text.splitlines():
        if re.match(r"^class HydraFlowConfig", line):
            in_class = True
            continue
        if in_class:
            # End of class: non-indented, non-empty, non-comment line
            stripped = line.strip()
            if (
                stripped
                and not line.startswith(" ")
                and not line.startswith("\t")
                and not stripped.startswith("#")
                and not stripped.startswith('"""')
            ):
                break
            # Field definition: indented, has a colon for type annotation
            field_match = re.match(r"\s+(\w+)\s*:", line)
            if field_match:
                name = field_match.group(1)
                # Skip dunder/private and class-level constants
                if not name.startswith("_") and name[0].islower():
                    fields.add(name)
    return fields


def _parse_interval_bounds_keys() -> set[str]:
    """Extract worker keys from _INTERVAL_BOUNDS in _common.py."""
    path = SRC / "dashboard_routes" / "_common.py"
    text = path.read_text()
    return set(re.findall(r'"(\w+)"\s*:\s*\(', text))


def _get_all_override_fields() -> list[tuple[str, str]]:
    """Return all (field_name, env_var) pairs from all override tables."""
    text = (SRC / "config.py").read_text()
    pairs: list[tuple[str, str]] = []
    for table in [
        "_ENV_INT_OVERRIDES",
        "_ENV_STR_OVERRIDES",
        "_ENV_FLOAT_OVERRIDES",
        "_ENV_FLOAT_RATIO_OVERRIDES",
    ]:
        pairs.extend(_parse_override_table(text, table))
    return pairs


class TestIntervalFieldsHaveBounds:
    """Interval config fields should have matching _INTERVAL_BOUNDS entries."""

    def test_interval_fields_in_bounds(self) -> None:
        override_fields = _get_all_override_fields()
        interval_fields = {
            field for field, _ in override_fields if field.endswith("_interval")
        }
        bounds_keys = _parse_interval_bounds_keys()

        # Map interval field names to their expected bounds key.
        # Convention: remove the _interval suffix to get the worker name,
        # but some have custom mappings.
        _FIELD_TO_BOUNDS_KEY: dict[str, str] = {
            "memory_sync_interval": "memory_sync",
            "pr_unstick_interval": "pr_unsticker",
            "adr_review_interval": "adr_reviewer",
            "stale_issue_gc_interval": "stale_issue_gc",
            "ci_monitor_interval": "ci_monitor",
            "security_patch_interval": "security_patch",
            "code_grooming_interval": "code_grooming",
        }

        missing = set()
        for field in interval_fields:
            if field in _INTERVAL_BOUNDS_SKIP:
                continue
            bounds_key = _FIELD_TO_BOUNDS_KEY.get(field)
            if bounds_key is None:
                # Default: strip _interval suffix
                bounds_key = field.removesuffix("_interval")
            if bounds_key not in bounds_keys:
                missing.add(f"{field} -> expected bounds key '{bounds_key}'")

        assert not missing, (
            f"Interval fields missing from _INTERVAL_BOUNDS: {sorted(missing)}"
        )


class TestOverrideFieldsExist:
    """Every field in the override tables must exist on HydraFlowConfig."""

    def test_override_fields_match_config(self) -> None:
        config_fields = _parse_config_fields()
        override_fields = _get_all_override_fields()

        missing = {field for field, _ in override_fields if field not in config_fields}
        assert not missing, (
            f"Override table fields not found in HydraFlowConfig: {sorted(missing)}"
        )


class TestSkipListFreshness:
    """Ensure skip-list entries refer to actual interval fields."""

    def test_skip_entries_are_real_fields(self) -> None:
        override_fields = _get_all_override_fields()
        interval_fields = {
            field for field, _ in override_fields if field.endswith("_interval")
        }
        stale = _INTERVAL_BOUNDS_SKIP - interval_fields
        assert not stale, (
            f"_INTERVAL_BOUNDS_SKIP contains entries not in override tables: {sorted(stale)}"
        )
