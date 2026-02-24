"""Memory digest system for persistent agent learnings."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from file_util import atomic_write
from models import (
    MEMORY_TYPE_DISPLAY_ORDER,
    MemoryIssueData,
    MemorySyncResult,
    MemoryType,
)
from state import StateTracker
from subprocess_util import make_clean_env

if TYPE_CHECKING:
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.memory")


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


def load_memory_digest(config: HydraFlowConfig) -> str:
    """Read the memory digest from disk if it exists.

    Returns an empty string if the file is missing or empty.
    Content is capped at ``config.max_memory_prompt_chars``.
    """
    digest_path = config.repo_root / ".hydraflow" / "memory" / "digest.md"
    if not digest_path.is_file():
        return ""
    try:
        content = digest_path.read_text()
    except OSError:
        return ""
    if not content.strip():
        return ""
    max_chars = config.max_memory_prompt_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n…(truncated)"
    return content


async def file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
    prs: PRManager,
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
    #   auto_approve=True  + knowledge   -> memory_label directly (auto-approved)
    #   auto_approve=True  + actionable  -> HITL (actionable always needs human review)
    #   auto_approve=False + knowledge   -> improve_label only (no HITL)
    #   auto_approve=False + actionable  -> improve_label + hitl_label (HITL)
    if MemoryType.is_actionable(memory_type):
        # Actionable types ALWAYS go through HITL regardless of auto-approve
        labels = list(config.improve_label) + list(config.hitl_label)
        hitl_cause = f"Actionable memory suggestion ({memory_type.value})"
    elif config.memory_auto_approve:
        # Knowledge + auto-approve: skip HITL, label for memory sync pickup
        labels = list(config.memory_label)
        hitl_cause = None
    else:
        # Knowledge + no auto-approve: normal improve pipeline
        labels = list(config.improve_label)
        hitl_cause = None

    issue_num = await prs.create_issue(title, body, labels)
    if issue_num:
        if hitl_cause is not None:
            state.set_hitl_origin(issue_num, config.improve_label[0])
            state.set_hitl_cause(issue_num, hitl_cause)
        logger.info(
            "Filed %s memory suggestion as issue #%d: %s",
            memory_type.value,
            issue_num,
            suggestion["title"],
        )


class MemorySyncWorker:
    """Polls ``hydraflow-memory`` issues and compiles them into a local digest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._runner = runner or get_default_runner()

    # Type alias for typed learning tuples:
    # (issue_number, learning_text, created_at, memory_type)
    _TypedLearning = tuple[int, str, str, MemoryType]

    async def sync(self, issues: list[MemoryIssueData]) -> MemorySyncResult:
        """Main sync entry point.

        *issues* is a list of dicts with ``number``, ``title``, ``body``,
        and ``createdAt`` keys (from ``gh issue list --json``).

        Returns stats dict for event publishing.
        """
        current_ids = sorted(i["number"] for i in issues)
        prev_ids, prev_hash, _ = self._state.get_memory_state()

        if not issues:
            self._state.update_memory_state([], prev_hash)
            return {
                "action": "synced",
                "item_count": 0,
                "compacted": False,
                "digest_chars": 0,
            }

        # Check if issue set changed
        if current_ids == sorted(prev_ids):
            # No change — just update timestamp
            self._state.update_memory_state(current_ids, prev_hash)
            digest_path = self._config.repo_root / ".hydraflow" / "memory" / "digest.md"
            digest_chars = len(digest_path.read_text()) if digest_path.is_file() else 0
            return {
                "action": "synced",
                "item_count": len(issues),
                "compacted": False,
                "digest_chars": digest_chars,
            }

        # Extract learnings (now typed) and build digest
        learnings: list[MemorySyncWorker._TypedLearning] = []
        for issue in issues:
            body = issue.get("body", "")
            learning = self._extract_learning(body)
            created = issue.get("createdAt", "")
            memory_type = self._extract_memory_type(body)
            if learning:
                learnings.append((issue["number"], learning, created, memory_type))

        # Sort newest first
        learnings.sort(key=lambda x: x[2], reverse=True)

        # Build digest
        compacted = False
        digest = self._build_digest(learnings)
        max_chars = self._config.max_memory_chars
        if len(digest) > max_chars:
            digest = await self._compact_digest(learnings, max_chars)
            compacted = True

        # Write individual items
        items_dir = self._config.repo_root / ".hydraflow" / "memory" / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        for num, learning, _, _ in learnings:
            item_path = items_dir / f"{num}.md"
            item_path.write_text(learning)

        # Atomic write of digest
        self._write_digest(digest)

        # Update state
        digest_hash = hashlib.sha256(digest.encode()).hexdigest()[:16]
        self._state.update_memory_state(current_ids, digest_hash)

        return {
            "action": "synced",
            "item_count": len(learnings),
            "compacted": compacted,
            "digest_chars": len(digest),
        }

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

    @staticmethod
    def _build_digest(learnings: list[_TypedLearning]) -> str:
        """Build the digest markdown grouped by memory type.

        Learnings are organised into sections by type (actionable types
        first, then knowledge) for easy scanning by agents.
        """
        now = datetime.now(UTC).isoformat()
        header = (
            f"## Accumulated Learnings\n"
            f"*{len(learnings)} learnings — last synced {now}*\n"
        )

        # Group learnings by type
        by_type: dict[MemoryType, list[tuple[int, str]]] = {}
        for num, learning, _, mtype in learnings:
            by_type.setdefault(mtype, []).append((num, learning))

        sections: list[str] = []
        for mtype in MEMORY_TYPE_DISPLAY_ORDER:
            items = by_type.get(mtype, [])
            if not items:
                continue
            type_header = f"### {mtype.value.title()}"
            type_items = [f"- **#{num}:** {learning}" for num, learning in items]
            sections.append(type_header + "\n" + "\n".join(type_items))

        return header + "\n" + "\n---\n".join(sections) + "\n"

    async def _compact_digest(
        self, learnings: list[_TypedLearning], max_chars: int
    ) -> str:
        """Deduplicate and optionally summarise learnings to fit within *max_chars*.

        Pipeline:
        1. Keyword-overlap deduplication (>70% overlap → drop duplicate).
        2. Rebuild digest from unique items (grouped by type).
        3. If still over *max_chars*: call a cheap model to summarise.
        4. Final truncation safety-net in case the model returns too much.
        """
        # --- Step 1: Deduplicate by keyword overlap ---
        seen_keywords: list[set[str]] = []
        unique: list[MemorySyncWorker._TypedLearning] = []

        for num, learning, created, mtype in learnings:
            words = {
                w.lower() for w in re.findall(r"[a-zA-Z]+", learning) if len(w) >= 4
            }
            is_dup = False
            for existing in seen_keywords:
                if not words or not existing:
                    continue
                overlap = len(words & existing) / max(len(words), 1)
                if overlap > 0.7:
                    is_dup = True
                    break
            if not is_dup:
                unique.append((num, learning, created, mtype))
                seen_keywords.append(words)

        # --- Step 2: Build digest from unique items (grouped by type) ---
        now = datetime.now(UTC).isoformat()
        header = (
            f"## Accumulated Learnings\n"
            f"*{len(unique)} learnings (compacted) — last synced {now}*\n"
        )

        by_type: dict[MemoryType, list[tuple[int, str]]] = {}
        for num, learning, _, mtype in unique:
            by_type.setdefault(mtype, []).append((num, learning))

        sections: list[str] = []
        for mtype in MEMORY_TYPE_DISPLAY_ORDER:
            items = by_type.get(mtype, [])
            if not items:
                continue
            type_header = f"### {mtype.value.title()}"
            type_items = [f"- **#{num}:** {learning}" for num, learning in items]
            sections.append(type_header + "\n" + "\n".join(type_items))

        digest = header + "\n" + "\n---\n".join(sections) + "\n"

        # --- Step 3: Model-based summarisation if still over limit ---
        if len(digest) > max_chars:
            summarised = await self._summarise_with_model(digest, max_chars)
            if summarised:
                digest = summarised

        # --- Step 4: Final truncation safety-net ---
        if len(digest) > max_chars:
            digest = digest[:max_chars] + "\n\n…(truncated)"

        return digest

    async def _summarise_with_model(self, content: str, max_chars: int) -> str | None:
        """Use a cheap model to condense the digest.

        Returns the summarised text or ``None`` on failure (caller
        falls back to truncation).
        """
        model = self._config.memory_compaction_model
        prompt = (
            f"Condense the following agent learnings into at most {max_chars} characters. "
            "Preserve every distinct insight but merge overlapping ones. "
            "Output ONLY the condensed markdown list — no preamble.\n\n"
            f"{content}"
        )
        cmd = ["claude", "-p", "--model", model]
        env = make_clean_env(self._config.gh_token)

        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=prompt.encode(),
                timeout=self._config.memory_compaction_timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "Memory compaction model failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:200],
                )
                return None
            if not result.stdout:
                return None
            now = datetime.now(UTC).isoformat()
            return (
                f"## Accumulated Learnings\n"
                f"*Summarised — last synced {now}*\n\n"
                f"{result.stdout}\n"
            )
        except TimeoutError:
            logger.warning("Memory compaction model timed out")
            return None
        except (OSError, FileNotFoundError, NotImplementedError, RuntimeError) as exc:
            logger.warning("Memory compaction model unavailable: %s", exc)
            return None

    def _write_digest(self, content: str) -> None:
        """Write digest to disk atomically."""
        digest_path = self._config.repo_root / ".hydraflow" / "memory" / "digest.md"
        atomic_write(digest_path, content)

    async def publish_sync_event(self, stats: MemorySyncResult) -> None:
        """Publish a MEMORY_SYNC event with *stats*."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.MEMORY_SYNC,
                data=dict(stats),
            )
        )
