"""Shape phase — multi-turn product design conversation."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from models import (
    ConversationTurn,
    ShapeConversation,
    Task,
)
from phase_utils import (
    MemorySuggester,  # noqa: TCH001
    _sentry_transaction,
    run_refilling_pool,
    store_lifecycle,
)
from pr_manager import PRManager
from shape_runner import ShapeRunner  # noqa: TCH001
from state import StateTracker
from task_source import TaskTransitioner
from whatsapp_bridge import WhatsAppBridge  # noqa: TCH001

logger = logging.getLogger("hydraflow.shape_phase")

_SHAPE_OPTIONS_MARKER = "## Product Directions"
_SHAPE_TURN_MARKER = "**Shape Turn"
_FINALIZE_RE = re.compile(
    r"\b(go with|finalize|ship it|let.s do|approved?|lgtm|"
    r"direction [a-e]|looks good|proceed|build it)\b",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(r"\b(cancel|nevermind|close this|stop)\b", re.IGNORECASE)

# Learning signal classification
_SCOPE_NARROW_RE = re.compile(r"\b(just|only|start with|mvp|scope to|limit to)\b", re.I)
_SCOPE_EXPAND_RE = re.compile(r"\b(also|and also|what about|add|include)\b", re.I)
_POSITIVE_RE = re.compile(r"\b(like|love|yes|good|great|perfect|exactly)\b", re.I)
_NEGATIVE_RE = re.compile(r"\b(no|not|don.t|skip|drop|remove|hate)\b", re.I)


class ShapePhase:
    """Multi-turn product design conversation.

    The Shape phase is a conversation loop:
    1. Agent proposes/explores/refines (each turn is a fresh claude -p invocation)
    2. Human responds via GitHub comment, dashboard, or WhatsApp
    3. Repeat until finalization or timeout
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStore,
        prs: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        shape_runner: ShapeRunner | None = None,
        whatsapp_bridge: WhatsAppBridge | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._runner = shape_runner
        self._whatsapp = whatsapp_bridge
        self._suggest_memory = MemorySuggester(config, prs, state)

    async def shape_issues(self) -> bool:
        """Process shape-labeled issues. Returns True if work was done."""

        async def _shape_one(_idx: int, issue: Task) -> int:
            if self._stop_event.is_set():
                return 0
            return await self._shape_single(issue)

        results = await run_refilling_pool(
            supply_fn=lambda: self._store.get_shapeable(1),
            worker_fn=_shape_one,
            max_concurrent=self._config.max_triagers,
            stop_event=self._stop_event,
        )
        return bool(sum(results))

    async def _shape_single(self, issue: Task) -> int:
        """Run one iteration of the shape conversation for a single issue."""
        with _sentry_transaction("pipeline.shape", f"shape:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "shape"):
                conv = self._state.get_shape_conversation(issue.id)
                if not conv:
                    conv = ShapeConversation(
                        issue_number=issue.id,
                        started_at=datetime.now(UTC).isoformat(),
                    )

                # If last turn was agent, check for human response
                if conv.turns and conv.turns[-1].role == "agent":
                    response = await self._check_for_response(issue)
                    if response:
                        signal = self._classify_signal(response)
                        conv.turns.append(
                            ConversationTurn(
                                role="human",
                                content=response,
                                timestamp=datetime.now(UTC).isoformat(),
                                signal=signal,
                            )
                        )
                        conv.last_activity_at = datetime.now(UTC).isoformat()
                        self._state.set_shape_conversation(issue.id, conv)

                        # Write per-turn learning signal
                        await self._write_turn_signal(issue, conv, response, signal)

                        if _CANCEL_RE.search(response):
                            logger.info(
                                "Issue #%d shape — cancelled by human", issue.id
                            )
                            self._state.remove_shape_conversation(issue.id)
                            return 1

                        if _FINALIZE_RE.search(response):
                            conv.status = "finalizing"
                    else:
                        # No response yet — check timeout
                        if self._is_timed_out(conv):
                            conv.status = "timed_out"
                            self._state.set_shape_conversation(issue.id, conv)
                            await self._transitioner.post_comment(
                                issue.id,
                                "**Shape conversation timed out.** "
                                "Reply to this issue to resume the design conversation.",
                            )
                            logger.info("Issue #%d shape — timed out", issue.id)
                            return 0
                        # Re-enqueue for next poll cycle
                        self._store.enqueue_transition(issue, "shape")
                        return 0

                # Check max turns
                if len(conv.turns) >= self._config.max_shape_turns:
                    conv.status = "finalizing"

                # Run agent turn
                if not self._runner:
                    await self._transitioner.post_comment(
                        issue.id,
                        "Shape runner not configured. Manual product design required.",
                    )
                    return 1

                research_brief = self._extract_research_brief(issue)
                # Query learned preferences for cross-issue context (first turn only)
                learned = ""
                if (
                    not conv.turns
                    and self._runner
                    and getattr(self._runner, "_hindsight", None)
                ):
                    learned = await self._recall_preferences(issue)
                result = await self._runner.run_turn(
                    issue,
                    conv,
                    research_brief=research_brief,
                    learned_preferences=learned,
                )

                conv.turns.append(
                    ConversationTurn(
                        role="agent",
                        content=result.content,
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                )
                conv.last_activity_at = datetime.now(UTC).isoformat()
                self._state.set_shape_conversation(issue.id, conv)

                if result.is_final or conv.status == "finalizing":
                    await self._process_finalization(issue, conv, result.content)
                    conv.status = "done"
                    self._state.set_shape_conversation(issue.id, conv)
                    return 1

                # Post agent turn and wait for response
                await self._post_conversation_turn(
                    issue, result.content, len(conv.turns)
                )
                self._store.enqueue_transition(issue, "shape")

                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SHAPE_UPDATE,
                        data={
                            "issue": issue.id,
                            "action": "turn_posted",
                            "turn": len(conv.turns),
                        },
                    )
                )
                return 1

    async def _check_for_response(self, issue: Task) -> str | None:
        """Check GitHub comments, dashboard input, and WhatsApp for a human response."""
        # Source 1: GitHub comments (primary)
        enriched = await self._store.enrich_with_comments(issue)
        github_response = self._find_human_reply(enriched.comments or [])
        if github_response:
            return github_response

        # Source 2: Dashboard human-input (if available via orchestrator)
        # This is checked by the orchestrator's HITL controller — responses
        # are posted as GitHub comments, so they'll appear in Source 1

        # Source 3: WhatsApp (if configured)
        # WhatsApp inbound webhook posts to human-input API → GitHub comment
        # So this also appears in Source 1

        return None

    def _find_human_reply(self, comments: list[str]) -> str | None:
        """Find the most recent human comment after the last agent turn."""
        last_agent_idx = -1
        for i, comment in enumerate(comments):
            if _SHAPE_TURN_MARKER in comment or _SHAPE_OPTIONS_MARKER in comment:
                last_agent_idx = i

        if last_agent_idx == -1:
            return None

        # Look for human comments after the last agent comment
        for comment in comments[last_agent_idx + 1 :]:
            if (
                _SHAPE_TURN_MARKER not in comment
                and _SHAPE_OPTIONS_MARKER not in comment
            ):
                return comment.strip()

        return None

    async def _post_conversation_turn(
        self, issue: Task, content: str, turn_num: int
    ) -> None:
        """Post an agent turn to GitHub and notify via WhatsApp."""
        comment = (
            f"{_SHAPE_TURN_MARKER} {turn_num}** — Product Design Conversation\n\n"
            f"{content}\n\n"
            "---\n"
            '*Reply to continue the conversation, or say "ship it" to finalize.*'
        )
        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, comment)

            # Save HTML artifact for visual viewing
            html = self.format_options_html(issue, content, turn_num)
            self._save_html_artifact(issue.id, html)

            # WhatsApp notification
            if self._whatsapp and hasattr(self._whatsapp, "send_shape_turn"):
                try:
                    artifact_url = (
                        f"{self._config.dashboard_url}/api/shape/artifact/{issue.id}"
                    )
                    await self._whatsapp.send_shape_turn(
                        issue.id, issue.title, content[:300], artifact_url
                    )
                except Exception:
                    logger.warning(
                        "WhatsApp notification failed for issue #%d",
                        issue.id,
                        exc_info=True,
                    )

    async def _process_finalization(
        self, issue: Task, conv: ShapeConversation, final_content: str
    ) -> None:
        """Process the final shape output and transition to plan."""
        enrichment_parts = [
            "## Final Product Direction\n",
            f"{final_content}\n",
            "\n### Planning Guidance — DECOMPOSITION REQUIRED\n\n"
            "This issue came through the product discovery and shaping track. "
            "It is a BROAD product direction, NOT a single implementable task.\n\n"
            "**You MUST decompose this into 3-8 concrete sub-issues** using the "
            "NEW_ISSUES_START/NEW_ISSUES_END format. Each sub-issue should:\n"
            "- Be independently implementable and testable\n"
            "- Be scoped to a single concern\n"
            "- Have clear acceptance criteria\n"
            "- Reference the product direction above for context",
        ]
        enrichment = "\n".join(enrichment_parts)

        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, enrichment)
            self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            self._state.increment_session_counter("shaped")

        # Write finalization learning signal
        await self._write_finalization_signal(issue, conv)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={
                    "issue": issue.id,
                    "action": "finalized",
                    "turns": len(conv.turns),
                },
            )
        )
        logger.info(
            "Issue #%d shape finalized after %d turns → %s",
            issue.id,
            len(conv.turns),
            self._config.planner_label[0],
        )

    async def _write_turn_signal(
        self, issue: Task, conv: ShapeConversation, response: str, signal: str
    ) -> None:
        """Write per-turn learning signal to memory."""
        turn_num = len(conv.turns)
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            f"title: Shape turn {turn_num} signal for #{issue.id}\n"
            f"learning: Turn {turn_num} for '{issue.title}': "
            f"human response classified as '{signal}'. "
            f"Response excerpt: '{response[:80]}'\n"
            f"context: Shape conversation turn {turn_num} for issue #{issue.id}\n"
            "type: knowledge\n"
            "MEMORY_SUGGESTION_END"
        )
        await self._suggest_memory(transcript, "shape", f"issue #{issue.id}")

    async def _write_finalization_signal(
        self, issue: Task, conv: ShapeConversation
    ) -> None:
        """Write comprehensive finalization learning signal."""
        turn_count = len(conv.turns)
        human_turns = [t for t in conv.turns if t.role == "human"]
        signals = [t.signal for t in human_turns if t.signal]
        taste_tokens = set()
        for t in human_turns:
            for word in re.findall(
                r"\b(simple|clean|fast|powerful|minimal|elegant|robust)\b",
                t.content,
                re.I,
            ):
                taste_tokens.add(word.lower())

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            f"title: Shape conversation completed for #{issue.id}\n"
            f"learning: Shaped '{issue.title}' in {turn_count} turns. "
            f"Signals: {', '.join(signals) if signals else 'none classified'}. "
            f"Taste tokens: {', '.join(taste_tokens) if taste_tokens else 'none extracted'}. "
            f"Conversation depth indicates {'deep exploration' if turn_count > 6 else 'quick decision'}.\n"
            f"context: Shape finalization for issue #{issue.id}\n"
            "type: knowledge\n"
            "MEMORY_SUGGESTION_END"
        )
        await self._suggest_memory(transcript, "shape", f"issue #{issue.id}")

    def _is_timed_out(self, conv: ShapeConversation) -> bool:
        """Check if the conversation has timed out."""
        if not conv.last_activity_at:
            return False
        last = datetime.fromisoformat(conv.last_activity_at)
        elapsed = (datetime.now(UTC) - last).total_seconds() / 60
        return elapsed > self._config.shape_timeout_minutes

    @staticmethod
    def _classify_signal(response: str) -> str:
        """Classify a human response for learning signal."""
        if _SCOPE_NARROW_RE.search(response):
            return "scope_narrow"
        if _SCOPE_EXPAND_RE.search(response):
            return "scope_expand"
        if _POSITIVE_RE.search(response):
            return "positive"
        if _NEGATIVE_RE.search(response):
            return "negative"
        return "neutral"

    async def _recall_preferences(self, issue: Task) -> str:
        """Query hindsight for learned product preferences and related decisions."""
        try:
            from hindsight import (  # noqa: PLC0415
                Bank,
                format_memories_as_markdown,
                recall_safe,
            )

            query = f"product direction preferences scope decisions for {issue.title}"
            hindsight = getattr(self._runner, "_hindsight", None)
            if not hindsight:
                return ""
            memories = await recall_safe(hindsight, Bank.LEARNINGS, query, limit=5)
            if memories:
                return format_memories_as_markdown(memories)
        except Exception:
            logger.debug("Hindsight recall failed for shape preferences", exc_info=True)
        return ""

    def _extract_research_brief(self, issue: Task) -> str:
        """Extract discovery research brief from issue comments if available."""
        for comment in issue.comments or []:
            if "## Product Discovery Brief" in comment:
                return comment
        return ""

    def _save_html_artifact(self, issue_number: int, html: str) -> None:
        """Save HTML artifact for dashboard/canvas serving."""
        artifacts_dir = self._config.data_root / "artifacts" / "shape"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / f"issue-{issue_number}.html"
        path.write_text(html, encoding="utf-8")

    @staticmethod
    def format_options_html(issue: Task, content: str, turn_num: int) -> str:
        """Render a conversation turn as self-contained HTML."""
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shape #{issue.id} — Turn {turn_num}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:#0d1117; color:#c9d1d9; padding:24px; line-height:1.6; }}
  h1 {{ font-size:18px; margin-bottom:4px; }}
  .subtitle {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .content {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
              padding:20px; font-size:14px; white-space:pre-wrap; }}
  .footer {{ margin-top:16px; color:#8b949e; font-size:12px; font-style:italic; }}
</style></head><body>
<h1>Shape Conversation — #{issue.id}</h1>
<p class="subtitle">{issue.title} · Turn {turn_num}</p>
<div class="content">{content}</div>
<p class="footer">Reply on GitHub, the dashboard, or WhatsApp to continue.</p>
</body></html>"""
