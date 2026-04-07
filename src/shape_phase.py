"""Shape phase — multi-turn product design conversation."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hindsight import HindsightClient

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from expert_council import CouncilResult, ExpertCouncil  # noqa: TCH001
from issue_store import IssueStore
from models import (
    ConversationTurn,
    ShapeConversation,
    ShapeResult,  # noqa: TCH001
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
        hindsight: HindsightClient | None = None,
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
        self._council: ExpertCouncil | None = None
        self._suggest_memory = MemorySuggester(config, hindsight=hindsight)

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
        """Run one iteration of the shape conversation for a single issue.

        Two modes of operation:

        1. **Comment-based selection** (always active): checks issue comments
           for an existing options marker.  If found, looks for a direction
           selection; if not found, generates options and posts them.

        2. **Agent-driven conversation** (when ``shape_runner`` is configured):
           uses a multi-turn agent loop with research briefs and memory recall.

        The comment-based path runs first so that selection detection works
        even when the runner is available.
        """
        with _sentry_transaction("pipeline.shape", f"shape:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "shape"):
                # --- Comment-based selection flow ---
                enriched = await self._store.enrich_with_comments(issue)
                comments = enriched.comments or []

                has_options = any(_SHAPE_OPTIONS_MARKER in c for c in comments)

                if has_options:
                    # Options already posted — check for selection
                    selection = self._find_selection(comments)
                    if selection:
                        self._store.enqueue_transition(issue, "plan")
                        await self._prs.transition(issue.id, "plan")
                        self._state.increment_session_counter("shaped")
                        return 1
                    # No selection yet — re-enqueue and wait
                    self._store.enqueue_transition(issue, "shape")
                    return 0

                # --- No options marker: generate options ---

                # If we have a runner, use the full conversation loop
                if self._runner:
                    return await self._shape_with_runner(issue)

                # No runner — post stub options via comment
                comment = (
                    f"{_SHAPE_OPTIONS_MARKER} for #{issue.id}\n\n"
                    "### Direction A: Quick & Focused\n"
                    "Minimal implementation targeting the core need.\n\n"
                    "### Direction B: Comprehensive\n"
                    "Full-featured approach addressing all aspects.\n\n"
                    "---\n"
                    '*Reply with your selection (e.g., "Direction A").*'
                )
                await self._prs.post_comment(issue.id, comment)
                self._store.enqueue_transition(issue, "shape")
                return 1

    async def _shape_with_runner(self, issue: Task) -> int:
        """Run one agent-driven conversation turn using the shape runner."""
        conv = self._state.get_shape_conversation(issue.id)
        if not conv:
            conv = ShapeConversation(
                issue_number=issue.id,
                started_at=datetime.now(UTC).isoformat(),
            )

        # Handle waiting states (timed-out or awaiting response)
        proceed, cancelled = await self._handle_waiting_state(issue, conv)
        if cancelled:
            return 1
        if not proceed:
            return 0

        # Check max turns
        if len(conv.turns) >= self._config.max_shape_turns:
            conv.status = "finalizing"

        research_brief = self._extract_research_brief(issue)
        learned = ""
        if (
            not conv.turns
            and self._runner
            and getattr(self._runner, "_hindsight", None)
        ):
            learned = await self._recall_preferences(issue)
        assert self._runner is not None  # guaranteed by caller
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
        self._truncate_old_turns(conv)
        self._state.set_shape_conversation(issue.id, conv)

        if result.is_final or conv.status == "finalizing":
            await self._process_finalization(issue, conv, result.content)
            conv.status = "done"
            self._state.set_shape_conversation(issue.id, conv)
            return 1

        # After first agent turn with directions, run expert council vote
        if len(conv.turns) == 1 and self._council:
            council_result = await self._run_council_vote(issue, conv, result.content)
            if council_result:
                return council_result

        # No consensus or no council — post turn and wait for human
        await self._post_conversation_turn(issue, result.content, len(conv.turns), conv)
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

    async def _run_council_vote(
        self, issue: Task, conv: ShapeConversation, directions_content: str
    ) -> int | None:
        """Run expert council vote with up to 2 rounds before human escalation.

        Round 1: Each expert votes independently.
        Round 2 (if split): Experts see each other's votes and reasoning,
                then revote with the full context — often reaches consensus.
        If still split after 2 rounds: escalate to human.

        Returns 1 if consensus reached and issue transitioned to plan.
        Returns None if no consensus after 2 rounds.
        """
        assert self._council is not None  # guaranteed by caller
        max_rounds = 2
        prev_result: CouncilResult | None = None

        for round_num in range(1, max_rounds + 1):
            if round_num == 1 or prev_result is None:
                council_result = await self._council.vote(issue, directions_content)
            else:
                # Mediate: synthesize the disagreement before revoting
                mediation = await self._council.mediate(
                    issue, prev_result, directions_content
                )
                await self._transitioner.post_comment(
                    issue.id,
                    f"## Council Mediation (before Round {round_num})\n\n{mediation}",
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SHAPE_UPDATE,
                        data={
                            "issue": issue.id,
                            "action": "council_mediation",
                            "round": round_num,
                            "mediation": mediation[:500],
                        },
                    )
                )
                learning = (
                    "MEMORY_SUGGESTION_START\n"
                    f"principle: Mediator synthesized split council vote: {mediation[:200]}\n"
                    f"rationale: Council mediation for issue #{issue.id} round {round_num}\n"
                    f"failure_mode: Council could not reach consensus without mediation\n"
                    "scope: hydraflow/shape\n"
                    "MEMORY_SUGGESTION_END"
                )
                await self._suggest_memory(
                    learning, "shape-mediator", f"issue #{issue.id}"
                )

                # Round 2: experts see prior votes + mediation synthesis
                enriched_directions = (
                    f"{directions_content}\n\n"
                    f"## Prior Council Vote (Round {round_num - 1})\n\n"
                    f"{prev_result.format_summary()}\n\n"
                    f"## Mediator's Synthesis\n\n"
                    f"{mediation}\n\n"
                    f"Consider the mediation above. You may change your vote "
                    f"if the synthesis addresses your concerns, or hold firm "
                    f"with stronger justification for why your perspective "
                    f"should take priority."
                )
                council_result = await self._council.vote(issue, enriched_directions)

            # Post vote summary
            round_label = f" (Round {round_num})" if max_rounds > 1 else ""
            await self._transitioner.post_comment(
                issue.id, f"{council_result.format_summary()}\n*{round_label}*"
            )

            # Track the decision
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SHAPE_UPDATE,
                    data={
                        "issue": issue.id,
                        "action": "council_vote",
                        "round": round_num,
                        "decision": {
                            "type": "council_auto"
                            if council_result.has_consensus
                            else "council_split",
                            "votes": council_result.to_dict(),
                        },
                    },
                )
            )

            if council_result.has_consensus:
                winner = council_result.winning_direction
                logger.info(
                    "Issue #%d shape — council consensus on Direction %s "
                    "in round %d (confidence %.1f) — auto-selecting",
                    issue.id,
                    winner,
                    round_num,
                    council_result.avg_confidence,
                )
                learning = (
                    "MEMORY_SUGGESTION_START\n"
                    f"principle: Expert council reached consensus on Direction {winner} "
                    f"for '{issue.title}' in round {round_num} with avg confidence "
                    f"{council_result.avg_confidence:.1f}/10\n"
                    f"rationale: Expert council vote for issue #{issue.id} automated the decision without human input\n"
                    f"failure_mode: Without council automation, shape would have required human selection\n"
                    "scope: hydraflow/shape\n"
                    "MEMORY_SUGGESTION_END"
                )
                await self._suggest_memory(
                    learning, "shape-council", f"issue #{issue.id}"
                )

                conv.turns.append(
                    ConversationTurn(
                        role="agent",
                        content=f"Council consensus (round {round_num}): Direction {winner}\n\n{council_result.format_summary()}",
                        timestamp=datetime.now(UTC).isoformat(),
                        signal="council_consensus",
                    )
                )
                conv.status = "done"
                self._state.set_shape_conversation(issue.id, conv)
                await self._process_finalization(
                    issue,
                    conv,
                    f"Direction {winner} selected by expert council consensus (round {round_num}).\n\n{directions_content}",
                )
                return 1

            # Split — save for next round context
            logger.info(
                "Issue #%d shape — council split in round %d",
                issue.id,
                round_num,
            )

        # Exhausted all rounds — escalate to human
        logger.info(
            "Issue #%d shape — council split after %d rounds, escalating to human",
            issue.id,
            max_rounds,
        )
        learning = (
            "MEMORY_SUGGESTION_START\n"
            f"principle: Expert council could not reach consensus for '{issue.title}' "
            f"after {max_rounds} voting rounds — human tiebreaker needed\n"
            f"rationale: Expert council vote for issue #{issue.id} split after {max_rounds} rounds\n"
            f"failure_mode: Council automation exhausted rounds without consensus\n"
            "scope: hydraflow/shape\n"
            "MEMORY_SUGGESTION_END"
        )
        await self._suggest_memory(learning, "shape-council", f"issue #{issue.id}")
        return None

    async def _handle_waiting_state(
        self, issue: Task, conv: ShapeConversation
    ) -> tuple[bool, bool]:
        """Handle timed-out or waiting-for-response states.

        Returns (proceed, cancelled):
        - (True, False): ready for next agent turn
        - (False, False): re-enqueued, waiting
        - (True, True): cancelled by human
        """
        needs_response = conv.status == "timed_out" or (
            conv.turns and conv.turns[-1].role == "agent"
        )
        if not needs_response:
            return True, False

        result = await self._check_for_response(issue)
        if result is None:
            if conv.status != "timed_out" and self._is_timed_out(conv):
                conv.status = "timed_out"
                self._state.set_shape_conversation(issue.id, conv)
                await self._transitioner.post_comment(
                    issue.id,
                    "**Shape conversation timed out.** "
                    "Reply to this issue to resume the design conversation.",
                )
                logger.info("Issue #%d shape — timed out", issue.id)
            self._store.enqueue_transition(issue, "shape")
            return False, False

        response, source = result

        # Got a response — process it
        if conv.status == "timed_out":
            conv.status = "exploring"
            logger.info("Issue #%d shape — resumed from timeout", issue.id)

        signal = self._classify_signal(response)
        conv.turns.append(
            ConversationTurn(
                role="human",
                content=response,
                timestamp=datetime.now(UTC).isoformat(),
                signal=signal,
                source=source,
            )
        )
        conv.last_activity_at = datetime.now(UTC).isoformat()
        self._state.set_shape_conversation(issue.id, conv)
        await self._write_turn_signal(issue, conv, response, signal)

        if _CANCEL_RE.search(response):
            logger.info("Issue #%d shape — cancelled by human", issue.id)
            self._state.remove_shape_conversation(issue.id)
            return True, True

        if _FINALIZE_RE.search(response):
            conv.status = "finalizing"

        return True, False

    async def _check_for_response(self, issue: Task) -> tuple[str, str] | None:
        """Check all response sources for a human reply.

        Returns a (response_text, source) tuple or None.
        Source is 'whatsapp' for state-based responses or 'github' for comments.

        Checks in order: WhatsApp responses (fastest), then GitHub comments
        (authoritative). WhatsApp responses arrive via the human-input API
        before they're mirrored to GitHub, so checking them first avoids a
        one-cycle race condition.
        """
        # Source 1: WhatsApp responses (via human-input API)
        # These arrive before the GitHub comment mirror, so check first
        try:
            # Access via store's bus subscribers or state — the response
            # dict lives on the HITL controller. We check state for any
            # response keyed by issue number.
            response = self._state.get_shape_response(issue.id)
            if response:
                self._state.clear_shape_response(issue.id)
                return (response, "whatsapp")
        except Exception:
            pass

        # Source 2: GitHub comments (authoritative, works for all channels)
        enriched = await self._store.enrich_with_comments(issue)
        reply = self._find_human_reply(enriched.comments or [])
        if reply is not None:
            return (reply, "github")
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
        self,
        issue: Task,
        content: str,
        turn_num: int,
        conversation: ShapeConversation | None = None,
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

            # Save HTML artifact with full conversation thread
            conv_turns = conversation.turns if conversation else None
            html = self.format_options_html(issue, content, turn_num, conv_turns)
            self._save_html_artifact(issue.id, html)

            # WhatsApp notification
            if self._whatsapp and hasattr(self._whatsapp, "send_shape_turn"):
                try:
                    from whatsapp_bridge import WhatsAppBridge  # noqa: PLC0415

                    base = self._config.dashboard_url.rstrip("/")
                    artifact_url = f"{base}/api/shape/artifact/{issue.id}"
                    summary = WhatsAppBridge.format_condensed_summary(content)
                    await self._whatsapp.send_shape_turn(
                        issue.id, issue.title, summary, artifact_url
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
            f"principle: Turn {turn_num} for '{issue.title}': "
            f"human response classified as '{signal}' "
            f"(excerpt: '{response[:80]}')\n"
            f"rationale: Shape conversation turn {turn_num} for issue #{issue.id}\n"
            "failure_mode: Without classification, shape signals drift between turns\n"
            "scope: hydraflow/shape\n"
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
            f"principle: Shaped '{issue.title}' in {turn_count} turns — "
            f"signals: {', '.join(signals) if signals else 'none classified'}, "
            f"taste tokens: {', '.join(taste_tokens) if taste_tokens else 'none extracted'}, "
            f"depth indicates {'deep exploration' if turn_count > 6 else 'quick decision'}\n"
            f"rationale: Shape finalization summary for issue #{issue.id}\n"
            "failure_mode: Without finalization signal, shape learnings are not reusable\n"
            "scope: hydraflow/shape\n"
            "MEMORY_SUGGESTION_END"
        )
        await self._suggest_memory(transcript, "shape", f"issue #{issue.id}")

    def _find_selection(self, comments: list[str]) -> str | None:
        """Find a direction selection in comments after the options marker.

        Looks for comments containing "Direction X" or "Option X" (case-insensitive)
        that appear AFTER the ``_SHAPE_OPTIONS_MARKER``. Returns the letter (A-E)
        or None if no selection found.
        """
        marker_seen = False
        for comment in comments:
            if _SHAPE_OPTIONS_MARKER in comment:
                marker_seen = True
                continue
            if not marker_seen:
                continue
            match = re.search(
                r"\b(?:direction|option)\s+([a-e])\b", comment, re.IGNORECASE
            )
            if match:
                return match.group(1).upper()
        return None

    def _format_options(self, issue: Task, result: ShapeResult) -> str:
        """Format a ShapeResult as a markdown comment with direction options."""

        lines = [f"{_SHAPE_OPTIONS_MARKER} for #{issue.id}\n"]
        for i, d in enumerate(result.directions):
            letter = chr(65 + i)  # A, B, C, ...
            lines.append(f"### Direction {letter}: {d.name}\n")
            lines.append(f"**Approach:** {d.approach}")
            lines.append(f"**Tradeoffs:** {d.tradeoffs}")
            lines.append(f"**Effort:** {d.effort}")
            lines.append(f"**Risk:** {d.risk}")
            if d.differentiator:
                lines.append(f"**Differentiator:** {d.differentiator}")
            lines.append("")

        if result.recommendation:
            lines.append(f"### Recommendation\n\n{result.recommendation}\n")

        lines.append('---\n*Reply with your selection (e.g., "Direction A").*')
        return "\n".join(lines)

    @staticmethod
    def _truncate_old_turns(
        conv: ShapeConversation, keep_recent: int = 4, max_content: int = 500
    ) -> None:
        """Truncate old turn content to keep state.json bounded.

        Keeps the last *keep_recent* turns at full length.
        Older turns are truncated to *max_content* characters.
        """
        if len(conv.turns) <= keep_recent:
            return
        cutoff = len(conv.turns) - keep_recent
        for turn in conv.turns[:cutoff]:
            if len(turn.content) > max_content:
                turn.content = turn.content[:max_content] + "... [truncated]"

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
            memories = await recall_safe(hindsight, Bank.TRIBAL, query, limit=5)
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
    def format_options_html(
        issue: Task,
        content: str | ShapeResult,
        turn_num: int = 0,
        conversation_turns: list[ConversationTurn] | None = None,
    ) -> str:
        """Render the conversation as self-contained HTML with full thread view.

        *content* may be a plain string (conversation turn text) or a
        :class:`ShapeResult` with structured directions.
        """
        import html as _html  # noqa: PLC0415

        from models import ShapeResult as _SR  # noqa: PLC0415

        safe_title = _html.escape(issue.title)

        # If content is a ShapeResult, render structured directions
        if isinstance(content, _SR):
            return ShapePhase._render_shape_result_html(issue, content, safe_title)

        # Build conversation thread (all turns, not just latest)
        thread_html = ""
        if conversation_turns:
            parts = []
            for i, turn in enumerate(conversation_turns):
                role_class = "agent" if turn.role == "agent" else "human"
                role_label = "Design Agent" if turn.role == "agent" else "Product Owner"
                safe_content = _html.escape(turn.content)
                parts.append(
                    f'<div class="turn {role_class}">'
                    f'<div class="turn-header">{role_label} · Turn {i + 1}</div>'
                    f'<div class="turn-content">{safe_content}</div></div>'
                )
            thread_html = "\n".join(parts)
        else:
            thread_html = f'<div class="turn agent"><div class="turn-content">{_html.escape(content)}</div></div>'

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shape #{issue.id} — Turn {turn_num}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:#0d1117; color:#c9d1d9; padding:24px; line-height:1.6; }}
  h1 {{ font-size:18px; margin-bottom:4px; }}
  .subtitle {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .turn {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
           padding:16px; margin-bottom:8px; font-size:14px; white-space:pre-wrap; }}
  .turn.human {{ border-left:3px solid #58a6ff; }}
  .turn.agent {{ border-left:3px solid #56d4dd; }}
  .turn-header {{ font-size:11px; color:#8b949e; margin-bottom:8px; font-weight:600;
                  text-transform:uppercase; letter-spacing:0.5px; }}
  .footer {{ margin-top:16px; color:#8b949e; font-size:12px; font-style:italic; }}
</style></head><body>
<h1>Shape Conversation — #{issue.id}</h1>
<p class="subtitle">{safe_title} · Turn {turn_num}</p>
{thread_html}
<p class="footer">Reply on GitHub, the dashboard, or WhatsApp to continue.</p>
</body></html>"""

    @staticmethod
    def _render_shape_result_html(
        issue: Task,
        result: ShapeResult,
        safe_title: str,
    ) -> str:
        """Render a ShapeResult as structured HTML with direction cards."""
        import html as _html  # noqa: PLC0415

        effort_colors = {
            "low": "#3fb950",
            "medium": "#d29922",
            "high": "#f85149",
            "unknown": "#8b949e",
        }
        risk_colors = {
            "low": "#3fb950",
            "medium": "#d29922",
            "high": "#f85149",
            "unknown": "#8b949e",
        }

        cards = []
        for d in result.directions:
            eff_color = effort_colors.get(d.effort, "#8b949e")
            risk_color = risk_colors.get(d.risk, "#8b949e")
            diff_html = ""
            if d.differentiator:
                diff_html = f"<p><strong>Differentiator:</strong> {_html.escape(d.differentiator)}</p>"
            cards.append(
                f'<div class="direction">'
                f"<h3>{_html.escape(d.name)}</h3>"
                f"<p>{_html.escape(d.approach)}</p>"
                f"<p><em>Tradeoffs:</em> {_html.escape(d.tradeoffs)}</p>"
                f'<span class="badge" style="background:{eff_color}">effort: {_html.escape(d.effort)}</span> '
                f'<span class="badge" style="background:{risk_color}">risk: {_html.escape(d.risk)}</span>'
                f"{diff_html}"
                f"</div>"
            )

        directions_html = "\n".join(cards)
        rec_html = ""
        if result.recommendation:
            rec_html = f'<div class="recommendation"><strong>Recommendation:</strong> {_html.escape(result.recommendation)}</div>'

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shape #{issue.id} — Directions</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:#0d1117; color:#c9d1d9; padding:24px; line-height:1.6; }}
  h1 {{ font-size:18px; margin-bottom:4px; }}
  .subtitle {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .direction {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
                padding:16px; margin-bottom:12px; }}
  .direction h3 {{ font-size:16px; margin-bottom:8px; color:#58a6ff; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px;
            color:#fff; margin-right:4px; }}
  .recommendation {{ background:#161b22; border:1px solid #3fb950; border-radius:8px;
                     padding:16px; margin-top:16px; }}
  .footer {{ margin-top:16px; color:#8b949e; font-size:12px; font-style:italic; }}
</style></head><body>
<h1>Shape Directions — #{issue.id}</h1>
<p class="subtitle">{safe_title}</p>
{directions_html}
{rec_html}
<p class="footer">Reply on GitHub, the dashboard, or WhatsApp to continue.</p>
</body></html>"""
