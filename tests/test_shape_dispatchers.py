"""Unit tests for the Pydantic shape dispatcher (Phase 5 of #8786)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_validator


def _sample(
    tmp_path: Path,
    *,
    args: list[str],
    stdout: str,
    adapter: str = "github",
    command: str = "gh",
):
    """Helper: record a sample to a temp corpus and return the loaded view."""
    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter=adapter,
        command=command,
        args=args,
        stdout=stdout,
        stderr="",
        exit_code=0,
    )
    assert path is not None
    return corpus.load(path)


@pytest.mark.asyncio
async def test_valid_pr_summary_returns_none(tmp_path: Path) -> None:
    """A well-shaped gh pr list payload validates cleanly → None (no drift)."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps(
            [
                {"number": 1, "title": "x", "state": "OPEN"},
                {"number": 2, "title": "y", "state": "MERGED"},
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_drifted_pr_state_enum_returns_diff(tmp_path: Path) -> None:
    """A new gh state value not in the Literal trips validation → drift dict."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "x", "state": "QUEUED"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True
    assert result["shape"] == "GhPRSummary"
    assert result["failure_count"] == 1


@pytest.mark.asyncio
async def test_pr_view_picks_detail_shape(tmp_path: Path) -> None:
    """``--json mergeable,headRefName`` is the detail-shape signal."""
    sample = _sample(
        tmp_path,
        args=[
            "pr",
            "view",
            "42",
            "--json",
            "number,headRefName,baseRefName,mergeable",
        ],
        stdout=json.dumps(
            {
                "number": 42,
                "headRefName": "feat/x",
                "baseRefName": "staging",
                "mergeable": "MERGEABLE",
            }
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_drifted_mergeable_enum(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42", "--json", "number,mergeable"],
        stdout=json.dumps({"number": 42, "mergeable": "PROBABLY"}) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhPRDetail"


@pytest.mark.asyncio
async def test_issue_view_validates_against_issue_summary(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["issue", "view", "7", "--json", "number,state,stateReason"],
        stdout=json.dumps({"number": 7, "state": "CLOSED", "stateReason": "completed"})
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_non_gh_adapter_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        adapter="git",
        command="git",
        args=["commit", "-m", "x"],
        stdout="[main abc1234] x\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_no_json_flag_skipped(tmp_path: Path) -> None:
    """Plain ``gh pr view 42`` (no --json) returns human text, not validated."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "42"],
        stdout="title: x\nstate: open\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_empty_stdout_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number"],
        stdout="",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_non_json_stdout_skipped(tmp_path: Path) -> None:
    """Subcommand says --json but stdout is malformed — skip rather than fail
    loudly. A real recorder bug would surface elsewhere."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number"],
        stdout="not actually json\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_unknown_subcommand_skipped(tmp_path: Path) -> None:
    sample = _sample(
        tmp_path,
        args=["api", "graphql", "--json", "data"],
        stdout='{"data": {}}\n',
    )
    assert await gh_shape_validator(sample) is None
