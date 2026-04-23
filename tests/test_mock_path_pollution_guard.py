"""Verify the mock-path-pollution guard in tests/conftest.py fires as designed.

Uses pytest's built-in ``pytester`` fixture to spin up an in-process pytest
run that loads our root conftest, then points it at a synthetic test that
creates a ``MagicMock/`` directory. Must see the guard fire.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


def test_guard_fires_on_mock_path_directory(pytester: pytest.Pytester) -> None:
    # Copy the real conftest hook into the pytester tmpdir by writing a
    # minimal conftest that reproduces the hook shape. Keeping this
    # self-contained avoids fragile path coupling to the repo root.
    pytester.makeconftest(
        """
        import shutil
        from pathlib import Path
        import pytest

        def pytest_runtest_teardown(item, nextitem):
            root = Path(item.config.rootpath)
            polluted = root / "MagicMock"
            if polluted.exists():
                shutil.rmtree(polluted, ignore_errors=True)
                pytest.fail(
                    f"Mock-path pollution: test {item.nodeid} left {polluted} on disk."
                )
        """
    )
    pytester.makepyfile(
        test_polluter="""
        from pathlib import Path
        def test_creates_magicmock_dir():
            Path("MagicMock").mkdir(exist_ok=True)
        """
    )
    result = pytester.runpytest("-q")
    # Expect one reported failure from the teardown hook.
    result.stdout.fnmatch_lines(["*Mock-path pollution*"])
    assert result.ret != 0


def test_guard_quiet_on_clean_run(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import shutil
        from pathlib import Path
        import pytest

        def pytest_runtest_teardown(item, nextitem):
            root = Path(item.config.rootpath)
            polluted = root / "MagicMock"
            if polluted.exists():
                shutil.rmtree(polluted, ignore_errors=True)
                pytest.fail(
                    f"Mock-path pollution: test {item.nodeid} left {polluted} on disk."
                )
        """
    )
    pytester.makepyfile(
        test_clean="""
        def test_leaves_nothing_behind():
            assert True
        """
    )
    result = pytester.runpytest("-q")
    assert result.ret == 0
