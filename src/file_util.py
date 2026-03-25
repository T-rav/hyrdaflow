"""Shared file-writing utilities for HydraFlow."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("hydraflow.file_util")


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


def rotate_backups(path: Path, count: int = 3) -> None:
    """Rotate backup copies of *path*, keeping at most *count* generations.

    Copies ``path`` to ``path.bak``, shifting existing ``.bak`` files:
    ``.bak`` -> ``.bak.1``, ``.bak.1`` -> ``.bak.2``, etc.  Deletes
    the oldest backup beyond *count*.
    """
    if not path.exists():
        return

    # Delete the oldest backup if it exists
    oldest = Path(f"{path}.bak.{count}")
    if oldest.exists():
        try:
            oldest.unlink()
        except OSError:
            logger.warning("Could not remove oldest backup %s", oldest, exc_info=True)

    # Shift existing backups up: .bak.(n-1) -> .bak.n
    for i in range(count - 1, 0, -1):
        src = Path(f"{path}.bak.{i}")
        dst = Path(f"{path}.bak.{i + 1}")
        if src.exists():
            try:
                shutil.copy2(src, dst)
                src.unlink()
            except OSError:
                logger.warning(
                    "Could not rotate backup %s -> %s", src, dst, exc_info=True
                )

    # Shift .bak -> .bak.1
    bak = Path(f"{path}.bak")
    if bak.exists():
        try:
            shutil.copy2(bak, Path(f"{path}.bak.1"))
            bak.unlink()
        except OSError:
            logger.warning("Could not rotate backup %s", bak, exc_info=True)

    # Copy current file to .bak
    try:
        shutil.copy2(path, bak)
    except OSError:
        logger.warning("Could not create backup %s", bak, exc_info=True)
