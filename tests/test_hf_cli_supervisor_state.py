from __future__ import annotations

import importlib
from pathlib import Path


def _load_state_module(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYDRAFLOW_HOME", str(tmp_path / "hf-home"))
    import hf_cli.config as hf_config

    importlib.reload(hf_config)

    from hf_cli import supervisor_state

    importlib.reload(supervisor_state)
    state_file = tmp_path / "supervisor-state.json"
    monkeypatch.setattr(supervisor_state, "SUPERVISOR_STATE_FILE", state_file)
    return supervisor_state


def test_upsert_and_lookup_by_slug(tmp_path, monkeypatch):
    supervisor_state = _load_state_module(tmp_path, monkeypatch)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    supervisor_state.upsert_repo(repo_path, "repo-slug", 5555, "/logs/repo.log")

    stored = supervisor_state.get_repo(slug="repo-slug")
    assert stored is not None
    assert stored["slug"] == "repo-slug"
    assert stored["path"] == str(repo_path.resolve())
    assert stored["port"] == 5555


def test_remove_by_slug_and_path(tmp_path, monkeypatch):
    supervisor_state = _load_state_module(tmp_path, monkeypatch)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    supervisor_state.upsert_repo(repo_path, "repo-slug", 5555, "/logs/repo.log")
    second_path = tmp_path / "second"
    second_path.mkdir()
    supervisor_state.upsert_repo(second_path, "two", 6000, "/logs/two.log")

    assert supervisor_state.remove_repo(slug="repo-slug") is True
    assert supervisor_state.get_repo(slug="repo-slug") is None

    assert supervisor_state.remove_repo(path=repo_path) is False
    assert supervisor_state.remove_repo(path=second_path) is True
    assert supervisor_state.get_repo(slug="two") is None
