from datetime import UTC, datetime, timedelta

from arch.freshness import FreshnessBadge, compute_badge, render_badge


def test_render_badge_emits_emoji_and_label():
    assert render_badge(FreshnessBadge.FRESH) == "Status: 🟢 fresh"
    assert render_badge(FreshnessBadge.SOURCE_MOVED) == "Status: 🟡 source-moved"
    assert render_badge(FreshnessBadge.STALE) == "Status: 🔴 stale"
    assert render_badge(FreshnessBadge.NOT_GENERATED) == "Status: 🔴 not yet generated"


def test_fresh_when_recent_and_source_unchanged():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    regen = (now - timedelta(hours=1)).isoformat()
    meta = {
        "artifacts": {"loops.md": {"source_sha": "aaa"}},
        "regenerated_at": regen,
    }
    badge = compute_badge("loops.md", meta=meta, current_source_sha="aaa", now=now)
    assert badge == FreshnessBadge.FRESH


def test_source_moved_when_sha_changed_recently():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    regen = (now - timedelta(hours=1)).isoformat()
    meta = {
        "artifacts": {"loops.md": {"source_sha": "aaa"}},
        "regenerated_at": regen,
    }
    badge = compute_badge("loops.md", meta=meta, current_source_sha="bbb", now=now)
    assert badge == FreshnessBadge.SOURCE_MOVED


def test_stale_when_older_than_seven_days():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    regen = (now - timedelta(days=10)).isoformat()
    meta = {
        "artifacts": {"loops.md": {"source_sha": "aaa"}},
        "regenerated_at": regen,
    }
    badge = compute_badge("loops.md", meta=meta, current_source_sha="aaa", now=now)
    assert badge == FreshnessBadge.STALE


def test_not_generated_when_meta_absent_or_missing_artifact():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    assert (
        compute_badge("loops.md", meta=None, current_source_sha="x", now=now)
        == FreshnessBadge.NOT_GENERATED
    )
    assert (
        compute_badge(
            "loops.md",
            meta={"artifacts": {}, "regenerated_at": now.isoformat()},
            current_source_sha="x",
            now=now,
        )
        == FreshnessBadge.NOT_GENERATED
    )
