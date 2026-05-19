"""Fake adapters for MockWorld.

All Fakes here satisfy a Port protocol from src/ports.py. Production
code (server.py, orchestrator.py) does NOT import from this package —
only the sandbox entrypoint does.
"""

from mockworld.fakes.fake_agent import FakeAgent
from mockworld.fakes.fake_beads import FakeBeads
from mockworld.fakes.fake_bot_pr import FakeBotPR
from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_fs import FakeFS
from mockworld.fakes.fake_git import FakeGit
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_http import FakeHTTP
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
from mockworld.fakes.fake_issue_store import FakeIssueStore
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_review_insight_store import FakeReviewInsightStore
from mockworld.fakes.fake_sentry import FakeObservability, FakeSentry
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler
from mockworld.fakes.fake_workspace import FakeWorkspace

__all__ = [
    "FakeAgent",
    "FakeBeads",
    "FakeBotPR",
    "FakeClock",
    "FakeDocker",
    "FakeFS",
    "FakeGit",
    "FakeGitHub",
    "FakeHTTP",
    "FakeIssueFetcher",
    "FakeIssueStore",
    "FakeLLM",
    "FakeObservability",
    "FakeReviewInsightStore",
    "FakeSentry",
    "FakeSubprocessRunner",
    "FakeWikiCompiler",
    "FakeWorkspace",
]
