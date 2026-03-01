"""Filesystem-backed cache for prompt context sections."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from config import HydraFlowConfig
from file_util import atomic_write

logger = logging.getLogger("hydraflow.context_cache")


class ContextSectionCache:
    """Caches expensive prompt context sections on disk.

    Cache key validity is based on source file metadata and content fingerprint.
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._path = config.data_path("cache", "context_sections.json")

    def get_or_load(
        self,
        *,
        key: str,
        source_path: Path,
        loader: Callable[[HydraFlowConfig], str],
    ) -> tuple[str, bool]:
        """Return cached content for *key* or load and persist it.

        Returns ``(content, cache_hit)``.
        """
        exists = source_path.is_file()
        stat_result = source_path.stat() if exists else None
        mtime_ns = stat_result.st_mtime_ns if stat_result is not None else 0
        ctime_ns = stat_result.st_ctime_ns if stat_result is not None else 0
        inode = stat_result.st_ino if stat_result is not None else 0
        size = stat_result.st_size if stat_result is not None else 0
        source_digest = self._source_digest(source_path, exists)

        data = self._load_cache_data()
        entry = data.get(key, {})

        if (
            entry.get("exists") == exists
            and entry.get("mtime_ns") == mtime_ns
            and entry.get("ctime_ns") == ctime_ns
            and entry.get("inode") == inode
            and entry.get("size") == size
            and entry.get("source_digest") == source_digest
        ):
            content = entry.get("content")
            if isinstance(content, str):
                return content, True

        content = loader(self._config)
        data[key] = {
            "exists": exists,
            "mtime_ns": mtime_ns,
            "ctime_ns": ctime_ns,
            "inode": inode,
            "size": size,
            "source_digest": source_digest,
            "content": content,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._write_cache_data(data)
        return content, False

    def _load_cache_data(self) -> dict[str, dict[str, object]]:
        if not self._path.is_file():
            return {}
        try:
            raw = self._path.read_text()
        except OSError:
            return {}
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Context cache is corrupt, rebuilding: %s", self._path)
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _write_cache_data(self, data: dict[str, dict[str, object]]) -> None:
        try:
            atomic_write(self._path, json.dumps(data, indent=2, sort_keys=True))
        except OSError:
            logger.warning(
                "Could not persist context cache to %s",
                self._path,
                exc_info=True,
            )

    def _source_digest(self, source_path: Path, exists: bool) -> str:
        if not exists:
            return ""
        try:
            return sha256(source_path.read_bytes()).hexdigest()
        except OSError:
            return ""
