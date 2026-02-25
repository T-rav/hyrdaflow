from __future__ import annotations

from pathlib import Path

from hf_cli import __main__ as cli_main
from hf_cli.update_check import UpdateCheckResult


def test_entrypoint_version_prints_current_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_main, "get_app_version", lambda: "0.9.0")

    cli_main.entrypoint(["version"])

    out = capsys.readouterr().out
    assert "hydraflow 0.9.0" in out


def test_entrypoint_check_update_prints_available(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_main,
        "check_for_updates",
        lambda: UpdateCheckResult(
            current_version="0.9.0",
            latest_version="0.9.1",
            update_available=True,
            error=None,
        ),
    )

    cli_main.entrypoint(["check-update"])

    out = capsys.readouterr().out
    assert "Update available: 0.9.0 -> 0.9.1" in out


def test_entrypoint_check_update_prints_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_main,
        "check_for_updates",
        lambda: UpdateCheckResult(
            current_version="0.9.0",
            latest_version=None,
            update_available=False,
            error="network down",
        ),
    )

    cli_main.entrypoint(["check-update"])

    out = capsys.readouterr().out
    assert "Update check failed: network down" in out


def test_run_prints_update_notice_when_available(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cli_main, "ensure_running", lambda: None)
    monkeypatch.setattr(
        cli_main,
        "add_repo",
        lambda _path: {"dashboard_url": "http://localhost:9000", "started": True},
    )
    monkeypatch.setattr(
        cli_main,
        "check_for_updates_cached",
        lambda: UpdateCheckResult(
            current_version="0.9.0",
            latest_version="0.9.1",
            update_available=True,
            error=None,
        ),
    )

    cli_main.entrypoint(["run", str(repo)])

    out = capsys.readouterr().out
    assert "Notice: hydraflow 0.9.1 is available (current 0.9.0)." in out


def test_run_skips_update_check_when_flag_present(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cli_main, "ensure_running", lambda: None)
    monkeypatch.setattr(
        cli_main,
        "add_repo",
        lambda _path: {"dashboard_url": "http://localhost:9000", "started": True},
    )
    monkeypatch.setattr(
        cli_main,
        "check_for_updates_cached",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected update check")),
    )

    cli_main.entrypoint(["run", str(repo), "--no-update-check"])

    out = capsys.readouterr().out
    assert "Registered repo" in out
