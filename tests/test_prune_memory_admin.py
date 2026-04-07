"""Tests for the prune-memory admin task."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class _FakeResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def _fake_config(tmp_path):
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(repo_root=tmp_path)


def _make_judge(*judge_responses):
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.side_effect = [_FakeResult(stdout=r) for r in judge_responses]
    cfg = MagicMock()
    cfg.background_tool = "claude"
    cfg.memory_judge_model = "haiku"
    cfg.agent_timeout = 60
    return MemoryJudge(config=cfg, runner=runner, threshold=0.7)


@pytest.mark.asyncio
async def test_prune_memory_archives_failures_keeps_survivors(tmp_path):
    from admin_tasks import run_prune_memory

    cfg = _fake_config(tmp_path)
    items_path = cfg.memory_dir / "items.jsonl"
    items_path.parent.mkdir(parents=True, exist_ok=True)
    items_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "keep",
                        "principle": "Keep me — durable architectural rule.",
                        "rationale": "Captured after a real production incident.",
                        "failure_mode": "Future agents repeat the mistake.",
                        "scope": "all",
                        "schema_version": 1,
                    }
                ),
                json.dumps(
                    {
                        "id": "drop",
                        "principle": "Drop me — trivial implementation detail.",
                        "rationale": "Just changed a variable name.",
                        "failure_mode": "Nothing happens.",
                        "scope": "src/foo.py",
                        "schema_version": 1,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    judge = _make_judge(
        '{"score": 0.9, "verdict": "accept", "reason": "good"}',
        '{"score": 0.1, "verdict": "reject", "reason": "noise"}',
    )

    result = await run_prune_memory(cfg, judge=judge)

    assert result.success is True
    surviving = items_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(surviving) == 1
    assert json.loads(surviving[0])["id"] == "keep"

    archive_path = cfg.memory_dir / "items_archive.jsonl"
    archive_lines = archive_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(archive_lines) == 1
    archived = json.loads(archive_lines[0])
    assert archived["id"] == "drop"
    assert archived["judge_score"] == 0.1
    assert "noise" in archived["judge_reason"]


@pytest.mark.asyncio
async def test_prune_memory_archives_legacy_v0_items(tmp_path):
    """Pre-tribal items with no `principle` field go straight to archive."""
    from admin_tasks import run_prune_memory

    cfg = _fake_config(tmp_path)
    items_path = cfg.memory_dir / "items.jsonl"
    items_path.parent.mkdir(parents=True, exist_ok=True)
    items_path.write_text(
        json.dumps(
            {
                "id": "legacy",
                "title": "Old format",
                "learning": "Pre-tribal schema",
                "context": "From before the rollout",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Judge should never be called for legacy items.
    judge = _make_judge()  # no responses queued

    result = await run_prune_memory(cfg, judge=judge)

    assert result.success is True
    surviving = items_path.read_text(encoding="utf-8")
    assert surviving == ""

    archive_path = cfg.memory_dir / "items_archive.jsonl"
    archive_lines = archive_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(archive_lines) == 1
    archived = json.loads(archive_lines[0])
    assert archived["id"] == "legacy"
    assert archived["judge_reason"] == "pre-tribal schema"


@pytest.mark.asyncio
async def test_prune_memory_no_items_file_succeeds(tmp_path):
    from admin_tasks import run_prune_memory

    cfg = _fake_config(tmp_path)
    judge = _make_judge()

    result = await run_prune_memory(cfg, judge=judge)

    assert result.success is True
    assert any("nothing to prune" in line.lower() for line in result.log)


@pytest.mark.asyncio
async def test_prune_memory_handles_concatenated_pretty_printed_legacy_format(tmp_path):
    """Real-world legacy items.jsonl files are concatenated pretty-printed
    JSON, not one-object-per-line. The streaming raw_decode parser must
    handle both formats."""
    from admin_tasks import run_prune_memory

    cfg = _fake_config(tmp_path)
    items_path = cfg.memory_dir / "items.jsonl"
    items_path.parent.mkdir(parents=True, exist_ok=True)
    items_path.write_text(
        # Two pretty-printed legacy objects, no compact-line separator.
        json.dumps(
            {
                "id": "mem-aaaa",
                "title": "Old format A",
                "learning": "Pre-tribal lesson A",
                "context": "From #1234",
            },
            indent=2,
        )
        + "\n"
        + json.dumps(
            {
                "id": "mem-bbbb",
                "title": "Old format B",
                "learning": "Pre-tribal lesson B",
                "context": "From #5678",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    judge = _make_judge()  # judge should never be called for legacy items
    result = await run_prune_memory(cfg, judge=judge)

    assert result.success is True
    archive_path = cfg.memory_dir / "items_archive.jsonl"
    archived = archive_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(archived) == 2
    ids = {json.loads(line)["id"] for line in archived}
    assert ids == {"mem-aaaa", "mem-bbbb"}
    # All survivors should be gone (they were all legacy).
    assert items_path.read_text(encoding="utf-8") == ""
    # Log should reflect 2 legacy items archived.
    assert any("legacy_v0=2" in line for line in result.log)
