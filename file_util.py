"""Shared file-writing utilities for HydraFlow."""

from __future__ import annotations

import contextlib
import os
import tempfile
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
