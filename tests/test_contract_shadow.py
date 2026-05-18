"""Unit tests for the live-shadow corpus (Phase 0 of #8786).

The shadow corpus captures real subprocess interactions (gh/git/docker/claude)
so a follow-up ``LiveCorpusReplayLoop`` can diff them against fake-adapter
outputs without needing a sandbox repo. This file pins the storage shape,
normalizer + PII contracts, and LRU behaviour — wiring into
``subprocess_util.run_subprocess`` lives in a separate PR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Storage shape
# ---------------------------------------------------------------------------


def test_record_creates_yaml_at_adapter_subdir(tmp_path: Path) -> None:
    """One sample per (adapter, command, args) lives at
    ``<root>/<adapter>/<call_hash>.yaml`` so the corpus is easy to enumerate."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state,mergeable"],
        stdout='{"state":"OPEN","mergeable":"MERGEABLE"}\n',
        stderr="",
        exit_code=0,
    )
    assert path is not None
    assert path.parent == tmp_path / "github"
    assert path.suffix == ".yaml"
    assert path.exists()


def test_record_round_trips_via_yaml(tmp_path: Path) -> None:
    """The persisted YAML matches the documented schema (adapter/command/args/
    output blocks) so a future replay loop can load and dispatch."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="git",
        command="git",
        args=["commit", "-m", "test"],
        stdout="[main abc1234] test\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["adapter"] == "git"
    assert loaded["command"] == "git"
    assert loaded["args"] == ["commit", "-m", "test"]
    assert loaded["output"]["exit_code"] == 0
    assert "stdout" in loaded["output"]


def test_record_rejects_unknown_adapter(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    with pytest.raises(ValueError, match="adapter"):
        corpus.record(
            adapter="bigquery",  # not one of github|git|docker|claude
            command="bq",
            args=["query"],
            stdout="",
            stderr="",
            exit_code=0,
        )


# ---------------------------------------------------------------------------
# Deterministic hashing — same call shape overwrites same file
# ---------------------------------------------------------------------------


def test_same_call_shape_overwrites_same_file(tmp_path: Path) -> None:
    """The call_hash is deterministic on (adapter, command, args). Two
    invocations of the same shape write to the same path — most recent
    wins. This is what makes the corpus bounded by call-shape variety
    rather than call frequency."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    first = corpus.record(
        adapter="git",
        command="git",
        args=["status", "--porcelain"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    second = corpus.record(
        adapter="git",
        command="git",
        args=["status", "--porcelain"],
        stdout=" M file.py\n",
        stderr="",
        exit_code=0,
    )
    assert first == second
    loaded = yaml.safe_load(second.read_text(encoding="utf-8"))
    assert loaded["output"]["stdout"] == " M file.py\n"


def test_distinct_args_produce_distinct_files(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    a = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    b = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "2"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    assert a != b


# ---------------------------------------------------------------------------
# Normalizers — collapse volatile fields before persisting
# ---------------------------------------------------------------------------


def test_record_applies_pr_number_normalizer(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout="https://github.com/org/repo/pull/42\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "<PR_NUMBER>" in loaded["output"]["stdout"]
    assert "/pull/42" not in loaded["output"]["stdout"]


def test_record_applies_iso8601_normalizer(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="github",
        command="gh",
        args=["issue", "view", "1"],
        stdout='{"updatedAt": "2026-05-13T01:23:45Z"}\n',
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "<ISO8601>" in loaded["output"]["stdout"]


def test_record_applies_sha_short_normalizer(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="git",
        command="git",
        args=["commit", "-m", "x"],
        stdout="[main 1a2b3c4] x\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "<SHORT_SHA>" in loaded["output"]["stdout"]


# ---------------------------------------------------------------------------
# PII scrub — defence in depth above normalizers
# ---------------------------------------------------------------------------


def test_record_scrubs_email_pii(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="git",
        command="git",
        args=["log", "-1"],
        stdout="Author: Jane Doe <jane.doe@example.com>\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    stdout = loaded["output"]["stdout"]
    assert "jane.doe@example.com" not in stdout
    assert "<EMAIL>" in stdout


def test_record_scrubs_github_token(tmp_path: Path) -> None:
    """A leaked PAT in stdout must be redacted before persistence."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="github",
        command="gh",
        args=["auth", "status"],
        stdout="Token: ghp_AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp1234\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    stdout = loaded["output"]["stdout"]
    assert "ghp_AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp1234" not in stdout
    assert "<GH_TOKEN>" in stdout


def test_record_scrubs_basic_auth_in_url(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="git",
        command="git",
        args=["remote", "-v"],
        stdout="origin\thttps://user:secrettoken@github.com/x/y.git (fetch)\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    stdout = loaded["output"]["stdout"]
    assert "secrettoken" not in stdout
    assert "<CREDS>" in stdout


# ---------------------------------------------------------------------------
# LRU bounding
# ---------------------------------------------------------------------------


def test_lru_evicts_oldest_when_over_limit(tmp_path: Path) -> None:
    """``max_per_adapter`` bounds total samples per adapter. Once the cap is
    hit, the next record evicts the least-recently-written sample."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path, max_per_adapter=3)
    paths: list[Path] = []
    for i in range(5):
        p = corpus.record(
            adapter="git",
            command="git",
            args=["log", "--oneline", "-n", str(i)],
            stdout="",
            stderr="",
            exit_code=0,
        )
        assert p is not None
        paths.append(p)

    # 5 distinct call shapes → 5 distinct files attempted. Only the most
    # recent 3 survive.
    surviving = list((tmp_path / "git").glob("*.yaml"))
    assert len(surviving) == 3, (
        f"expected 3 surviving samples after LRU eviction, got {len(surviving)}"
    )
    # The first two should be gone.
    assert paths[0] not in surviving
    assert paths[1] not in surviving
    # The last three should be present.
    for p in paths[2:]:
        assert p in surviving


def test_lru_is_per_adapter(tmp_path: Path) -> None:
    """One adapter hitting its cap must not evict samples from another."""
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path, max_per_adapter=2)
    git_p = corpus.record(
        adapter="git",
        command="git",
        args=["status"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    for i in range(3):
        corpus.record(
            adapter="github",
            command="gh",
            args=["pr", "view", str(i)],
            stdout="",
            stderr="",
            exit_code=0,
        )
    assert git_p is not None and git_p.exists()
    assert len(list((tmp_path / "github").glob("*.yaml"))) == 2


# ---------------------------------------------------------------------------
# Enumeration / loading
# ---------------------------------------------------------------------------


def test_list_filters_by_adapter(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    corpus.record(
        adapter="git",
        command="git",
        args=["status"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    git_paths = corpus.list(adapter="git")
    assert len(git_paths) == 1
    assert git_paths[0].parent.name == "git"
    all_paths = corpus.list()
    assert len(all_paths) == 2


def test_load_round_trips_a_sample(tmp_path: Path) -> None:
    from contracts.shadow import ShadowCorpus

    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter="git",
        command="git",
        args=["status", "--porcelain"],
        stdout=" M src/x.py\n",
        stderr="",
        exit_code=0,
    )
    assert path is not None
    sample = corpus.load(path)
    assert sample.adapter == "git"
    assert sample.command == "git"
    assert sample.args == ["status", "--porcelain"]
    assert sample.exit_code == 0
    assert sample.stdout == " M src/x.py\n"
