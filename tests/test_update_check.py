"""Tests for ``update_check`` utilities."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import update_check


class TestUpdateCheckResult:
    def test_dataclass_is_frozen(self) -> None:
        result = update_check.UpdateCheckResult(
            current_version="1.0.0",
            latest_version="2.0.0",
            update_available=True,
        )
        with pytest.raises(FrozenInstanceError):
            result.current_version = "1.1.0"  # type: ignore[misc]


class TestVersionKey:
    def test_parses_numeric_chunks(self) -> None:
        assert update_check._version_key("1.2.3") == (1, 2, 3)

    def test_strips_non_digit_chars_from_chunks(self) -> None:
        assert update_check._version_key("1.2beta") == (1, 2)

    def test_stops_at_all_alpha_chunk(self) -> None:
        # "beta" has no digits at all — the break fires and trailing "3" is ignored
        assert update_check._version_key("1.beta.3") == (1,)


class TestIsNewer:
    def test_compares_numeric_keys(self) -> None:
        assert update_check._is_newer("2.0.0", "1.9.9") is True
        assert update_check._is_newer("1.0.1", "1.2.0") is False
        assert update_check._is_newer("1.0.0", "1.0.0") is False

    def test_falls_back_to_inequality_when_no_numeric_keys(self) -> None:
        # Fallback uses `latest != current`, not lexicographic ordering
        assert update_check._is_newer("beta", "alpha") is True
        assert update_check._is_newer("beta", "beta") is False
        assert (
            update_check._is_newer("alpha", "beta") is True
        )  # different → True despite lex order


class TestReadCache:
    def test_returns_dict_for_valid_cache_file(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        data = {"latest_version": "2.0.0"}
        cache_path.write_text(json.dumps(data))
        assert update_check._read_cache(cache_path) == data

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{invalid json")
        assert update_check._read_cache(cache_path) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert update_check._read_cache(tmp_path / "nonexistent.json") is None


class TestLoadCachedUpdateResult:
    def test_returns_none_for_incomplete_cache(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({"current_version": "", "latest_version": ""}))
        assert update_check.load_cached_update_result(path=cache_path) is None

    def test_returns_deserialized_result(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps(
                {"current_version": "1.0.0", "latest_version": "2.0.0"},
            )
        )
        result = update_check.load_cached_update_result(path=cache_path)
        assert result is not None
        assert result.current_version == "1.0.0"
        assert result.latest_version == "2.0.0"
        assert result.update_available is True

    def test_prefers_explicit_current_version_argument(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps(
                {"current_version": "0.1.0", "latest_version": "1.0.0"},
            )
        )
        result = update_check.load_cached_update_result(
            current_version="0.2.0", path=cache_path
        )
        assert result is not None
        assert result.current_version == "0.2.0"
        assert result.update_available is True
