"""Unit tests for src/telemetry/otel.py — feature-gated SDK bootstrap."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.telemetry import otel as otel_mod


def _config(**overrides):
    """Build a minimal config-like object with the otel_* fields."""
    base = {
        "otel_enabled": True,
        "otel_endpoint": "https://api.honeycomb.io",
        "otel_service_name": "hydraflow",
        "otel_environment": "test",
    }
    base.update(overrides)
    cfg = MagicMock()
    for k, v in base.items():
        setattr(cfg, k, v)
    return cfg


def test_init_otel_disabled_is_noop():
    cfg = _config(otel_enabled=False)
    with patch.object(otel_mod, "_install_provider") as install:
        otel_mod.init_otel(cfg)
    install.assert_not_called()


def test_init_otel_enabled_no_key_warns_and_returns(monkeypatch, caplog):
    monkeypatch.delenv("HONEYCOMB_API_KEY", raising=False)
    cfg = _config()
    with (
        caplog.at_level(logging.WARNING),
        patch.object(otel_mod, "_install_provider") as install,
    ):
        otel_mod.init_otel(cfg)
    install.assert_not_called()
    assert any("HONEYCOMB_API_KEY" in r.message for r in caplog.records)


def test_init_otel_enabled_with_key_installs_provider(monkeypatch):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "test-key")
    cfg = _config()
    # Reset the initialized state in case prior tests touched it
    monkeypatch.setattr(otel_mod, "_INITIALIZED", False)
    with (
        patch.object(otel_mod, "_install_provider") as install,
        patch.object(otel_mod, "_register_auto_instrumentation") as auto,
    ):
        otel_mod.init_otel(cfg)
    install.assert_called_once()
    auto.assert_called_once()


def test_init_otel_swallows_install_failure(monkeypatch, caplog):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "test-key")
    monkeypatch.setattr(otel_mod, "_INITIALIZED", False)
    cfg = _config()
    with (
        patch.object(otel_mod, "_install_provider", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.ERROR),
    ):
        otel_mod.init_otel(cfg)  # must not raise
    assert any("init_otel failed" in r.message for r in caplog.records)


def test_shutdown_otel_is_idempotent_when_uninitialized(monkeypatch):
    # Without ever calling init_otel, shutdown_otel must not raise.
    monkeypatch.setattr(otel_mod, "_PROVIDER", None)
    monkeypatch.setattr(otel_mod, "_INITIALIZED", False)
    otel_mod.shutdown_otel()


def test_init_otel_redacts_api_key_from_logs(monkeypatch, caplog):
    monkeypatch.setenv("HONEYCOMB_API_KEY", "secret-not-to-log")
    monkeypatch.setattr(otel_mod, "_INITIALIZED", False)
    cfg = _config()
    with (
        caplog.at_level(logging.INFO),
        patch.object(otel_mod, "_install_provider"),
        patch.object(otel_mod, "_register_auto_instrumentation"),
    ):
        otel_mod.init_otel(cfg)
    for record in caplog.records:
        assert "secret-not-to-log" not in record.getMessage()


def test_main_calls_init_otel_after_sentry(monkeypatch):
    """server.main() must call init_otel after _init_sentry."""
    from unittest.mock import MagicMock

    from src import server

    call_order: list[str] = []

    def _fake_sentry():
        call_order.append("sentry")

    def _fake_otel(cfg):
        call_order.append("otel")

    monkeypatch.setattr(server, "_init_sentry", _fake_sentry)
    monkeypatch.setattr("src.telemetry.otel.init_otel", _fake_otel)

    # Stub out everything in main() that does real I/O
    fake_config = MagicMock()
    fake_config.dashboard_enabled = False
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr("src.server.load_runtime_config", lambda: fake_config)
    monkeypatch.setattr("src.server.setup_logging", lambda *a, **kw: None)
    import asyncio as _asyncio

    def _fake_asyncio_run(coro, **kw):
        # Close the coroutine to avoid "never awaited" warnings.
        coro.close()

    monkeypatch.setattr(_asyncio, "run", _fake_asyncio_run)

    server.main()
    assert call_order == ["sentry", "otel"]
