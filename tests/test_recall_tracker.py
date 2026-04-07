"""Tests for the recall_tracker — minimal data-collection layer for #6083."""

from __future__ import annotations

import json


def _fake_config(tmp_path):
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(repo_root=tmp_path)


def _make_memory(text: str, item_id: str = ""):
    from hindsight_types import HindsightMemory

    metadata = {"id": item_id} if item_id else {}
    return HindsightMemory(
        content=text, text=text, context="", metadata=metadata, relevance_score=0.5
    )


def test_log_recall_writes_record_with_item_ids(tmp_path):
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    memories = [
        _make_memory("first lesson", item_id="mem-aaaa"),
        _make_memory("second lesson", item_id="mem-bbbb"),
    ]

    log_recall(
        cfg,
        bank="hydraflow-tribal",
        query="how do background loops handle restart",
        memories=memories,
        source="base_runner",
    )

    path = cfg.data_path("memory", "recall_history.jsonl")
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["bank"] == "hydraflow-tribal"
    assert record["query"] == "how do background loops handle restart"
    assert record["item_count"] == 2
    assert record["item_ids"] == ["mem-aaaa", "mem-bbbb"]
    assert record["source"] == "base_runner"
    assert "timestamp" in record


def test_log_recall_logs_empty_recalls(tmp_path):
    """Empty recalls (zero memories returned) must still be logged so we can
    distinguish 'memory bank cold' from 'no queries running'."""
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    log_recall(
        cfg,
        bank="hydraflow-tribal",
        query="anything",
        memories=[],
        source="shape_phase",
    )

    path = cfg.data_path("memory", "recall_history.jsonl")
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["item_count"] == 0
    assert record["item_ids"] == []


def test_log_recall_truncates_long_queries(tmp_path):
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    long_query = "x" * 5000
    log_recall(
        cfg,
        bank="hydraflow-tribal",
        query=long_query,
        memories=[],
        source="base_runner",
    )

    path = cfg.data_path("memory", "recall_history.jsonl")
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert len(record["query"]) == 500


def test_log_recall_omits_missing_item_ids(tmp_path):
    """Memories without an `id` in metadata are counted but not enumerated."""
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    memories = [
        _make_memory("anonymous lesson"),  # no id
        _make_memory("named lesson", item_id="mem-cccc"),
    ]
    log_recall(
        cfg,
        bank="hydraflow-tribal",
        query="anything",
        memories=memories,
        source="base_runner",
    )

    path = cfg.data_path("memory", "recall_history.jsonl")
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["item_count"] == 2
    assert record["item_ids"] == ["mem-cccc"]


def test_log_recall_appends_multiple_recalls(tmp_path):
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    for i in range(3):
        log_recall(
            cfg,
            bank="hydraflow-tribal",
            query=f"query {i}",
            memories=[],
            source="base_runner",
        )

    path = cfg.data_path("memory", "recall_history.jsonl")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    queries = [json.loads(line)["query"] for line in lines]
    assert queries == ["query 0", "query 1", "query 2"]


def test_log_recall_swallows_oserror(tmp_path):
    """Recall logging must never raise — observability is best-effort."""
    from recall_tracker import log_recall

    cfg = _fake_config(tmp_path)
    # Make the parent dir read-only so the open() inside log_recall fails.
    target = cfg.data_path("memory")
    target.mkdir(parents=True, exist_ok=True)
    (target / "recall_history.jsonl").write_text("preexisting\n")
    target.chmod(0o444)

    try:
        # Should not raise.
        log_recall(
            cfg,
            bank="hydraflow-tribal",
            query="any",
            memories=[],
            source="base_runner",
        )
    finally:
        target.chmod(0o755)
