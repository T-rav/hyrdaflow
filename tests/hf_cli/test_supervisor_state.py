from __future__ import annotations

import importlib
import json
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


def test_get_repo_by_path(tmp_path, monkeypatch):
    supervisor_state = _load_state_module(tmp_path, monkeypatch)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    supervisor_state.upsert_repo(repo_path, "repo-slug", 5555, "/logs/repo.log")

    stored = supervisor_state.get_repo(path=repo_path)
    assert stored is not None
    assert stored["slug"] == "repo-slug"


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


def test_list_repos_returns_empty_on_invalid_json(tmp_path, monkeypatch):
    supervisor_state = _load_state_module(tmp_path, monkeypatch)
    supervisor_state.SUPERVISOR_STATE_FILE.write_text("{bad json")

    assert supervisor_state.list_repos() == []


def test_upsert_updates_existing_entry(tmp_path, monkeypatch):
    supervisor_state = _load_state_module(tmp_path, monkeypatch)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    supervisor_state.upsert_repo(repo_path, "repo-slug", 5555, "/logs/repo.log")
    supervisor_state.upsert_repo(repo_path, "repo-slug-v2", 6000, "/logs/repo-v2.log")
    data = json.loads(supervisor_state.SUPERVISOR_STATE_FILE.read_text())

    assert len(data["repos"]) == 1
    assert data["repos"][0]["slug"] == "repo-slug-v2"
    assert data["repos"][0]["port"] == 6000
