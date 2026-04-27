"""In-memory fake of ``src/wiki_compiler.py:WikiCompiler`` for scenario tests.

Records every ``compile_topic_tracked`` invocation and returns a
configurable number of compiled entries. Never invokes an LLM.

Scenario tests exercising the post-merge wiki-compile hook
(PR #8400 / ``post_merge_handler._compile_tracked_topics_for_merge``)
and the RepoWikiLoop's on-demand compile assert on
``.compile_calls`` to verify the right topics were picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CompileCall:
    """One invocation of ``compile_topic_tracked``."""

    tracked_root: Path
    repo: str
    topic: str


@dataclass
class FakeWikiCompiler:
    """Drop-in replacement for WikiCompiler in scenario tests.

    Implements the methods PostMergeHandler and RepoWikiLoop actually
    call (the rest raise AttributeError on access so missed wiring is
    loud).
    """

    compile_calls: list[CompileCall] = field(default_factory=list)
    compiled_entries_per_call: int = 1

    async def compile_topic_tracked(
        self,
        *,
        tracked_root: Path,
        repo: str,
        topic: str,
    ) -> int:
        self.compile_calls.append(
            CompileCall(tracked_root=tracked_root, repo=repo, topic=topic)
        )
        return self.compiled_entries_per_call

    async def compile_topic(self, *args, **kwargs) -> int:
        """Legacy topic-page compile — return 0 to indicate no change."""
        return 0

    async def detect_contradictions(self, *args, **kwargs):
        """Ingest-time contradiction detector — never flags anything in fakes."""

        class _Empty:
            contradicts: list = []

        return _Empty()

    async def dedup_or_corroborate(self, **kwargs):
        """Corroboration decision stub.

        Default is 'no match' so scenarios exercise the normal write
        path. Tests that need corroboration to fire should assign
        ``fake.dedup_decision = CorroborationDecision(...)`` before
        running the tick.
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        return getattr(self, "dedup_decision", CorroborationDecision())
