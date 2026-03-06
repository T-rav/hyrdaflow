"""Persistence layer for RepoRuntime registrations."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from file_util import atomic_write

logger = logging.getLogger("hydraflow.repo_registry_store")


class RepoEntry(BaseModel):
    """Metadata describing a registered repository runtime."""

    slug: str = Field(..., min_length=1)
    path: str | None = None
    repo: str | None = None
    auto_start: bool = True

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            msg = "slug must not be empty"
            raise ValueError(msg)
        return trimmed

    @field_validator("path")
    @classmethod
    def _normalize_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("repo")
    @classmethod
    def _normalize_repo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RepoRegistryStore:
    """Manage persistence for registered repos via ``repos.json``."""

    def __init__(self, data_root: Path, filename: str = "repos.json") -> None:
        self._path = data_root / filename

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[RepoEntry]:
        """Load repo entries from disk, tolerating corrupt files."""
        records = self._read_raw_records()
        entries: list[RepoEntry] = []
        for record in records:
            try:
                entries.append(RepoEntry.model_validate(record))
            except ValidationError as exc:
                logger.warning("Skipping invalid repo entry: %s", exc)
        return entries

    def save(self, entries: Iterable[RepoEntry]) -> None:
        """Persist *entries* to ``repos.json`` atomically."""
        payload = [entry.model_dump(mode="json") for entry in entries]
        text = json.dumps(payload, indent=2) + "\n"
        atomic_write(self._path, text)

    def add(self, entry: RepoEntry) -> RepoEntry:
        """Insert or update *entry* keyed by slug."""
        entries = self.load()
        for idx, existing in enumerate(entries):
            if existing.slug == entry.slug:
                entries[idx] = entry
                break
        else:
            entries.append(entry)
        self.save(entries)
        return entry

    def remove(self, slug: str) -> bool:
        """Remove *slug* if present. Returns ``True`` when deleted."""
        entries = self.load()
        filtered = [entry for entry in entries if entry.slug != slug]
        if len(filtered) == len(entries):
            return False
        self.save(filtered)
        return True

    def _read_raw_records(self) -> list[dict[str, object]]:
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Failed to read repo registry %s: %s", self._path, exc)
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Repo registry %s is corrupt; moving aside", self._path)
            self._quarantine_corrupt_file()
            return []
        if not isinstance(data, list):
            logger.warning("Repo registry %s must contain a list", self._path)
            return []
        result: list[dict[str, object]] = []
        for record in data:
            if isinstance(record, dict):
                result.append(record)
            else:
                logger.warning("Ignoring non-object repo entry in %s", self._path)
        return result

    def _quarantine_corrupt_file(self) -> None:
        target = self._path.with_suffix(self._path.suffix + ".corrupt")
        counter = 1
        while target.exists():
            target = self._path.with_suffix(self._path.suffix + f".corrupt{counter}")
            counter += 1
        try:
            self._path.rename(target)
        except OSError as exc:
            logger.warning(
                "Failed to quarantine corrupt registry %s: %s", self._path, exc
            )
