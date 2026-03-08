"""Tests for ``app_version`` helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import app_version


def test_get_app_version_returns_installed_value(monkeypatch):
    calls: list[str] = []

    def fake_version(package_name: str) -> str:
        calls.append(package_name)
        return "2.1.0"

    monkeypatch.setattr(app_version, "version", fake_version)

    result = app_version.get_app_version()

    assert result == "2.1.0"
    assert calls == [app_version._PACKAGE_NAME]


def test_get_app_version_falls_back_when_package_missing(monkeypatch):
    def fake_version(_: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(app_version, "version", fake_version)

    result = app_version.get_app_version()

    assert result == app_version._FALLBACK_VERSION
