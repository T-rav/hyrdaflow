"""Tests for shadow-corpus registration at orchestrator startup (#8786).

``build_services`` always installs a ShadowCorpus-backed sampler so every
gh/git/docker/claude subprocess call feeds the corpus that
``LiveCorpusReplayLoop`` consumes. The pipeline is unconditional —
``shadow_corpus_max_per_adapter`` is the only operator knob.

We don't run the full registry build here (heavy); instead we exercise the
same fragment in isolation, matching the pattern in service_registry where
the shadow-corpus install lives right after ``configure_gh_concurrency``.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

import subprocess_util


@pytest.fixture(autouse=True)
def _reset_sampler() -> Generator[None, None, None]:
    """Each test starts/ends with no sampler installed."""
    subprocess_util.set_shadow_sampler(None)
    yield
    subprocess_util.set_shadow_sampler(None)


def _apply_registration(config) -> None:  # noqa: ANN001
    """Mirror the registration block from service_registry.build_services."""
    from contracts.shadow import ShadowCorpus
    from subprocess_util import set_shadow_sampler

    corpus = ShadowCorpus(
        config.data_root / "contract_shadow",
        max_per_adapter=config.shadow_corpus_max_per_adapter,
    )
    set_shadow_sampler(corpus.record)


def _config(tmp_path: Path, **overrides):  # noqa: ANN201
    from config import HydraFlowConfig

    return HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **overrides,
    )


def test_registration_installs_sampler(tmp_path: Path) -> None:
    """Default config installs a working ShadowCorpus.record sampler."""
    config = _config(tmp_path)
    _apply_registration(config)
    assert subprocess_util._shadow_sampler is not None

    sampler = subprocess_util._shadow_sampler
    path = sampler(
        adapter="git",
        command="git",
        args=["status"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    assert isinstance(path, Path)
    assert path.parent == config.data_root / "contract_shadow" / "git"


def test_max_per_adapter_propagates_to_corpus(tmp_path: Path) -> None:
    """The config knob actually controls the LRU cap."""
    config = _config(tmp_path, shadow_corpus_max_per_adapter=11)
    _apply_registration(config)

    # Write 12 distinct shapes; only 11 should survive.
    sampler = subprocess_util._shadow_sampler
    assert sampler is not None
    for i in range(12):
        sampler(
            adapter="git",
            command="git",
            args=["log", "--oneline", "-n", str(i)],
            stdout="",
            stderr="",
            exit_code=0,
        )
    git_dir = config.data_root / "contract_shadow" / "git"
    surviving = list(git_dir.glob("*.yaml"))
    assert len(surviving) == 11
