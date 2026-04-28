"""FakeFS — in-memory filesystem scoped to scenario tests.

Intentionally NOT pyfakefs-global (which intercepts all open() calls). Scoped
behavior avoids surprising unrelated code.
"""

from __future__ import annotations

from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path


class _FakeLock:
    def __init__(self, owner: FakeFS, path: Path) -> None:
        self._owner = owner
        self._path = path
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def __enter__(self) -> _FakeLock:
        if self._path in self._owner._locks_held:
            msg = f"lock {self._path} already held"
            raise RuntimeError(msg)
        self._owner._locks_held.add(self._path)
        self._acquired = True
        return self

    def __exit__(self, *_: object) -> None:
        if self._acquired:
            self._owner._locks_held.discard(self._path)
            self._acquired = False


class FakeFS:
    _is_fake_adapter = True

    def __init__(self) -> None:
        self._files: dict[Path, str] = {}
        self._locks_held: set[Path] = set()

    def write(self, path: Path, data: str | bytes) -> None:
        self._files[path] = data if isinstance(data, str) else data.decode()

    def read(self, path: Path) -> str:
        if path not in self._files:
            msg = f"{path} not in FakeFS"
            raise FileNotFoundError(msg)
        return self._files[path]

    def exists(self, path: Path) -> bool:
        return path in self._files

    def glob(self, root: Path, pattern: str) -> Iterator[Path]:
        root_s = str(root)
        for path in self._files:
            if str(path).startswith(root_s) and fnmatch(path.name, pattern):
                yield path

    def mkdir(self, path: Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        _ = (path, parents, exist_ok)
        # In-memory: directories are implicit (derived from file paths).

    def lock(self, path: Path) -> _FakeLock:
        return _FakeLock(self, path)
