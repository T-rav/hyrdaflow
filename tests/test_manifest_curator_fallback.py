"""Tests for CuratedManifestStore fallback read path."""

from __future__ import annotations

import json

import pytest

from config import HydraFlowConfig
from manifest_curator import CuratedManifestStore


@pytest.fixture
def manifest_store(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
    return CuratedManifestStore(config)


def test_read_for_prompt_returns_empty_when_no_file(manifest_store):
    assert manifest_store.read_for_prompt() == ""


def test_read_for_prompt_returns_formatted_content(manifest_store):
    payload = {
        "overview": "HydraFlow automates the issue lifecycle",
        "key_services": ["orchestrator", "planner"],
        "standards": ["Always run lint"],
        "architecture": [],
        "source_count": 3,
        "updated_at": "2026-03-26T00:00:00Z",
    }
    manifest_store._path.parent.mkdir(parents=True, exist_ok=True)
    manifest_store._path.write_text(json.dumps(payload))

    result = manifest_store.read_for_prompt()
    assert "HydraFlow automates" in result
    assert "orchestrator" in result


def test_read_for_prompt_respects_max_chars(manifest_store):
    payload = {
        "overview": "A" * 5000,
        "key_services": [],
        "standards": [],
        "architecture": [],
        "source_count": 1,
        "updated_at": "2026-03-26T00:00:00Z",
    }
    manifest_store._path.parent.mkdir(parents=True, exist_ok=True)
    manifest_store._path.write_text(json.dumps(payload))

    result = manifest_store.read_for_prompt(max_chars=100)
    assert len(result) <= 100
