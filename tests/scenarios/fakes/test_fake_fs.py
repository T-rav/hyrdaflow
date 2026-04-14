"""FakeFS unit tests — in-memory fs with lock semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.fake_fs import FakeFS
from tests.scenarios.ports import FSPort


def test_fake_fs_satisfies_port() -> None:
    assert isinstance(FakeFS(), FSPort)


def test_write_then_read_roundtrips() -> None:
    fake = FakeFS()
    fake.write(Path("/.hydraflow/plans/issue-1.md"), "plan body")
    assert fake.read(Path("/.hydraflow/plans/issue-1.md")) == "plan body"


def test_exists_and_glob() -> None:
    fake = FakeFS()
    fake.write(Path("/.hydraflow/logs/a.log"), "")
    fake.write(Path("/.hydraflow/logs/b.log"), "")
    assert fake.exists(Path("/.hydraflow/logs/a.log"))
    matches = sorted(fake.glob(Path("/.hydraflow/logs"), "*.log"))
    assert len(matches) == 2


def test_lock_is_exclusive_via_contention_flag() -> None:
    fake = FakeFS()
    lock1 = fake.lock(Path("/.hydraflow/metrics/cache.lock"))
    with lock1:
        assert lock1.acquired
        lock2 = fake.lock(Path("/.hydraflow/metrics/cache.lock"))
        with pytest.raises(RuntimeError, match="already held"):
            lock2.__enter__()
