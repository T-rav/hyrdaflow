"""Fake adapters for MockWorld.

All Fakes here satisfy a Port protocol from src/ports.py. Production
code (server.py, orchestrator.py) does NOT import from this package —
only the sandbox entrypoint does.
"""

from mockworld.fakes.fake_beads import FakeBeads
from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_fs import FakeFS
from mockworld.fakes.fake_git import FakeGit
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_http import FakeHTTP
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
from mockworld.fakes.fake_issue_store import FakeIssueStore
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_sentry import FakeSentry
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler
from mockworld.fakes.fake_workspace import FakeWorkspace

__all__ = [
    "FakeBeads",
    "FakeClock",
    "FakeDocker",
    "FakeFS",
    "FakeGit",
    "FakeGitHub",
    "FakeHTTP",
    "FakeIssueFetcher",
    "FakeIssueStore",
    "FakeLLM",
    "FakeSentry",
    "FakeSubprocessRunner",
    "FakeWikiCompiler",
    "FakeWorkspace",
]
