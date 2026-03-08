"""Persistent repo registry storage and config cloning for multi-repo setups."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from file_util import atomic_write

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.repo_store")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


@dataclass
class RepoRecord:
    """Single persisted repo entry."""

    slug: str
    repo: str
    path: str
    overrides: dict[str, Any] = field(default_factory=dict)
    auto_registered: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "repo": self.repo,
            "path": self.path,
            "overrides": self.overrides,
            "auto_registered": self.auto_registered,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoRecord:
        slug = str(data.get("slug") or "").strip()
        repo = str(data.get("repo") or "").strip()
        path = data.get("path") or ""
        overrides = data.get("overrides") or {}
        if not slug or not repo or not path:
            msg = f"invalid repo record: {data!r}"
            raise ValueError(msg)
        record = cls(
            slug=slug,
            repo=repo,
            path=_normalize_path(path),
            overrides=dict(overrides),
            auto_registered=bool(data.get("auto_registered", False)),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
        return record


class RepoRegistryStore:
    """Load/save repo registry metadata under ``data_root/repos.json``."""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root).expanduser().resolve() / "repos.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[RepoRecord]:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            logger.warning(
                "repos.json is corrupt; starting from empty state", exc_info=True
            )
            return []
        repos_raw = raw.get("repos") if isinstance(raw, dict) else None
        if not isinstance(repos_raw, list):
            return []
        records: list[RepoRecord] = []
        for entry in repos_raw:
            if not isinstance(entry, dict):
                continue
            try:
                records.append(RepoRecord.from_dict(entry))
            except ValueError:
                logger.debug("Skipping invalid repo entry: %s", entry, exc_info=True)
        return records

    def list(self) -> list[RepoRecord]:
        """Backward-compatible alias for ``load``."""
        return self.load()

    def save(self, records: list[RepoRecord]) -> None:
        payload = {
            "repos": [record.to_dict() for record in records],
        }
        atomic_write(self._path, json.dumps(payload, indent=2) + "\n")

    def upsert(self, record: RepoRecord) -> RepoRecord:
        records = {existing.slug: existing for existing in self.load()}
        normalized_path = _normalize_path(record.path)
        record.path = normalized_path
        now = _now_iso()
        if record.slug in records:
            existing = records[record.slug]
            record.created_at = existing.created_at or now
            merged = dict(existing.overrides)
            merged.update(record.overrides)
            record.overrides = merged
        else:
            record.created_at = record.created_at or now
        record.updated_at = now
        records[record.slug] = record
        self.save(list(records.values()))
        return record

    def remove(self, slug: str) -> bool:
        slug = slug.strip()
        if not slug:
            return False
        records = self.load()
        filtered = [r for r in records if r.slug != slug]
        if len(filtered) == len(records):
            return False
        self.save(filtered)
        return True

    def update_overrides(self, slug: str, updates: dict[str, Any]) -> bool:
        slug = slug.strip()
        if not slug or not updates:
            return False
        records = self.load()
        for record in records:
            if record.slug != slug:
                continue
            record.overrides.update(updates)
            record.updated_at = _now_iso()
            self.save(records)
            return True
        return False

    def get(self, slug: str) -> RepoRecord | None:
        slug = slug.strip()
        if not slug:
            return None
        for record in self.load():
            if record.slug == slug:
                return record
        return None


# Backwards-compatibility alias until call-sites migrate.
RepoStore = RepoRegistryStore


def clone_config_for_repo(
    base_config: HydraFlowConfig,
    *,
    repo: str,
    repo_root: Path,
) -> HydraFlowConfig:
    """Create a per-repo config by overriding repo identity fields.

    Copies *base_config* and replaces ``repo`` and ``repo_root`` while
    keeping all other settings (worker counts, models, poll intervals,
    etc.) from the base.  Path fields that are derived from ``repo_root``
    (like ``state_file``, ``event_log_path``) are re-resolved by the
    config model's validators.
    """
    from config import HydraFlowConfig  # noqa: PLC0415

    base_dict = base_config.model_dump()
    base_dict["repo"] = repo
    base_dict["repo_root"] = repo_root
    for key in ("state_file", "event_log_path", "config_file"):
        base_dict.pop(key, None)
    return HydraFlowConfig(**base_dict)


__all__ = [
    "RepoRecord",
    "RepoRegistryStore",
    "RepoStore",
    "clone_config_for_repo",
]
