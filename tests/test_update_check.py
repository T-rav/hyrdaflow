"""Tests for ``update_check`` utilities."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import httpx
import pytest

import update_check


class DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.raise_called = False

    def raise_for_status(self) -> None:
        self.raise_called = True

    def json(self) -> dict[str, object]:
        return self.payload


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


class TestWriteCache:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "nested" / "cache.json"
        payload = {"checked_at": 10}
        update_check._write_cache(payload, cache_path)
        assert json.loads(cache_path.read_text()) == payload


class TestFetchLatestPyPIVersion:
    def test_returns_version_from_pypi_payload(self, monkeypatch) -> None:
        response = DummyResponse({"info": {"version": "3.2.1"}})

        def fake_get(url: str, *, headers: dict[str, str], timeout: float):
            assert url == update_check._PYPI_JSON_URL
            assert headers["Accept"] == "application/json"
            assert timeout == 5.0
            return response

        monkeypatch.setattr(update_check.httpx, "get", fake_get)

        latest = update_check._fetch_latest_pypi_version(timeout_seconds=5.0)
        assert response.raise_called is True
        assert latest == "3.2.1"

    def test_raises_when_payload_missing_version(self, monkeypatch) -> None:
        response = DummyResponse({"info": {}})
        monkeypatch.setattr(update_check.httpx, "get", lambda *_, **__: response)

        with pytest.raises(RuntimeError):
            update_check._fetch_latest_pypi_version(timeout_seconds=1.0)


class TestCheckForUpdates:
    def test_successful_check_marks_update_available(self, monkeypatch) -> None:
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")
        monkeypatch.setattr(
            update_check, "_fetch_latest_pypi_version", lambda _: "1.0.1"
        )

        result = update_check.check_for_updates(timeout_seconds=2.5)

        assert result.update_available is True
        assert result.error is None

    def test_failure_path_sets_error(self, monkeypatch) -> None:
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")

        def boom(_: float) -> str:
            raise httpx.HTTPError("network down")

        monkeypatch.setattr(update_check, "_fetch_latest_pypi_version", boom)

        result = update_check.check_for_updates(timeout_seconds=1.0)

        assert result.update_available is False
        assert result.latest_version is None
        assert "network down" in (result.error or "")


class TestCheckForUpdatesCached:
    def test_returns_cached_value_when_fresh(self, tmp_path: Path, monkeypatch) -> None:
        cache_path = tmp_path / "cache.json"
        now = 1_700_000_000
        cache_path.write_text(
            json.dumps(
                {
                    "checked_at": now - 60,
                    "current_version": "1.0.0",
                    "latest_version": "2.0.0",
                }
            )
        )
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")
        monkeypatch.setattr(update_check.time, "time", lambda: now)

        result = update_check.check_for_updates_cached(
            timeout_seconds=0.5, max_age_seconds=3600, path=cache_path
        )

        assert result.latest_version == "2.0.0"
        assert result.update_available is True

    def test_refreshes_cache_when_stale(self, tmp_path: Path, monkeypatch) -> None:
        cache_path = tmp_path / "cache.json"
        now = 1_700_000_000
        cache_path.write_text(
            json.dumps(
                {
                    "checked_at": now - 10_000,
                    "current_version": "1.0.0",
                    "latest_version": "1.1.0",
                }
            )
        )
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")
        monkeypatch.setattr(update_check.time, "time", lambda: now)

        expected = update_check.UpdateCheckResult(
            current_version="1.0.0",
            latest_version="2.0.0",
            update_available=True,
            error=None,
        )

        def fake_check(timeout_seconds: float) -> update_check.UpdateCheckResult:
            assert timeout_seconds == 0.5
            return expected

        monkeypatch.setattr(update_check, "check_for_updates", fake_check)

        result = update_check.check_for_updates_cached(
            timeout_seconds=0.5, max_age_seconds=3600, path=cache_path
        )

        assert result is expected
        stored = json.loads(cache_path.read_text())
        assert stored["latest_version"] == "2.0.0"
        assert stored["checked_at"] == now

    def test_version_change_invalidates_cache(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        cache_path = tmp_path / "cache.json"
        now = 1_700_000_000
        # Cache was written when version was "1.0.0", but now we're on "1.1.0"
        cache_path.write_text(
            json.dumps(
                {
                    "checked_at": now - 60,
                    "current_version": "1.0.0",
                    "latest_version": "2.0.0",
                }
            )
        )
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.1.0")
        monkeypatch.setattr(update_check.time, "time", lambda: now)

        expected = update_check.UpdateCheckResult(
            current_version="1.1.0",
            latest_version="2.0.0",
            update_available=True,
        )

        def fake_check(timeout_seconds: float) -> update_check.UpdateCheckResult:  # noqa: ARG001
            return expected

        monkeypatch.setattr(update_check, "check_for_updates", fake_check)

        result = update_check.check_for_updates_cached(
            timeout_seconds=0.5, max_age_seconds=3600, path=cache_path
        )

        assert result is expected

    def test_skips_cache_write_when_no_latest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(update_check, "get_app_version", lambda: "1.0.0")
        monkeypatch.setattr(update_check.time, "time", lambda: 1_700_000_000)

        expected = update_check.UpdateCheckResult(
            current_version="1.0.0",
            latest_version=None,
            update_available=False,
            error="timeout",
        )
        monkeypatch.setattr(
            update_check,
            "check_for_updates",
            lambda timeout_seconds=2.0: expected,
        )

        writes: list[dict[str, object]] = []

        def fake_write(payload: dict[str, object], path: Path) -> None:
            writes.append(payload)

        monkeypatch.setattr(update_check, "_write_cache", fake_write)

        result = update_check.check_for_updates_cached(path=cache_path)

        assert result is expected
        assert writes == []
