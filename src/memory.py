"""Memory system for persistent agent learnings — backed by Hindsight."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from file_util import atomic_write
from hindsight import (
    BANK_LEARNINGS,
    HindsightClient,
    format_memories_as_markdown,
    recall_safe,
    retain_safe,
)
from manifest import ProjectManifestManager
from manifest_curator import CuratedLearning, CuratedManifestStore
from manifest_issue_syncer import ManifestIssueSyncer
from models import (
    MemoryIssueData,
    MemorySyncResult,
    MemoryType,
)
from state import StateTracker

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.memory")
_ADR_ARCH_KEYWORDS: tuple[str, ...] = (
    "architecture",
    "architectural",
    "design",
    "decision",
    "adr",
    "topology",
    "service boundary",
    "module boundary",
    "workflow shift",
    "pipeline shift",
)
_ADR_REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Context",
    "## Decision",
    "## Consequences",
)


def _parse_memory_type(raw: str) -> MemoryType:
    """Normalise a raw type string to a ``MemoryType`` enum value.

    Returns ``MemoryType.KNOWLEDGE`` for unknown or empty values.
    """
    cleaned = raw.strip().lower()
    try:
        return MemoryType(cleaned)
    except ValueError:
        return MemoryType.KNOWLEDGE


def parse_memory_suggestion(transcript: str) -> dict[str, str] | None:
    """Parse a MEMORY_SUGGESTION block from an agent transcript.

    Returns a dict with ``title``, ``learning``, ``context``, and ``type``
    keys, or ``None`` if no block is found.  Only the first block is
    returned (cap at 1 suggestion per agent run).

    The ``type`` field defaults to ``"knowledge"`` when absent or
    unrecognised.
    """
    pattern = r"MEMORY_SUGGESTION_START\s*\n(.*?)\nMEMORY_SUGGESTION_END"
    match = re.search(pattern, transcript, re.DOTALL)
    if not match:
        return None

    block = match.group(1)
    result: dict[str, str] = {"title": "", "learning": "", "context": "", "type": ""}

    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            result["title"] = stripped[len("title:") :].strip()
        elif stripped.startswith("learning:"):
            result["learning"] = stripped[len("learning:") :].strip()
        elif stripped.startswith("context:"):
            result["context"] = stripped[len("context:") :].strip()
        elif stripped.startswith("type:"):
            result["type"] = stripped[len("type:") :].strip()

    if not result["title"] or not result["learning"]:
        return None

    # Normalise type — default to knowledge when missing or invalid
    result["type"] = _parse_memory_type(result["type"]).value

    return result


def build_memory_issue_body(
    learning: str,
    context: str,
    source: str,
    reference: str,
    memory_type: str = "knowledge",
) -> str:
    """Format a structured GitHub issue body for a memory suggestion."""
    return (
        f"## Memory Suggestion\n\n"
        f"**Type:** {memory_type}\n\n"
        f"**Learning:** {learning}\n\n"
        f"**Context:** {context}\n\n"
        f"**Source:** {source} during {reference}\n"
    )


async def recall_contextual_memory(
    hindsight: HindsightClient,
    query: str,
    *,
    limit: int = 20,
    max_chars: int = 4000,
) -> str:
    """Recall relevant memories from Hindsight for a given task context.

    Returns formatted markdown, or empty string on failure.
    """
    memories = await recall_safe(hindsight, BANK_LEARNINGS, query, limit=limit)
    if not memories:
        return ""
    content = format_memories_as_markdown(memories)
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n…(truncated)"
    return content


async def file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
    prs: PRPort,
    state: StateTracker,
) -> None:
    """Parse and file a memory suggestion from an agent transcript.

    Actionable types (``config``, ``instruction``, ``code``) are routed
    through HITL for human approval.  Knowledge-type suggestions follow
    the normal improve-label flow.
    """
    suggestion = parse_memory_suggestion(transcript)
    if not suggestion:
        return

    memory_type = MemoryType(suggestion.get("type", "knowledge"))
    body = build_memory_issue_body(
        learning=suggestion["learning"],
        context=suggestion["context"],
        source=source,
        reference=reference,
        memory_type=memory_type.value,
    )
    title = f"[Memory] {suggestion['title']}"

    # Routing matrix (auto_approve x is_actionable):
    #   auto_approve=True  + any type    -> memory_label directly (skip HITL)
    #   auto_approve=False + knowledge   -> improve_label only (no HITL)
    #   auto_approve=False + actionable  -> improve_label + hitl_label (HITL)
    if config.memory_auto_approve:
        # Auto-approve: all types skip HITL, label for memory sync pickup
        labels = list(config.memory_label)
        hitl_cause = None
    elif MemoryType.is_actionable(memory_type):
        # No auto-approve + actionable: route through HITL
        labels = list(config.improve_label) + list(config.hitl_label)
        hitl_cause = f"Actionable memory suggestion ({memory_type.value})"
    else:
        # No auto-approve + knowledge: normal improve pipeline
        labels = list(config.improve_label)
        hitl_cause = None

    issue_number = await prs.create_issue(title, body, labels)
    if issue_number:
        if hitl_cause is not None:
            state.set_hitl_origin(issue_number, config.improve_label[0])
            state.set_hitl_cause(issue_number, hitl_cause)
        logger.info(
            "Filed %s memory suggestion as issue #%d: %s",
            memory_type.value,
            issue_number,
            suggestion["title"],
        )


class MemorySyncWorker:
    """Syncs memory issues to Hindsight and maintains the manifest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        hindsight: HindsightClient,
        prs: PRPort | None = None,
        *,
        manifest_store: CuratedManifestStore | None = None,
        manifest_manager: ProjectManifestManager | None = None,
        manifest_syncer: ManifestIssueSyncer | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._hindsight = hindsight
        self._prs = prs
        self._manifest_store = manifest_store or CuratedManifestStore(config)
        self._manifest_manager = manifest_manager or ProjectManifestManager(
            config, curator=self._manifest_store
        )
        self._manifest_syncer = manifest_syncer

    async def sync(self, issues: list[MemoryIssueData]) -> MemorySyncResult:
        """Main sync entry point — retains learnings to Hindsight.

        *issues* is a list of dicts with ``number``, ``title``, ``body``,
        and ``createdAt`` keys (from ``gh issue list --json``).

        Returns stats dict for event publishing.
        """
        current_ids = sorted(i["number"] for i in issues)
        _, prev_hash, _ = self._state.get_memory_state()

        if not issues:
            self._state.update_memory_state([], prev_hash)
            self._manifest_store.update_from_learnings([])
            await self._refresh_manifest("memory-sync-empty")
            return {
                "action": "synced",
                "item_count": 0,
                "compacted": False,
                "digest_chars": 0,
                "pruned": 0,
                "issues_closed": 0,
            }

        # Extract learnings
        learnings: list[CuratedLearning] = []
        for issue in issues:
            body = issue.get("body", "")
            learning = self._extract_learning(body)
            created = issue.get("createdAt", "")
            memory_type = self._extract_memory_type(body)
            if learning:
                learnings.append(
                    CuratedLearning(
                        number=issue["number"],
                        title=issue.get("title", ""),
                        learning=learning,
                        created_at=created,
                        memory_type=memory_type,
                        body=body,
                    )
                )

        # Retain each learning to Hindsight
        for record in learnings:
            await retain_safe(
                self._hindsight,
                BANK_LEARNINGS,
                record.learning,
                context=record.title,
                metadata={
                    "source": "memory_sync",
                    "memory_type": record.memory_type.value,
                    "issue_number": str(record.number),
                },
            )

        # Trigger Hindsight reflection to build mental models
        try:
            await self._hindsight.reflect(BANK_LEARNINGS)
        except Exception:
            logger.warning("Hindsight reflect failed", exc_info=True)

        # Update state and manifest
        self._state.update_memory_state(current_ids, "hindsight")
        self._manifest_store.update_from_learnings(learnings)
        await self._refresh_manifest("memory-sync")
        await self._route_adr_candidates(issues)
        closed, _close_failed = await self._close_synced_issues(issues)

        return {
            "action": "synced",
            "item_count": len(learnings),
            "compacted": False,
            "digest_chars": 0,
            "pruned": 0,
            "issues_closed": closed,
        }

    def _should_auto_close_issue(self, issue: MemoryIssueData) -> bool:
        """Return True only for canonical memory/transcript sync issues."""
        title = str(issue.get("title", "")).strip()
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            return False
        has_memory_label = any(lbl in self._config.memory_label for lbl in labels)
        has_transcript_label = any(
            lbl in self._config.transcript_label for lbl in labels
        )
        is_memory = title.startswith("[Memory]") and has_memory_label
        is_transcript = (
            title.startswith("[Transcript Summary]") and has_transcript_label
        )
        return is_memory or is_transcript

    async def _close_synced_issues(
        self, issues: list[MemoryIssueData]
    ) -> tuple[int, int]:
        """Close synced memory issues when a PR port is available.

        Returns ``(closed, failed)`` counts.
        """
        if self._prs is None:
            return 0, 0
        closed = 0
        failed = 0
        for issue in issues:
            if not self._should_auto_close_issue(issue):
                continue
            issue_number = int(issue.get("number", 0))
            if issue_number <= 0:
                continue
            try:
                await self._prs.close_issue(issue_number)
                closed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(
                    "Could not close synced memory issue #%d: %s",
                    issue_number,
                    exc,
                )
        logger.info(
            "Memory sync auto-close summary: closed=%d failed=%d",
            closed,
            failed,
        )
        return closed, failed

    async def _route_adr_candidates(self, issues: list[MemoryIssueData]) -> None:
        """Create ADR draft tasks from architecture-shift memory issues."""
        from phase_utils import load_existing_adr_topics, normalize_adr_topic

        if self._prs is None:
            return

        seen = self._load_adr_source_ids()
        existing_topics = load_existing_adr_topics(self._config.repo_root)
        batch_topics: set[str] = set()
        created = 0
        rejected = 0
        deduped = 0
        for issue in issues:
            if not self._is_memory_issue(issue):
                continue
            source_id = int(issue.get("number", 0))
            if source_id <= 0 or source_id in seen:
                continue
            title = str(issue.get("title", "")).strip()
            body = str(issue.get("body", ""))
            learning = self._extract_learning(body)
            if not self._is_architecture_candidate(title, learning, body):
                continue

            topic_key = normalize_adr_topic(title)
            if topic_key in existing_topics or topic_key in batch_topics:
                deduped += 1
                seen.add(source_id)
                logger.info(
                    "Skipping ADR candidate from memory #%d — duplicate topic %r",
                    source_id,
                    topic_key,
                )
                continue

            adr_title = ""
            adr_body = ""
            reasons: list[str] = ["uninitialized"]
            for attempt in (1, 2):
                adr_title, adr_body = self._build_adr_task(
                    issue, learning, refine=(attempt > 1)
                )
                reasons = self._validate_adr_task(adr_body)
                if not reasons:
                    break
            if reasons:
                rejected += 1
                seen.add(source_id)
                logger.warning(
                    "Rejected ADR candidate from memory #%d after validation: %s",
                    source_id,
                    "; ".join(reasons),
                )
                continue

            issue_number = await self._prs.create_issue(
                adr_title,
                adr_body,
                list(self._config.find_label[:1]),
            )
            if issue_number:
                seen.add(source_id)
                batch_topics.add(topic_key)
                created += 1

        if created or deduped:
            self._save_adr_source_ids(seen)
        logger.info(
            "ADR routing summary: created=%d rejected=%d deduped=%d tracked_sources=%d",
            created,
            rejected,
            deduped,
            len(seen),
        )

    def _is_memory_issue(self, issue: MemoryIssueData) -> bool:
        title = str(issue.get("title", "")).strip()
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            return False
        has_memory_label = any(lbl in self._config.memory_label for lbl in labels)
        return title.startswith("[Memory]") and has_memory_label

    @staticmethod
    def _is_architecture_candidate(title: str, learning: str, body: str) -> bool:
        haystack = " ".join([title.lower(), learning.lower(), body.lower()])
        return any(keyword in haystack for keyword in _ADR_ARCH_KEYWORDS)

    def _build_adr_task(
        self, source_issue: MemoryIssueData, learning: str, *, refine: bool = False
    ) -> tuple[str, str]:
        raw_title = str(source_issue.get("title", "")).strip()
        cleaned = re.sub(r"^\[Memory\]\s*", "", raw_title, flags=re.IGNORECASE).strip()
        adr_title = (
            f"[ADR] Draft decision from memory #{source_issue['number']}: {cleaned}"
        )
        decision = (
            "Adopt the architectural shift captured in this memory by recording a "
            "concrete ADR under `docs/adr/`, including boundaries, tradeoffs, and "
            "operational impact on HydraFlow workers."
        )
        if refine:
            decision += (
                " Tie this explicitly to the current implementation and call out "
                "what changes now versus what remains unchanged."
            )
        body = (
            "## ADR Draft Task\n\n"
            "Create or update an ADR under `docs/adr/` that captures this architectural shift.\n\n"
            "### Verification Gate\n"
            "- Validate decision scope and tradeoffs against current code and workflow\n"
            "- Ensure ADR format follows `docs/adr/README.md`\n"
            "- Include links back to source memory and related issues/PRs\n\n"
            "### Source Memory\n"
            f"- Issue: #{source_issue['number']}\n"
            f"- Title: {raw_title}\n"
            f"- Learning: {learning}\n\n"
            "## Context\n"
            f"This ADR was seeded from memory issue #{source_issue['number']} and "
            "captures an architecture/workflow change that should be recorded as a "
            "durable decision.\n\n"
            "## Decision\n"
            f"{decision}\n\n"
            "## Consequences\n"
            "- Creates a durable architecture record linked to the source memory.\n"
            "- Makes tradeoffs explicit for future implementation/review cycles.\n"
            "- May require follow-up tasks if gaps are identified during ADR write-up.\n\n"
            "### ADR Metadata Template\n"
            "```md\n"
            "- Status: Proposed\n"
            "- Date: <YYYY-MM-DD>\n\n"
            "```\n\n"
            "After implementation and validation, continue normal pipeline flow to review."
        )
        return adr_title, body

    @staticmethod
    def _extract_markdown_section(body: str, heading: str) -> str:
        pattern = (
            r"(?ims)^##\s+" + re.escape(heading) + r"\s*\n(?P<section>.*?)(?=^##\s+|\Z)"
        )
        match = re.search(pattern, body)
        return match.group("section").strip() if match else ""

    def _validate_adr_task(self, body: str) -> list[str]:
        reasons: list[str] = []
        text = body.strip()
        if len(text) < 120:
            reasons.append("ADR body is too short (minimum 120 characters)")
        lower = text.lower()
        missing = [h for h in _ADR_REQUIRED_HEADINGS if h.lower() not in lower]
        if missing:
            reasons.append("Missing required ADR sections: " + ", ".join(missing))
        decision = self._extract_markdown_section(text, "decision")
        if len(decision.strip()) < 60:
            reasons.append(
                "Decision section lacks actionable detail (minimum 60 chars)"
            )
        return reasons

    def _adr_sources_path(self) -> Path:
        return self._config.data_path("memory", "adr_sources.json")

    def _load_adr_source_ids(self) -> set[int]:
        path = self._adr_sources_path()
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {int(x) for x in data if isinstance(x, int)}

    def _save_adr_source_ids(self, issue_ids: set[int]) -> None:
        path = self._adr_sources_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(sorted(issue_ids)) + "\n")

    async def _refresh_manifest(self, source: str) -> None:
        """Regenerate the manifest and optionally sync it upstream."""
        if self._manifest_manager is None:
            return
        result = self._manifest_manager.refresh()
        self._state.update_manifest_state(result.digest_hash)
        logger.info(
            "Manifest refreshed via %s (hash=%s, chars=%d)",
            source,
            result.digest_hash,
            len(result.content),
        )
        if self._manifest_syncer is not None:
            await self._manifest_syncer.sync(
                result.content,
                result.digest_hash,
                source=source,
            )

    @staticmethod
    def _extract_learning(body: str) -> str:
        """Extract the learning content from an issue body."""
        if not body or not body.strip():
            return ""
        learning_match = re.search(
            r"\*\*Learning:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)",
            body,
            re.DOTALL,
        )
        if learning_match:
            return learning_match.group(1).strip()
        return body.strip()

    @staticmethod
    def _extract_memory_type(body: str) -> MemoryType:
        """Extract the memory type from an issue body."""
        if not body:
            return MemoryType.KNOWLEDGE
        type_match = re.search(
            r"\*\*Type:\*\*\s*(\S+)",
            body,
        )
        if type_match:
            return _parse_memory_type(type_match.group(1))
        return MemoryType.KNOWLEDGE

    async def publish_sync_event(self, stats: MemorySyncResult) -> None:
        """Publish a MEMORY_SYNC event with *stats*."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.MEMORY_SYNC,
                data=dict(stats),
            )
        )
