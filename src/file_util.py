"""Shared file-writing utilities for HydraFlow."""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via temp file + ``os.replace``.

    Creates parent directories if needed.  The temp file is placed in the
    same directory as *path* so that ``os.replace`` is guaranteed to be
    atomic on POSIX (same filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def append_jsonl(path: Path, data: str) -> None:
    """Append *data* as a single line to *path* with crash-safe fsync.

    Creates parent directories if needed.  Calls ``flush`` + ``fsync``
    to ensure the record reaches stable storage before returning.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(data + "\n")
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Acquire an exclusive advisory lock for *path* until context exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
