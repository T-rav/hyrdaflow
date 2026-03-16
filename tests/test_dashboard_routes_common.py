"""Tests for dashboard_routes._common — shared constants and helpers.

Ensures all symbols extracted to the canonical _common module are importable,
correct, and that no sub-module re-defines them inline.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._common import (
    _EPIC_INTERNAL_LABELS,
    _FRONTEND_STAGE_TO_LABEL_FIELD,
    _HISTORY_STATUSES,
    _INFERENCE_COUNTER_KEYS,
    _INTERVAL_BOUNDS,
    _SAFE_SLUG_COMPONENT,
    _STAGE_NAME_MAP,
    _coerce_history_status,
    _coerce_int,
    _extract_field_from_sources,
    _is_timestamp_in_range,
    _parse_compat_json_object,
    _parse_iso_or_none,
    _status_rank,
    _status_sort_key,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestSharedConstants:
    """Verify shared constants are importable and well-formed."""

    def test_safe_slug_component_is_compiled_regex(self) -> None:
        assert isinstance(_SAFE_SLUG_COMPONENT, re.Pattern)

    def test_safe_slug_component_accepts_valid(self) -> None:
        assert _SAFE_SLUG_COMPONENT.match("my-repo_1.0")

    def test_safe_slug_component_rejects_slashes(self) -> None:
        assert _SAFE_SLUG_COMPONENT.match("foo/bar") is None

    def test_interval_bounds_non_empty(self) -> None:
        assert len(_INTERVAL_BOUNDS) > 0

    def test_interval_bounds_values_are_tuples(self) -> None:
        for key, bounds in _INTERVAL_BOUNDS.items():
            assert isinstance(bounds, tuple), f"{key} should be a tuple"
            assert len(bounds) == 2, f"{key} should have (min, max)"
            assert bounds[0] < bounds[1], f"{key}: min must be < max"

    def test_epic_internal_labels_is_frozenset(self) -> None:
        assert isinstance(_EPIC_INTERNAL_LABELS, frozenset)
        assert "hydraflow-epic" in _EPIC_INTERNAL_LABELS

    def test_stage_name_map_covers_all_stages(self) -> None:
        expected_values = {"triage", "plan", "implement", "review", "hitl"}
        assert set(_STAGE_NAME_MAP.values()) == expected_values

    def test_frontend_stage_to_label_field_keys(self) -> None:
        expected_keys = {"triage", "plan", "implement", "review"}
        assert set(_FRONTEND_STAGE_TO_LABEL_FIELD.keys()) == expected_keys

    def test_inference_counter_keys_non_empty(self) -> None:
        assert len(_INFERENCE_COUNTER_KEYS) > 0
        assert "inference_calls" in _INFERENCE_COUNTER_KEYS

    def test_history_statuses_is_set(self) -> None:
        assert isinstance(_HISTORY_STATUSES, set)
        assert "merged" in _HISTORY_STATUSES
        assert "unknown" in _HISTORY_STATUSES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestParseIsoOrNone:
    """Tests for _parse_iso_or_none."""

    def test_none_input(self) -> None:
        assert _parse_iso_or_none(None) is None

    def test_empty_string(self) -> None:
        assert _parse_iso_or_none("") is None

    def test_invalid_string(self) -> None:
        assert _parse_iso_or_none("not-a-date") is None

    def test_valid_iso_with_tz(self) -> None:
        result = _parse_iso_or_none("2025-01-15T10:30:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_valid_iso_without_tz_gets_utc(self) -> None:
        result = _parse_iso_or_none("2025-01-15T10:30:00")
        assert result is not None
        assert result.tzinfo == UTC


class TestCoerceInt:
    """Tests for _coerce_int."""

    def test_int_passthrough(self) -> None:
        assert _coerce_int(42) == 42

    def test_float_truncates(self) -> None:
        assert _coerce_int(3.9) == 3

    def test_string_converts(self) -> None:
        assert _coerce_int("7") == 7

    def test_invalid_string_returns_zero(self) -> None:
        assert _coerce_int("abc") == 0

    def test_bool_converts(self) -> None:
        assert _coerce_int(True) == 1
        assert _coerce_int(False) == 0

    def test_none_returns_zero(self) -> None:
        assert _coerce_int(None) == 0


class TestCoerceHistoryStatus:
    """Tests for _coerce_history_status."""

    def test_valid_status_lowered(self) -> None:
        assert _coerce_history_status("MERGED") == "merged"

    def test_valid_status_trimmed(self) -> None:
        assert _coerce_history_status("  active  ") == "active"

    def test_unknown_returns_unknown(self) -> None:
        assert _coerce_history_status("bogus") == "unknown"


class TestStatusRank:
    """Tests for _status_rank."""

    def test_merged_is_highest(self) -> None:
        assert _status_rank("merged") == 9

    def test_unknown_is_lowest(self) -> None:
        assert _status_rank("unknown") == 0

    def test_unrecognised_returns_zero(self) -> None:
        assert _status_rank("nonexistent") == 0


class TestIsTimestampInRange:
    """Tests for _is_timestamp_in_range."""

    def test_none_raw_with_no_bounds(self) -> None:
        assert _is_timestamp_in_range(None, None, None) is True

    def test_none_raw_with_since(self) -> None:
        since = datetime(2025, 1, 1, tzinfo=UTC)
        assert _is_timestamp_in_range(None, since, None) is False

    def test_in_range(self) -> None:
        since = datetime(2025, 1, 1, tzinfo=UTC)
        until = datetime(2025, 12, 31, tzinfo=UTC)
        assert _is_timestamp_in_range("2025-06-15T00:00:00+00:00", since, until) is True

    def test_before_since(self) -> None:
        since = datetime(2025, 6, 1, tzinfo=UTC)
        assert _is_timestamp_in_range("2025-01-01T00:00:00+00:00", since, None) is False


class TestStatusSortKey:
    """Tests for _status_sort_key."""

    def test_returns_tuple(self) -> None:
        result = _status_sort_key("merged", "2025-01-15T10:00:00+00:00")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_none_timestamp_uses_min(self) -> None:
        result = _status_sort_key("merged", None)
        assert result[0] == datetime.min.replace(tzinfo=UTC)


class TestParseCompatJsonObject:
    """Tests for _parse_compat_json_object."""

    def test_none_returns_none(self) -> None:
        assert _parse_compat_json_object(None) is None

    def test_empty_string(self) -> None:
        assert _parse_compat_json_object("") is None

    def test_valid_json_object(self) -> None:
        assert _parse_compat_json_object('{"key": "val"}') == {"key": "val"}

    def test_json_array_returns_none(self) -> None:
        assert _parse_compat_json_object("[1,2]") is None

    def test_invalid_json(self) -> None:
        assert _parse_compat_json_object("{bad}") is None


class TestExtractFieldFromSources:
    """Tests for _extract_field_from_sources."""

    def test_body_dict(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"),
            {"slug": "owner/repo"},
            None,
            (None, None),
        )
        assert result == "owner/repo"

    def test_query_params_first(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"),
            {"slug": "from-body"},
            None,
            ("from-query", None),
            query_params_first=True,
        )
        assert result == "from-query"

    def test_empty_returns_empty_string(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"),
            None,
            None,
            (None, None),
        )
        assert result == ""


# ---------------------------------------------------------------------------
# No-duplication guard
# ---------------------------------------------------------------------------


class TestNoDuplicateCommonSymbols:
    """Ensure _common constants are not redefined in sibling sub-modules.

    This is the primary guard against the RepoSlugParam-style duplication
    pattern (issue #2723).
    """

    # Match `_UPPER_SNAKE = ...` or `_UPPER_SNAKE: <any type annotation> = ...`.
    # Use `[^=\n]+` for the type annotation so multi-word annotations like
    # `dict[str, str]` or `tuple[str, ...]` are handled correctly.
    _CONSTANT_RE = re.compile(
        r"^(_[A-Z][A-Z0-9_]+)\s*(?::[^=\n]+)?=\s*",
        re.MULTILINE,
    )

    _PKG_DIR = Path(__file__).resolve().parent.parent / "src" / "dashboard_routes"

    def _canonical_names(self) -> set[str]:
        source = (self._PKG_DIR / "_common.py").read_text()
        return {m.group(1) for m in self._CONSTANT_RE.finditer(source)}

    def test_no_duplicate_constants_in_routes(self) -> None:
        canonical = self._canonical_names()
        assert canonical, "_common.py should define at least one constant"

        sub_modules = [
            p
            for p in self._PKG_DIR.glob("*.py")
            if p.name not in {"_common.py", "__init__.py"}
        ]
        assert sub_modules, (
            "Expected at least one sub-module besides _common and __init__"
        )

        all_duplicates: dict[str, list[str]] = {}
        for sub in sub_modules:
            content = sub.read_text()
            dups = [
                m.group(1)
                for m in self._CONSTANT_RE.finditer(content)
                if m.group(1) in canonical
            ]
            if dups:
                all_duplicates[sub.name] = dups

        assert all_duplicates == {}, (
            f"Found constants that should be imported from _common.py: {all_duplicates}"
        )
