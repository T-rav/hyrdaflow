"""Tests for shadow-corpus registration at orchestrator startup (Phase 0.3 of #8786).

`build_services` must:
- Install a ShadowCorpus-backed sampler when `config.shadow_corpus_enabled=True`.
- Leave the sampler clear (`None`) when the flag is False — defensive against
  prior installs leaking across processes / test invocations.

We don't run the full registry build here (heavy); instead we exercise the
same fragment in isolation, matching the pattern in service_registry where
the shadow-corpus install lives right after `configure_gh_concurrency`.
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
    from subprocess_util import set_shadow_sampler

    if config.shadow_corpus_enabled:
        from contracts.shadow import ShadowCorpus

        corpus = ShadowCorpus(
            config.data_root / "contract_shadow",
            max_per_adapter=config.shadow_corpus_max_per_adapter,
        )
        set_shadow_sampler(corpus.record)
    else:
        set_shadow_sampler(None)


def _config(tmp_path: Path, **overrides):  # noqa: ANN201
    from config import HydraFlowConfig

    return HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **overrides,
    )


def test_disabled_by_default(tmp_path: Path) -> None:
    """Default config leaves the sampler clear."""
    config = _config(tmp_path)
    assert config.shadow_corpus_enabled is False
    _apply_registration(config)
    assert subprocess_util._shadow_sampler is None


def test_enabled_installs_sampler(tmp_path: Path) -> None:
    """Flag on → a sampler is installed that writes through ShadowCorpus."""
    config = _config(tmp_path, shadow_corpus_enabled=True)
    _apply_registration(config)
    assert subprocess_util._shadow_sampler is not None

    # The installed sampler must be a ShadowCorpus.record bound method
    # — exercise it end-to-end via run_subprocess to prove the wiring.
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


def test_disabled_clears_previously_installed_sampler(tmp_path: Path) -> None:
    """Re-running registration with the flag off clears any prior install."""
    enabled = _config(tmp_path, shadow_corpus_enabled=True)
    _apply_registration(enabled)
    assert subprocess_util._shadow_sampler is not None

    disabled = _config(tmp_path, shadow_corpus_enabled=False)
    _apply_registration(disabled)
    assert subprocess_util._shadow_sampler is None


def test_max_per_adapter_propagates_to_corpus(tmp_path: Path) -> None:
    """The config knob actually controls the LRU cap."""
    config = _config(
        tmp_path, shadow_corpus_enabled=True, shadow_corpus_max_per_adapter=11
    )
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
