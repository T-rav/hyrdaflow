"""Verify all Fake adapters carry the `_is_fake_adapter = True` marker.

The dashboard reads this marker via duck-typing to decide whether to
render the MOCKWORLD MODE banner. Adding it as a CLASS attribute (not
instance attribute) means it's discoverable without instantiation and
survives class-level introspection.
"""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub, FakeLLM, FakeWorkspace

_FAKE_CLASSES = [FakeGitHub, FakeWorkspace, FakeLLM]


@pytest.mark.parametrize("cls", _FAKE_CLASSES, ids=lambda c: c.__name__)
def test_fake_adapter_has_marker(cls: type) -> None:
    assert getattr(cls, "_is_fake_adapter", False) is True, (
        f"{cls.__name__} is missing `_is_fake_adapter = True` class attribute. "
        "The dashboard banner relies on this for duck-typed detection."
    )
