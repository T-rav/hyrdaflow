from __future__ import annotations

from prompt_stats import build_prompt_stats, truncate_with_notice


def test_truncate_with_notice_returns_original_when_under_limit() -> None:
    value, before, after = truncate_with_notice("hello", 10)

    assert value == "hello"
    assert before == 5
    assert after == 5


def test_truncate_with_notice_appends_notice_when_trimmed() -> None:
    value, before, after = truncate_with_notice("abcdef", 4, label="History")

    assert value.startswith("abcd")
    assert "[History truncated at 4 chars]" in value
    assert before == 6
    assert after == len(value)


def test_build_prompt_stats_normalizes_and_tracks_pruned_chars() -> None:
    stats = build_prompt_stats(
        history_before=100,
        history_after=90,
        context_before=120,
        context_after=80,
        section_chars={" summary ": 22, "": 9, "ctx": -5},
    )

    assert stats["history_chars_before"] == 100
    assert stats["history_chars_after"] == 90
    assert stats["context_chars_before"] == 120
    assert stats["context_chars_after"] == 80
    assert stats["pruned_chars_total"] == 50
    assert stats["section_chars"] == {"summary": 22, "ctx": 0}


def test_truncate_with_notice_returns_empty_when_max_chars_non_positive() -> None:
    value, before, after = truncate_with_notice("abcdef", 0)

    assert value == ""
    assert before == 6
    assert after == 0


def test_build_prompt_stats_clamps_negative_inputs_to_zero() -> None:
    stats = build_prompt_stats(
        history_before=-10,
        history_after=-1,
        context_before=-9,
        context_after=-3,
    )

    assert stats["history_chars_before"] == 0
    assert stats["history_chars_after"] == 0
    assert stats["context_chars_before"] == 0
    assert stats["context_chars_after"] == 0
    assert stats["pruned_chars_total"] == 0
    assert "section_chars" not in stats
