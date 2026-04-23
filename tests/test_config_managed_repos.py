"""Tests for the ManagedRepo config model + managed_repos field + JSON env override."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig, ManagedRepo, _apply_env_overrides


def test_managed_repo_defaults():
    repo = ManagedRepo(slug="acme/widget")
    assert repo.slug == "acme/widget"
    assert repo.staging_branch == "staging"
    assert repo.main_branch == "main"
    assert repo.labels_namespace == ""
    assert repo.enabled is True


def test_managed_repo_rejects_bad_slug():
    with pytest.raises(ValueError):
        ManagedRepo(slug="not-a-slug")


def test_hydraflow_config_has_managed_repos_field():
    cfg = HydraFlowConfig()
    assert cfg.managed_repos == []


def test_hydraflow_managed_repos_json_env_override():
    payload = '[{"slug":"acme/widget","enabled":false}]'
    with patch.dict(os.environ, {"HYDRAFLOW_MANAGED_REPOS": payload}):
        cfg = HydraFlowConfig()
        _apply_env_overrides(cfg)
    assert len(cfg.managed_repos) == 1
    assert cfg.managed_repos[0].slug == "acme/widget"
    assert cfg.managed_repos[0].enabled is False


def test_hydraflow_principles_audit_interval_default():
    cfg = HydraFlowConfig()
    assert cfg.principles_audit_interval == 604800
