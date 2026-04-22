"""Regression test for issue #6493.

Bug: ``DoltBackend`` has three code-quality issues:

1. ``_run()`` calls ``result.check_returncode()`` which raises
   ``subprocess.CalledProcessError``, but the surrounding code (log message,
   callers) expects ``RuntimeError``.  Exception type mismatch.

2. ``self._dolt`` is validated as non-None at construction time only.  If the
   ``dolt`` binary is removed after construction, ``_run()`` passes ``None``
   into ``subprocess.run()`` which raises a confusing ``TypeError``, not the
   expected ``FileNotFoundError``.

3. ``_ensure_repo()`` reads ``_SCHEMA_FILE.read_text()`` inside an
   ``is_file()`` guard, but has no ``try/except`` for OSError.  If the file
   exists but cannot be read (e.g. permissions), a raw ``PermissionError``
   propagates with no helpful context instead of a ``FileNotFoundError``
   pointing at the migrations directory.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from dolt_backend import DoltBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend(tmp_path: Path) -> DoltBackend:
    """Create a DoltBackend with a mocked dolt binary, bypassing real init."""
    dolt_dir = tmp_path / "dolt_repo"
    dolt_dir.mkdir()
    (dolt_dir / ".dolt").mkdir()  # Skip dolt init sequence

    with (
        patch("dolt_backend.shutil.which", return_value="/usr/local/bin/dolt"),
        patch("dolt_backend.subprocess.run") as mock_run,
        patch("dolt_backend._SCHEMA_FILE") as mock_schema,
    ):
        mock_schema.is_file.return_value = False
        mock_run.return_value = MagicMock(
            returncode=0, stdout="nothing to commit", stderr=""
        )
        return DoltBackend(dolt_dir)


# ---------------------------------------------------------------------------
# 1. _run() exception type: should be RuntimeError, not CalledProcessError
# ---------------------------------------------------------------------------


class TestRunExceptionType:
    """_run() must raise RuntimeError on non-zero exit, not CalledProcessError."""

    @pytest.mark.xfail(
        reason="Regression for issue #6493 — fix not yet landed", strict=False
    )
    def test_run_raises_runtime_error_on_failure(self, backend: DoltBackend) -> None:
        """BUG (current): _run() calls result.check_returncode() which raises
        subprocess.CalledProcessError.  Callers (e.g. load_state)
        catch CalledProcessError directly, but the pattern implies RuntimeError
        was intended.

        After fix: _run() should raise RuntimeError with the stderr message.
        """
        with patch("dolt_backend.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["dolt", "status"],
                returncode=1,
                stdout="",
                stderr="error: something went wrong",
            )
            with pytest.raises(RuntimeError):
                backend._run("status")

    @pytest.mark.xfail(
        reason="Regression for issue #6493 — fix not yet landed", strict=False
    )
    def test_run_error_includes_stderr_in_message(self, backend: DoltBackend) -> None:
        """The RuntimeError message should include the stderr output for debugging."""
        with patch("dolt_backend.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["dolt", "sql", "-q", "BAD SQL"],
                returncode=1,
                stdout="",
                stderr="SQL error: syntax error near BAD",
            )
            with pytest.raises(RuntimeError, match="syntax error"):
                backend._run("sql", "-q", "BAD SQL")


# ---------------------------------------------------------------------------
# 2. Binary removed after init: should be FileNotFoundError, not TypeError
# ---------------------------------------------------------------------------


class TestBinaryRemovedAfterInit:
    """If dolt binary disappears after construction, _run() should raise
    FileNotFoundError, not TypeError from subprocess.run receiving None."""

    @pytest.mark.xfail(
        reason="Regression for issue #6493 — fix not yet landed", strict=False
    )
    def test_none_dolt_raises_file_not_found_error(self, backend: DoltBackend) -> None:
        """BUG (current): setting _dolt to None (simulating binary removal)
        and calling _run() causes subprocess.run([None, ...]) which raises
        TypeError('expected str, bytes or os.PathLike object, not NoneType').

        After fix: _run() should validate self._dolt and raise FileNotFoundError.
        """
        backend._dolt = None
        with pytest.raises(FileNotFoundError):
            backend._run("status")


# ---------------------------------------------------------------------------
# 3. Schema file OSError: should be FileNotFoundError with path context
# ---------------------------------------------------------------------------


class TestSchemaFileReadError:
    """_ensure_repo() must catch OSError from read_text() and re-raise as
    FileNotFoundError with the migrations path for diagnostics."""

    @pytest.mark.xfail(
        reason="Regression for issue #6493 — fix not yet landed", strict=False
    )
    def test_permission_error_raises_file_not_found_with_path(
        self, tmp_path: Path
    ) -> None:
        """BUG (current): if _SCHEMA_FILE.is_file() returns True but
        read_text() raises PermissionError, the raw PermissionError propagates
        from __init__ with no context about the migrations directory.

        After fix: should raise FileNotFoundError mentioning the schema path.
        """
        dolt_dir = tmp_path / "dolt_repo_schema"
        dolt_dir.mkdir()
        (dolt_dir / ".dolt").mkdir()

        mock_schema = MagicMock()
        mock_schema.is_file.return_value = True
        mock_schema.read_text.side_effect = PermissionError(13, "Permission denied")

        with (
            patch("dolt_backend.shutil.which", return_value="/usr/local/bin/dolt"),
            patch("dolt_backend.subprocess.run") as mock_run,
            patch("dolt_backend._SCHEMA_FILE", mock_schema),
        ):
            mock_run.return_value = MagicMock(
                returncode=0, stdout="nothing to commit", stderr=""
            )
            with pytest.raises(FileNotFoundError, match="migration"):
                DoltBackend(dolt_dir)
