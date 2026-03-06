from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
        "check_for_updates_cached",
        lambda **_kwargs: UpdateCheckResult(
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
        "check_for_updates_cached",
        lambda **_kwargs: UpdateCheckResult(
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
        lambda **_kwargs: UpdateCheckResult(
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
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected update check")
        ),
    )

    cli_main.entrypoint(["run", str(repo), "--no-update-check"])

    out = capsys.readouterr().out
    assert "Registered repo" in out


def test_update_uses_uv_tool_upgrade_first(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []

    def _run(cmd, check, **_kwargs):
        assert check is False
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", _run)

    cli_main.entrypoint(["update"])

    out = capsys.readouterr().out
    assert "Update complete via `uv tool upgrade hydraflow`." in out
    assert calls == [["uv", "tool", "upgrade", "hydraflow"]]


def test_update_falls_back_to_uv_pip(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []

    def _run(cmd, check, **_kwargs):
        assert check is False
        calls.append(cmd)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_main.subprocess, "run", _run)

    cli_main.entrypoint(["update"])

    out = capsys.readouterr().out
    assert "Tool upgrade failed; trying environment upgrade..." in out
    assert "Update complete via `uv pip install -U hydraflow`." in out
    assert calls == [
        ["uv", "tool", "upgrade", "hydraflow"],
        ["uv", "pip", "install", "-U", "hydraflow"],
    ]


def test_update_exits_nonzero_when_both_commands_fail(monkeypatch, capsys) -> None:
    def _run(_cmd, check, **_kwargs):
        assert check is False
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(cli_main.subprocess, "run", _run)

    try:
        cli_main.entrypoint(["update"])
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert exc.code == 1

    out = capsys.readouterr().out
    assert "Update failed. Try manually:" in out


def test_open_existing_repo_opens_dashboard(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cli_main, "ensure_running", lambda: None)
    monkeypatch.setattr(
        cli_main,
        "list_repos",
        lambda: [
            {
                "path": str(repo.resolve()),
                "slug": "repo",
                "dashboard_url": "http://localhost:9010",
            }
        ],
    )
    opened: list[str] = []
    monkeypatch.setattr(
        cli_main.webbrowser,
        "open",
        lambda url: opened.append(url) is None or True,
    )

    cli_main.entrypoint(["open", str(repo)])

    out = capsys.readouterr().out
    assert "Opened dashboard: http://localhost:9010" in out
    assert opened == ["http://localhost:9010"]


def test_open_registers_repo_when_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cli_main, "ensure_running", lambda: None)
    monkeypatch.setattr(cli_main, "list_repos", lambda: [])
    captured: dict[str, Path] = {}
    monkeypatch.setattr(
        cli_main,
        "add_repo",
        lambda path: (
            captured.__setitem__("path", path)
            or {"dashboard_url": "http://localhost:9020", "started": True}
        ),
    )
    opened: list[str] = []
    monkeypatch.setattr(
        cli_main.webbrowser,
        "open",
        lambda url: opened.append(url) is None or True,
    )

    cli_main.entrypoint(["open", str(repo)])

    out = capsys.readouterr().out
    assert "Opened dashboard: http://localhost:9020" in out
    assert captured["path"] == repo.resolve()
    assert opened == ["http://localhost:9020"]


def test_open_errors_when_browser_cannot_open(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cli_main, "ensure_running", lambda: None)
    monkeypatch.setattr(
        cli_main,
        "list_repos",
        lambda: [
            {
                "path": str(repo.resolve()),
                "slug": "repo",
                "dashboard_url": "http://localhost:9030",
            }
        ],
    )
    monkeypatch.setattr(cli_main.webbrowser, "open", lambda _url: False)

    try:
        cli_main.entrypoint(["open", str(repo)])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Could not open browser" in str(exc)
