"""Tests for knowledge-system in-memory metric counters."""

from __future__ import annotations

import pytest

from knowledge_metrics import KnowledgeMetrics


def test_metrics_starts_at_zero():
    m = KnowledgeMetrics()
    snap = m.snapshot()
    assert snap["wiki_entries_ingested"] == 0
    assert snap["wiki_supersedes"] == 0
    assert snap["tribal_promotions"] == 0
    assert snap["adr_drafts_judged"] == 0
    assert snap["adr_drafts_opened"] == 0
    assert snap["reflections_bridged"] == 0


def test_increment_is_independent_across_counters():
    m = KnowledgeMetrics()
    m.increment("wiki_supersedes", 3)
    m.increment("tribal_promotions", 1)
    snap = m.snapshot()
    assert snap["wiki_supersedes"] == 3
    assert snap["tribal_promotions"] == 1
    assert snap["wiki_entries_ingested"] == 0


def test_default_increment_is_one():
    m = KnowledgeMetrics()
    m.increment("wiki_supersedes")
    m.increment("wiki_supersedes")
    assert m.snapshot()["wiki_supersedes"] == 2


def test_unknown_counter_raises():
    m = KnowledgeMetrics()
    with pytest.raises(KeyError):
        m.increment("nonexistent_counter")


def test_module_level_metrics_singleton_is_shared():
    """Callers should import ``metrics`` and share state."""
    from knowledge_metrics import metrics as m1
    from knowledge_metrics import metrics as m2

    assert m1 is m2


def test_reset_zeroes_all_counters():
    m = KnowledgeMetrics()
    m.increment("wiki_supersedes", 5)
    m.reset()
    snap = m.snapshot()
    assert all(v == 0 for v in snap.values())
