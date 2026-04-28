"""Verify all Fake adapters carry the `_is_fake_adapter = True` marker.

The marker has two consumers:

1. The dashboard reads it via duck-typing to decide whether to render
   the MOCKWORLD MODE banner.
2. The arch-doc extractor (``src/arch/extractors/mockworld.py``) gates
   inclusion in ``docs/arch/generated/mockworld.md`` on this marker so
   nested-record dataclasses (``FakeIssue``, ``FakePR``, ``FakeIssueRecord``,
   ``FakeIssueSummary``) that live alongside Fake adapters are excluded.

Adding the marker as a CLASS attribute (not instance) means it's
discoverable without instantiation and survives class-level introspection.
"""

from __future__ import annotations

import pytest

from mockworld.fakes import (
    FakeBeads,
    FakeClock,
    FakeDocker,
    FakeFS,
    FakeGit,
    FakeGitHub,
    FakeHTTP,
    FakeIssueFetcher,
    FakeIssueStore,
    FakeLLM,
    FakeSentry,
    FakeSubprocessRunner,
    FakeWikiCompiler,
    FakeWorkspace,
)

# All top-level Fake adapters re-exported by ``mockworld.fakes``. The
# arch-doc generator filters its discovery logic on this same marker,
# so any new Fake must carry it for both the dashboard banner and the
# generated MockWorld map to surface it.
_FAKE_CLASSES = [
    FakeBeads,
    FakeClock,
    FakeDocker,
    FakeFS,
    FakeGit,
    FakeGitHub,
    FakeHTTP,
    FakeIssueFetcher,
    FakeIssueStore,
    FakeLLM,
    FakeSentry,
    FakeSubprocessRunner,
    FakeWikiCompiler,
    FakeWorkspace,
]


@pytest.mark.parametrize("cls", _FAKE_CLASSES, ids=lambda c: c.__name__)
def test_fake_adapter_has_marker(cls: type) -> None:
    assert getattr(cls, "_is_fake_adapter", False) is True, (
        f"{cls.__name__} is missing `_is_fake_adapter = True` class attribute. "
        "Both the dashboard banner (duck-typed detection) and the arch-doc "
        "generator (``src/arch/extractors/mockworld.py``) rely on this marker."
    )
