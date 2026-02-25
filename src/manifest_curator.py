"""Curated manifest assembly from long-lived agent learnings."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from config import HydraFlowConfig
from file_util import atomic_write
from models import MemoryType

logger = logging.getLogger("hydraflow.manifest_curator")


class CuratedPayload(TypedDict):
    overview: str
    key_services: list[str]
    standards: list[str]
    architecture: list[str]
    source_count: int
    updated_at: str | None


@dataclass(slots=True)
class CuratedLearning:
    """Structured learning extracted from the memory digest."""

    number: int
    title: str
    learning: str
    created_at: str
    memory_type: MemoryType
    body: str = ""


class CuratedManifestStore:
    """Persist curated manifest hints derived from long-lived learnings."""

    _OVERVIEW_KEYWORDS = (
        "overview",
        "mission",
        "purpose",
        "vision",
        "summary",
        "hydraflow",
        "platform",
        "system",
    )
    _SERVICE_KEYWORDS = (
        "service",
        "api",
        "worker",
        "process",
        "component",
        "orchestrator",
        "pipeline",
        "agent",
        "daemon",
    )
    _STANDARD_KEYWORDS = (
        "standard",
        "guideline",
        "convention",
        "policy",
        "naming",
        "lint",
        "requirement",
        "checklist",
    )
    _ARCHITECTURE_KEYWORDS = (
        "architecture",
        "diagram",
        "flow",
        "design",
        "topology",
        "integration",
        "dependency",
        "module",
        "service mesh",
    )

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._path = config.data_path("manifest", "curated.json")

    @property
    def path(self) -> Path:
        """Return the on-disk curated manifest JSON path."""
        return self._path

    def update_from_learnings(
        self, learnings: Sequence[CuratedLearning]
    ) -> CuratedPayload:
        """Build curated payload from *learnings* and persist to disk."""
        payload = self._build_payload(learnings)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(payload, indent=2) + "\n")
        logger.info(
            "Curated manifest updated with %d learnings (overview=%s, services=%d, standards=%d, architecture=%d)",
            payload["source_count"],
            bool(payload["overview"]),
            len(payload["key_services"]),
            len(payload["standards"]),
            len(payload["architecture"]),
        )
        return payload

    def load(self) -> CuratedPayload:
        """Load curated payload from disk, returning an empty structure on failure."""
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data, dict):
                return self._coerce_payload(data)
        except (OSError, json.JSONDecodeError):
            logger.debug("No curated manifest payload at %s", self._path)
        return self._empty_payload()

    def render_markdown(self, payload: CuratedPayload | None = None) -> str:
        """Render curated payload as Markdown sections."""
        payload = payload or self.load()
        if not payload:
            payload = self._empty_payload()

        sections: list[str] = []
        overview = payload["overview"].strip()
        if overview:
            sections.append("### Project Overview\n" + overview)

        services = payload["key_services"]
        if services:
            joined = "\n".join(f"- {item}" for item in services)
            sections.append("### Key Services & Projects\n" + joined)

        standards = payload["standards"]
        if standards:
            joined = "\n".join(f"- {item}" for item in standards)
            sections.append("### Standards & Guidelines\n" + joined)

        architecture = payload["architecture"]
        if architecture:
            joined = "\n".join(f"- {item}" for item in architecture)
            sections.append("### Architecture Notes\n" + joined)

        if not sections:
            return ""

        header = "## Curated Learnings\n"
        return header + "\n\n".join(sections) + "\n"

    def _build_payload(self, learnings: Sequence[CuratedLearning]) -> CuratedPayload:
        knowledge = [
            item for item in learnings if item.memory_type == MemoryType.KNOWLEDGE
        ]
        payload = self._empty_payload()
        payload["source_count"] = len(knowledge)
        payload["overview"] = self._select_overview(knowledge)
        payload["key_services"] = self._collect_matches(
            knowledge, self._SERVICE_KEYWORDS
        )
        payload["standards"] = self._collect_matches(knowledge, self._STANDARD_KEYWORDS)
        payload["architecture"] = self._collect_matches(
            knowledge, self._ARCHITECTURE_KEYWORDS
        )
        return payload

    def _select_overview(self, knowledge: Sequence[CuratedLearning]) -> str:
        if not knowledge:
            return ""
        for learning in knowledge:
            if self._contains_any(learning, self._OVERVIEW_KEYWORDS):
                return self._format_single(learning)
        return self._format_single(knowledge[0])

    def _collect_matches(
        self,
        knowledge: Sequence[CuratedLearning],
        keywords: Sequence[str],
        limit: int = 6,
    ) -> list[str]:
        results: list[str] = []
        for learning in knowledge:
            if self._contains_any(learning, keywords):
                results.append(self._format_single(learning, include_issue=True))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _contains_any(learning: CuratedLearning, keywords: Sequence[str]) -> bool:
        haystacks = (
            learning.learning.lower(),
            learning.title.lower(),
            learning.body.lower(),
        )
        for keyword in keywords:
            lowered = keyword.lower()
            if any(lowered in hay for hay in haystacks if hay):
                return True
        return False

    @staticmethod
    def _format_single(
        learning: CuratedLearning,
        include_issue: bool = False,
        char_limit: int = 280,
    ) -> str:
        snippet = " ".join(learning.learning.split())
        if len(snippet) > char_limit:
            snippet = snippet[: char_limit - 1] + "…"
        title = learning.title.strip() or f"Issue #{learning.number}"
        if include_issue:
            return f"{title}: {snippet} (#{learning.number})"
        return f"{snippet} (#{learning.number} — {title})"

    @staticmethod
    def _empty_payload() -> CuratedPayload:
        return {
            "overview": "",
            "key_services": [],
            "standards": [],
            "architecture": [],
            "source_count": 0,
            "updated_at": None,
        }

    def _coerce_payload(self, raw: dict[str, object]) -> CuratedPayload:
        payload = self._empty_payload()
        payload["overview"] = str(raw.get("overview") or "")
        payload["key_services"] = [str(item) for item in raw.get("key_services") or []]
        payload["standards"] = [str(item) for item in raw.get("standards") or []]
        payload["architecture"] = [str(item) for item in raw.get("architecture") or []]
        payload["source_count"] = int(raw.get("source_count") or 0)
        updated = raw.get("updated_at")
        payload["updated_at"] = str(updated) if updated else None
        return payload
