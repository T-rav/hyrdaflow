"""Tests for context_cache.py."""

from __future__ import annotations

from context_cache import ContextSectionCache
from tests.helpers import ConfigFactory


class TestContextSectionCache:
    def test_hits_cache_when_source_unchanged(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        cache = ContextSectionCache(config)
        source = config.data_path("memory", "manifest.md")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("manifest v1")

        calls = {"count": 0}

        def loader(_cfg):
            calls["count"] += 1
            return "manifest payload"

        content1, hit1 = cache.get_or_load(
            key="manifest", source_path=source, loader=loader
        )
        content2, hit2 = cache.get_or_load(
            key="manifest", source_path=source, loader=loader
        )

        assert content1 == "manifest payload"
        assert content2 == "manifest payload"
        assert hit1 is False
        assert hit2 is True
        assert calls["count"] == 1

    def test_cache_invalidates_when_source_changes(self, tmp_path):
        config = ConfigFactory.create(repo_root=tmp_path)
        cache = ContextSectionCache(config)
        source = config.data_path("memory", "digest.md")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("digest v1")

        calls = {"count": 0}

        def loader(_cfg):
            calls["count"] += 1
            return f"payload-{calls['count']}"

        content1, hit1 = cache.get_or_load(
            key="memory_digest", source_path=source, loader=loader
        )
        source.write_text("digest v2")
        content2, hit2 = cache.get_or_load(
            key="memory_digest", source_path=source, loader=loader
        )

        assert hit1 is False
        assert hit2 is False
        assert content1 == "payload-1"
        assert content2 == "payload-2"
        assert calls["count"] == 2
