"""EventuallyConsistent — delays visibility of writes for N subsequent reads."""

from __future__ import annotations

from mockworld.fakes.fake_github import FakeGitHub
from tests.scenarios.behaviors.eventual_consistency import EventuallyConsistent


async def test_write_visible_after_N_reads() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "A", "body")
    wrapped = EventuallyConsistent(
        gh, delay_reads=2, watch_writes=["add_labels"], watch_reads=["issue"]
    )
    # Stage a "write" via the pass-through then assert stale views for N reads.
    await wrapped.add_labels(1, ["fresh"])
    # Immediate reads see stale state (0 labels before "fresh").
    snap1 = wrapped.issue(1)
    snap2 = wrapped.issue(1)
    # After N (2) stale reads, the label is visible.
    snap3 = wrapped.issue(1)
    assert "fresh" not in snap1.labels
    assert "fresh" not in snap2.labels
    assert "fresh" in snap3.labels


def test_unwatched_methods_pass_through() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "A", "body")
    wrapped = EventuallyConsistent(gh, delay_reads=2, watch_writes=[], watch_reads=[])
    # No methods watched: behaves identical to underlying.
    assert wrapped.issue(1).title == "A"
