"""Memory digest system for persistent agent learnings."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from file_util import atomic_write
from manifest import ProjectManifestManager
from manifest_curator import CuratedLearning, CuratedManifestStore
from manifest_issue_syncer import ManifestIssueSyncer
from models import (
    MEMORY_TYPE_DISPLAY_ORDER,
    MemoryIssueData,
    MemorySyncResult,
    MemoryType,
)
from state import StateTracker
from subprocess_util import make_clean_env

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


def load_memory_digest(config: HydraFlowConfig) -> str:
    """Read the memory digest from disk if it exists.

    Returns an empty string if the file is missing or empty.
    Content is capped at ``config.max_memory_prompt_chars``.
    """
    digest_path = config.data_path("memory", "digest.md")
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
        prs: PRPort | None = None,
        *,
        manifest_store: CuratedManifestStore | None = None,
        manifest_manager: ProjectManifestManager | None = None,
        manifest_syncer: ManifestIssueSyncer | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._runner = runner or get_default_runner()
        self._prs = prs
        self._manifest_store = manifest_store or CuratedManifestStore(config)
        self._manifest_manager = manifest_manager or ProjectManifestManager(
            config, curator=self._manifest_store
        )
        self._manifest_syncer = manifest_syncer

    _TypedLearning = tuple[int, str, str, MemoryType]
    _LearningRecord = CuratedLearning | _TypedLearning

    @staticmethod
    def _coerce_learning_tuple(
        record: _LearningRecord,
    ) -> tuple[int, str, str, MemoryType]:
        """Normalize curated objects and legacy tuple records to a single shape."""
        if isinstance(record, tuple):
            num, learning, created, memory_type = record
            return num, learning, created, memory_type
        return (
            record.number,
            record.learning,
            record.created_at,
            record.memory_type,
        )

    async def sync(self, issues: list[MemoryIssueData]) -> MemorySyncResult:
        """Main sync entry point.

        *issues* is a list of dicts with ``number``, ``title``, ``body``,
        and ``createdAt`` keys (from ``gh issue list --json``).

        Returns stats dict for event publishing.
        """
        current_ids = sorted(i["number"] for i in issues)
        prev_ids, prev_hash, _ = self._state.get_memory_state()

        if not issues:
            pruned = 0
            if self._config.memory_prune_stale_items:
                pruned = self._prune_stale_items([])
            self._state.update_memory_state([], prev_hash)
            self._manifest_store.update_from_learnings([])
            await self._refresh_manifest("memory-sync-empty")
            return {
                "action": "synced",
                "item_count": 0,
                "compacted": False,
                "digest_chars": 0,
                "pruned": pruned,
                "issues_closed": 0,
            }

        # Extract learnings (now typed) and build digest
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

        # Sort newest first
        learnings.sort(key=lambda item: item.created_at, reverse=True)

        # Build digest
        compacted = False
        digest = self._build_digest(learnings)
        max_chars = self._config.max_memory_chars
        if len(digest) > max_chars:
            digest = await self._compact_digest(learnings, max_chars)
            compacted = True

        # Write individual items
        items_dir = self._config.data_path("memory", "items")
        items_dir.mkdir(parents=True, exist_ok=True)
        for record in learnings:
            num, learning, _, _ = self._coerce_learning_tuple(record)
            item_path = items_dir / f"{num}.md"
            item_path.write_text(learning)

        # Prune stale item files
        pruned = 0
        if self._config.memory_prune_stale_items:
            pruned = self._prune_stale_items(current_ids)

        # Atomic write of digest
        self._write_digest(digest)

        # Update state
        digest_hash = hashlib.sha256(digest.encode()).hexdigest()[:16]
        self._state.update_memory_state(current_ids, digest_hash)
        self._manifest_store.update_from_learnings(learnings)
        await self._refresh_manifest("memory-sync")
        await self._route_adr_candidates(issues)
        closed, _close_failed = await self._close_synced_issues(issues)

        return {
            "action": "synced",
            "item_count": len(learnings),
            "compacted": compacted,
            "digest_chars": len(digest),
            "pruned": pruned,
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

    def _prune_stale_items(self, current_ids: list[int]) -> int:
        """Remove item files whose source issue is no longer active.

        Returns the number of pruned files.
        """
        items_dir = self._config.data_path("memory", "items")
        if not items_dir.is_dir():
            return 0
        active = set(current_ids)
        pruned = 0
        for path in items_dir.glob("*.md"):
            try:
                file_id = int(path.stem)
            except ValueError:
                continue
            if file_id not in active:
                path.unlink()
                pruned += 1
        if pruned:
            logger.info("Pruned %d stale memory item files", pruned)
        return pruned

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

            issue_num = await self._prs.create_issue(
                adr_title,
                adr_body,
                list(self._config.find_label[:1]),
            )
            if issue_num:
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
    def _build_digest(learnings: Sequence[_LearningRecord]) -> str:
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
        for record in learnings:
            num, learning, _, memory_type = MemorySyncWorker._coerce_learning_tuple(
                record
            )
            by_type.setdefault(memory_type, []).append((num, learning))

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
        self, learnings: Sequence[_LearningRecord], max_chars: int
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
        unique: list[MemorySyncWorker._LearningRecord] = []

        for record in learnings:
            num, learning, created, mtype = self._coerce_learning_tuple(record)
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
        for record in unique:
            num, learning, _, memory_type = self._coerce_learning_tuple(record)
            by_type.setdefault(memory_type, []).append((num, learning))

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
        tool = self._config.memory_compaction_tool
        model = self._config.memory_compaction_model
        prompt = (
            f"Condense the following agent learnings into at most {max_chars} characters. "
            "Preserve every distinct insight but merge overlapping ones. "
            "Output ONLY the condensed markdown list — no preamble.\n\n"
            f"{content}"
        )
        if tool == "codex":
            cmd = [
                "codex",
                "exec",
                "--json",
                "--model",
                model,
                "--sandbox",
                "danger-full-access",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                prompt,
            ]
            cmd_input = None
        else:
            cmd = ["claude", "-p", prompt, "--model", model]
            cmd_input = None
        env = make_clean_env(self._config.gh_token)

        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self._config.memory_compaction_timeout,
            )
            if result.returncode != 0:
                stderr_excerpt = result.stderr[:200]
                stdout_excerpt = result.stdout[:200]
                logger.warning(
                    "Memory compaction model failed (rc=%d, model=%s): stderr=%r stdout=%r",
                    result.returncode,
                    model,
                    stderr_excerpt,
                    stdout_excerpt,
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
        digest_path = self._config.data_path("memory", "digest.md")
        atomic_write(digest_path, content)

    async def publish_sync_event(self, stats: MemorySyncResult) -> None:
        """Publish a MEMORY_SYNC event with *stats*."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.MEMORY_SYNC,
                data=dict(stats),
            )
        )
