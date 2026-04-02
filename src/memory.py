"""Memory digest system for persistent agent learnings."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from adr_utils import load_existing_adr_topics, normalize_adr_topic
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from models import (
    MemoryIssueData,
    MemorySyncResult,
    MemoryType,
)
from state import StateTracker

if TYPE_CHECKING:
    from dolt_backend import DoltBackend
    from hindsight import HindsightClient
    from hindsight_wal import HindsightWAL
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


def _next_item_id() -> str:
    """Generate a unique memory item ID."""
    import uuid as _uuid  # noqa: PLC0415

    return f"mem-{_uuid.uuid4().hex[:8]}"


async def file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
    prs: PRPort | None = None,  # no longer needed — kept for signature compat
    state: StateTracker | None = None,  # no longer needed — kept for signature compat
) -> None:
    """Parse and store a memory suggestion from an agent transcript.

    Writes directly to local JSONL storage and Hindsight vector store.
    No GitHub issues are created.
    """
    import json as _json  # noqa: PLC0415

    suggestion = parse_memory_suggestion(transcript)
    if not suggestion:
        return

    memory_type = MemoryType(suggestion.get("type", "knowledge"))
    item = {
        "id": _next_item_id(),
        "title": suggestion["title"],
        "learning": suggestion["learning"],
        "context": suggestion.get("context", ""),
        "memory_type": memory_type.value,
        "source": source,
        "reference": reference,
        "created_at": datetime.now(UTC).isoformat(),
    }

    # Write to JSONL
    try:
        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        with items_path.open("a") as f:
            f.write(_json.dumps(item) + "\n")
    except OSError:
        logger.exception("Failed to write memory item to JSONL")
        return

    # Write to Hindsight if available
    try:
        from hindsight import Bank, schedule_retain  # noqa: PLC0415

        schedule_retain(
            None,  # client — resolved by schedule_retain from global state
            Bank.LEARNINGS,
            item["learning"],
            metadata={
                "source": source,
                "type": memory_type.value,
                "title": item["title"],
            },
        )
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        logger.debug("Hindsight retain failed for memory item %s", item["id"])

    logger.info(
        "Stored memory item %s: %s (%s)",
        item["id"],
        item["title"],
        memory_type.value,
    )


class MemorySyncWorker:
    """Reads local JSONL memory items, scores/evicts them, and writes to Hindsight."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
        prs: PRPort | None = None,
        *,
        hindsight: HindsightClient | None = None,
        dolt: DoltBackend | None = None,
        wal: HindsightWAL | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._runner = runner or get_default_runner()
        self._prs = prs
        self._hindsight = hindsight
        self._dolt = dolt
        self._wal = wal
        from dedup_store import DedupStore  # noqa: PLC0415

        self._adr_sources = DedupStore(
            "adr_sources",
            config.data_path("memory", "adr_sources.json"),
            dolt=dolt,
        )

    def _load_local_items(self) -> list[dict[str, object]]:
        """Load memory items from items.jsonl."""
        import json as _json  # noqa: PLC0415

        path = self._config.data_path("memory", "items.jsonl")
        if not path.exists():
            return []
        items: list[dict[str, object]] = []
        try:
            for line in path.read_text().strip().splitlines():
                try:
                    items.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
        except OSError:
            logger.warning("Failed to read memory items from %s", path)
        return items

    async def sync(
        self, issues: list[MemoryIssueData] | None = None
    ) -> MemorySyncResult:
        """Process local memory items and write to Hindsight.

        Returns stats dict for event publishing.
        """
        local_items = self._load_local_items()
        _, prev_hash, _ = self._state.get_memory_state()

        if not local_items:
            self._state.update_memory_state([], prev_hash)
            return {
                "action": "synced",
                "item_count": 0,
                "compacted": False,
                "digest_chars": 0,
            }

        # Write items to Hindsight
        if self._hindsight:
            from hindsight import Bank, retain_safe  # noqa: PLC0415

            for item in local_items:
                learning_text = str(item.get("learning", ""))
                if not learning_text:
                    continue
                item_id = str(item.get("id", ""))
                memory_type = _parse_memory_type(
                    str(item.get("memory_type", "knowledge"))
                )
                await retain_safe(
                    self._hindsight,
                    Bank.LEARNINGS,
                    learning_text,
                    context=f"Item {item_id} ({memory_type.value})",
                    metadata={
                        "item_id": item_id,
                        "memory_type": memory_type.value,
                        "created_at": str(item.get("created_at", "")),
                    },
                    wal=self._wal,
                )

        # Update state
        item_ids = sorted(
            abs(hash(str(item.get("id", "")))) % (10**9) for item in local_items
        )
        items_hash = hashlib.sha256(
            "".join(str(item.get("learning", "")) for item in local_items).encode()
        ).hexdigest()[:16]
        self._state.update_memory_state(item_ids, items_hash)

        # Route ADR candidates from local items (convert to issue-like dicts)
        adr_issues = self._local_items_to_issue_dicts(local_items)
        await self._route_adr_candidates(adr_issues)

        return {
            "action": "synced",
            "item_count": len(local_items),
            "compacted": False,
            "digest_chars": 0,
        }

    @staticmethod
    def _local_items_to_issue_dicts(
        items: list[dict[str, object]],
    ) -> list[MemoryIssueData]:
        """Convert local JSONL items to MemoryIssueData dicts for ADR routing."""
        result: list[MemoryIssueData] = []
        for item in items:
            item_id = str(item.get("id", ""))
            num = abs(hash(item_id)) % (10**9) if item_id else 0
            learning = str(item.get("learning", ""))
            context = str(item.get("context", ""))
            memory_type = str(item.get("memory_type", "knowledge"))
            source = str(item.get("source", ""))
            body = (
                f"## Memory Suggestion\n\n"
                f"**Type:** {memory_type}\n\n"
                f"**Learning:** {learning}\n\n"
                f"**Context:** {context}\n\n"
                f"**Source:** {source}\n"
            )
            result.append(
                MemoryIssueData(
                    number=num,
                    title=f"[Memory] {item.get('title', '')}",
                    body=body,
                    createdAt=str(item.get("created_at", "")),
                    labels=[],
                )
            )
        return result

    async def _route_adr_candidates(self, issues: list[MemoryIssueData]) -> None:
        """Write ADR draft decisions from architecture-shift memory issues to JSONL."""
        import json as _json  # noqa: PLC0415
        from datetime import UTC, datetime  # noqa: PLC0415

        seen = self._load_adr_source_ids()
        existing_topics = load_existing_adr_topics(self._config.repo_root)
        batch_topics: set[str] = set()
        created = 0
        rejected = 0
        deduped = 0
        for issue in issues:
            try:
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

                try:
                    path = self._config.data_path("memory", "adr_decisions.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    rec = {
                        "title": adr_title,
                        "body": adr_body,
                        "type": "follow_up",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    with path.open("a") as f:
                        f.write(_json.dumps(rec) + "\n")
                    logger.info("ADR decision recorded: %s", adr_title)
                    seen.add(source_id)
                    batch_topics.add(topic_key)
                    created += 1
                except OSError:
                    logger.debug("Failed to write ADR decision", exc_info=True)
            except Exception:
                logger.exception(
                    "Error routing ADR candidate from memory issue #%s — skipping",
                    issue.get("number", "?"),
                )

        if created or deduped:
            self._save_adr_source_ids(seen)
        logger.info(
            "ADR routing summary: created=%d rejected=%d deduped=%d tracked_sources=%d",
            created,
            rejected,
            deduped,
            len(seen),
        )

    @staticmethod
    def _is_memory_issue(issue: MemoryIssueData) -> bool:
        title = str(issue.get("title", "")).strip()
        return title.startswith("[Memory]")

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
            "- Include links back to source memory and related issues/PRs\n"
            "- Cite source files by function/class name only (e.g. `src/foo.py:MyClass`) — "
            "do NOT include line numbers, they become stale\n\n"
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

    def _load_adr_source_ids(self) -> set[int]:
        return {int(v) for v in self._adr_sources.get() if v.isdigit()}

    def _save_adr_source_ids(self, issue_ids: set[int]) -> None:
        self._adr_sources.set_all({str(i) for i in issue_ids})

    @staticmethod
    def _extract_learning(body: str) -> str:
        """Extract the learning content from an issue body.

        Looks for a ``## Memory Suggestion`` section with a
        ``**Learning:**`` line.  Falls back to the full body.
        """
        if not body or not body.strip():
            return ""

        # Try structured extraction
        learning_match = re.search(
            r"\*\*Learning:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)",
            body,
            re.DOTALL,
        )
        if learning_match:
            return learning_match.group(1).strip()

        # Fallback: return full body (stripped)
        return body.strip()

    @staticmethod
    def _extract_memory_type(body: str) -> MemoryType:
        """Extract the memory type from an issue body.

        Looks for a ``**Type:**`` line.  Defaults to ``MemoryType.KNOWLEDGE``
        when the field is missing or unrecognised.
        """
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
