"""Tests for hindsight_types — shared types extracted to break circular imports."""

from __future__ import annotations

from hindsight_types import Bank, HindsightMemory, WALEntry


class TestBank:
    """Bank enum tests."""

    def test_bank_values(self) -> None:
        assert Bank.LEARNINGS == "hydraflow-learnings"
        assert Bank.RETROSPECTIVES == "hydraflow-retrospectives"
        assert Bank.REVIEW_INSIGHTS == "hydraflow-review-insights"
        assert Bank.HARNESS_INSIGHTS == "hydraflow-harness-insights"
        assert Bank.TROUBLESHOOTING == "hydraflow-troubleshooting"
        assert Bank.TRACING_INSIGHTS == "hydraflow-tracing-insights"

    def test_bank_is_str(self) -> None:
        assert isinstance(Bank.LEARNINGS, str)


class TestHindsightMemory:
    """HindsightMemory model tests."""

    def test_defaults(self) -> None:
        mem = HindsightMemory()
        assert mem.content == ""
        assert mem.text == ""
        assert mem.context == ""
        assert mem.metadata == {}
        assert mem.relevance_score == 0.0
        assert mem.timestamp == ""

    def test_display_text_prefers_text(self) -> None:
        mem = HindsightMemory(text="from text", content="from content")
        assert mem.display_text == "from text"

    def test_display_text_falls_back_to_content(self) -> None:
        mem = HindsightMemory(text="", content="from content")
        assert mem.display_text == "from content"

    def test_serialization_roundtrip(self) -> None:
        mem = HindsightMemory(
            content="c", text="t", context="ctx", relevance_score=0.9, timestamp="ts"
        )
        data = mem.model_dump()
        restored = HindsightMemory.model_validate(data)
        assert restored == mem


class TestWALEntry:
    """WALEntry model tests."""

    def test_defaults(self) -> None:
        entry = WALEntry(bank="b", content="c")
        assert entry.bank == "b"
        assert entry.content == "c"
        assert entry.context == ""
        assert entry.metadata == {}
        assert entry.retries == 0
        assert entry.created_at  # non-empty ISO timestamp

    def test_serialization_roundtrip(self) -> None:
        entry = WALEntry(bank="b", content="c", context="ctx", metadata={"k": "v"})
        data = entry.model_dump()
        restored = WALEntry.model_validate(data)
        assert restored == entry


class TestNoCircularImport:
    """Verify the circular import is broken."""

    def test_import_hindsight_then_wal(self) -> None:
        """Importing hindsight followed by hindsight_wal must succeed."""
        import hindsight  # noqa: PLC0415
        import hindsight_wal  # noqa: PLC0415

        assert hasattr(hindsight, "Bank")
        assert hasattr(hindsight_wal, "WALEntry")

    def test_import_wal_then_hindsight(self) -> None:
        """Importing hindsight_wal followed by hindsight must succeed."""
        import hindsight  # noqa: PLC0415
        import hindsight_wal  # noqa: PLC0415

        assert hasattr(hindsight_wal, "WALEntry")
        assert hasattr(hindsight, "Bank")

    def test_reexports_from_hindsight(self) -> None:
        """Bank, HindsightMemory, WALEntry are re-exported from hindsight."""
        from hindsight import Bank as B  # noqa: PLC0415
        from hindsight import HindsightMemory as HM  # noqa: PLC0415
        from hindsight import WALEntry as WE  # noqa: PLC0415

        assert B is Bank
        assert HM is HindsightMemory
        assert WE is WALEntry

    def test_reexport_from_wal(self) -> None:
        """WALEntry is re-exported from hindsight_wal."""
        from hindsight_wal import WALEntry as WE  # noqa: PLC0415

        assert WE is WALEntry
