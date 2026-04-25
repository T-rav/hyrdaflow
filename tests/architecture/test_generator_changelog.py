from arch._models import CommitInfo
from arch.generators.changelog import render_changelog


def test_groups_by_iso_week_descending():
    commits = [
        CommitInfo(sha="aaa1111", iso_date="2026-04-01", subject="early thing"),
        CommitInfo(
            sha="bbb2222", iso_date="2026-04-20", subject="recent thing", pr_number=42
        ),
    ]
    md = render_changelog(commits)
    pos_late = md.index("recent thing")
    pos_early = md.index("early thing")
    assert pos_late < pos_early  # newest first
    assert "(#42)" in md or "PR #42" in md


def test_handles_empty_input():
    md = render_changelog([])
    assert "no recent" in md.lower() or "_(empty" in md
