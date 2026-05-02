"""Tests for the shape conversation mode — multi-turn design conversations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from models import ConversationTurn, ShapeConversation, ShapeTurnResult, Task
from shape_phase import _CANCEL_RE, _FINALIZE_RE, ShapePhase


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig(
        repo="test/repo", max_shape_turns=5, shape_timeout_minutes=30
    )


@pytest.fixture
def deps(config: HydraFlowConfig) -> dict:
    import asyncio

    return {
        "config": config,
        "state": MagicMock(),
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
        "shape_runner": AsyncMock(),
    }


@pytest.fixture
def phase(deps: dict) -> ShapePhase:
    return ShapePhase(**deps)


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id=42,
        title="Build a better Calendly",
        body="Scheduling tool",
        labels=["hydraflow-shape"],
    )


class TestConversationStateModel:
    def test_conversation_turn_creation(self) -> None:
        turn = ConversationTurn(
            role="agent",
            content="Here are 3 directions",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert turn.role == "agent"
        assert turn.signal == ""

    def test_shape_conversation_defaults(self) -> None:
        conv = ShapeConversation(issue_number=42)
        assert conv.status == "exploring"
        assert conv.turns == []

    def test_shape_conversation_with_turns(self) -> None:
        conv = ShapeConversation(
            issue_number=42,
            turns=[
                ConversationTurn(
                    role="agent", content="Options A, B, C", timestamp="t1"
                ),
                ConversationTurn(
                    role="human",
                    content="Go deeper on B",
                    timestamp="t2",
                    signal="positive",
                    source="github",
                ),
            ],
        )
        assert len(conv.turns) == 2
        assert conv.turns[1].signal == "positive"
        assert conv.turns[1].source == "github"


class TestFinalizeDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "go with direction B",
            "ship it",
            "let's do it",
            "approved",
            "lgtm",
            "looks good to me",
            "Direction A please",
            "proceed with this",
            "build it",
        ],
    )
    def test_finalize_signals_detected(self, text: str) -> None:
        assert _FINALIZE_RE.search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "tell me more about B",
            "what about mobile?",
            "can you explore privacy angle?",
            "how complex is this?",
        ],
    )
    def test_non_finalize_not_detected(self, text: str) -> None:
        assert not _FINALIZE_RE.search(text)


class TestCancelDetection:
    def test_cancel_detected(self) -> None:
        assert _CANCEL_RE.search("cancel this")
        assert _CANCEL_RE.search("nevermind")
        assert _CANCEL_RE.search("close this issue")

    def test_normal_text_not_cancelled(self) -> None:
        assert not _CANCEL_RE.search("go deeper on B")


class TestSignalClassification:
    def test_scope_narrow(self, phase: ShapePhase) -> None:
        assert phase._classify_signal("just the calendar widget") == "scope_narrow"
        assert phase._classify_signal("start with MVP") == "scope_narrow"
        assert phase._classify_signal("only the core feature") == "scope_narrow"

    def test_scope_expand(self, phase: ShapePhase) -> None:
        assert phase._classify_signal("also add notifications") == "scope_expand"
        assert phase._classify_signal("what about mobile?") == "scope_expand"

    def test_positive(self, phase: ShapePhase) -> None:
        assert phase._classify_signal("I love direction B") == "positive"
        assert phase._classify_signal("yes, exactly") == "positive"

    def test_negative(self, phase: ShapePhase) -> None:
        assert phase._classify_signal("no, not that approach") == "negative"
        assert phase._classify_signal("skip direction A") == "negative"

    def test_neutral(self, phase: ShapePhase) -> None:
        assert phase._classify_signal("tell me more") == "neutral"


class TestFindHumanReply:
    def test_finds_reply_after_agent_turn(self, phase: ShapePhase) -> None:
        comments = [
            "**Shape Turn 1** — Product Design Conversation\n\nHere are options...",
            "Go deeper on B please",
        ]
        assert phase._find_human_reply(comments) == "Go deeper on B please"

    def test_returns_none_when_no_reply(self, phase: ShapePhase) -> None:
        comments = [
            "**Shape Turn 1** — Product Design Conversation\n\nHere are options...",
        ]
        assert phase._find_human_reply(comments) is None

    def test_returns_none_when_no_agent_turn(self, phase: ShapePhase) -> None:
        comments = ["some random comment"]
        assert phase._find_human_reply(comments) is None

    def test_ignores_agent_comments(self, phase: ShapePhase) -> None:
        comments = [
            "**Shape Turn 1** — Conversation\n\nOptions...",
            "**Shape Turn 2** — Conversation\n\nRefined...",
        ]
        assert phase._find_human_reply(comments) is None


class TestConversationLoop:
    @pytest.mark.asyncio
    async def test_first_turn_runs_agent(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """First turn with no existing conversation runs the agent."""
        deps["state"].get_shape_conversation.return_value = None
        deps["state"].get_shape_response.return_value = None
        deps["shape_runner"].run_turn = AsyncMock(
            return_value=ShapeTurnResult(
                content="Here are 3 directions...", is_final=False
            )
        )
        deps["store"].enrich_with_comments = AsyncMock(return_value=sample_task)
        phase._runner = deps["shape_runner"]

        result = await phase._shape_single(sample_task)

        assert result == 1
        deps["shape_runner"].run_turn.assert_awaited_once()
        deps["prs"].post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_waiting_for_response_re_enqueues(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When waiting for human response and none found, re-enqueue."""
        conv = ShapeConversation(
            issue_number=42,
            turns=[
                ConversationTurn(
                    role="agent",
                    content="Options...",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            ],
            last_activity_at=datetime.now(UTC).isoformat(),
        )
        deps["state"].get_shape_conversation.return_value = conv
        deps["state"].get_shape_response.return_value = None
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(
                update={"comments": ["**Shape Turn 1** — Options..."]}
            )
        )

        result = await phase._shape_single(sample_task)

        assert result == 0
        deps["store"].enqueue_transition.assert_called_with(sample_task, "shape")

    @pytest.mark.asyncio
    async def test_finalize_transitions_to_plan(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When agent produces final output, transition to plan."""
        deps["state"].get_shape_conversation.return_value = None
        deps["state"].get_shape_response.return_value = None
        deps["shape_runner"].run_turn = AsyncMock(
            return_value=ShapeTurnResult(content="Final spec here", is_final=True)
        )
        deps["store"].enrich_with_comments = AsyncMock(return_value=sample_task)
        phase._runner = deps["shape_runner"]

        result = await phase._shape_single(sample_task)

        assert result == 1
        deps["prs"].transition.assert_awaited_once_with(42, "plan")


class TestConversationTurnSource:
    @pytest.mark.asyncio
    async def test_state_response_sets_source_to_whatsapp(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When response comes from state (WhatsApp webhook), source='whatsapp'."""
        conv = ShapeConversation(
            issue_number=42,
            turns=[
                ConversationTurn(
                    role="agent",
                    content="Options...",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            ],
            last_activity_at=datetime.now(UTC).isoformat(),
        )
        deps["state"].get_shape_conversation.return_value = conv
        deps["state"].get_shape_response.return_value = "Go with B"
        deps["store"].enrich_with_comments = AsyncMock(return_value=sample_task)
        deps["shape_runner"].run_turn = AsyncMock(
            return_value=ShapeTurnResult(content="Exploring B...", is_final=False)
        )
        phase._runner = deps["shape_runner"]

        await phase._shape_single(sample_task)

        human_turns = [t for t in conv.turns if t.role == "human"]
        assert len(human_turns) == 1
        assert human_turns[0].source == "whatsapp"

    @pytest.mark.asyncio
    async def test_github_comment_sets_source_to_github(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When response comes from GitHub comments, source='github'."""
        conv = ShapeConversation(
            issue_number=42,
            turns=[
                ConversationTurn(
                    role="agent",
                    content="Options...",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            ],
            last_activity_at=datetime.now(UTC).isoformat(),
        )
        deps["state"].get_shape_conversation.return_value = conv
        deps["state"].get_shape_response.return_value = None
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(
                update={
                    "comments": [
                        "**Shape Turn 1** — Options...",
                        "Go deeper on B",
                    ]
                }
            )
        )
        deps["shape_runner"].run_turn = AsyncMock(
            return_value=ShapeTurnResult(content="Exploring B...", is_final=False)
        )
        phase._runner = deps["shape_runner"]

        await phase._shape_single(sample_task)

        human_turns = [t for t in conv.turns if t.role == "human"]
        assert len(human_turns) == 1
        assert human_turns[0].source == "github"

    def test_source_defaults_to_empty_string(self) -> None:
        """Source field defaults to empty string when not provided."""
        turn = ConversationTurn(role="agent", content="Hello")
        assert turn.source == ""

    @pytest.mark.asyncio
    async def test_no_response_appends_no_human_turn(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When neither path returns a response, no human turn is appended."""
        conv = ShapeConversation(
            issue_number=42,
            turns=[
                ConversationTurn(
                    role="agent",
                    content="Options...",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            ],
            last_activity_at=datetime.now(UTC).isoformat(),
        )
        deps["state"].get_shape_conversation.return_value = conv
        deps["state"].get_shape_response.return_value = None
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(
                update={"comments": ["**Shape Turn 1** — Options..."]}
            )
        )

        await phase._shape_single(sample_task)

        human_turns = [t for t in conv.turns if t.role == "human"]
        assert len(human_turns) == 0


class TestWhatsAppBridge:
    def test_parse_webhook_extracts_text_and_issue(self) -> None:
        from whatsapp_bridge import WhatsAppBridge

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"text": {"body": "Go with #42 Direction B"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        text, issue = WhatsAppBridge.parse_webhook(payload)
        assert text == "Go with #42 Direction B"
        assert issue == 42

    def test_parse_webhook_no_issue_number(self) -> None:
        from whatsapp_bridge import WhatsAppBridge

        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [{"text": {"body": "Ship it"}}]}}]}
            ]
        }
        text, issue = WhatsAppBridge.parse_webhook(payload)
        assert text == "Ship it"
        assert issue is None

    def test_parse_webhook_empty_payload(self) -> None:
        from whatsapp_bridge import WhatsAppBridge

        text, issue = WhatsAppBridge.parse_webhook({})
        assert text == ""
        assert issue is None

    def test_format_condensed_summary(self) -> None:
        from whatsapp_bridge import WhatsAppBridge

        content = "## Direction A: Privacy-First\n\n**Approach:** Self-hosted scheduling\n\nThis is a long description that goes on and on."
        result = WhatsAppBridge.format_condensed_summary(content, max_length=50)
        assert len(result) <= 53  # 50 + "..."
        assert "##" not in result
        assert "**" not in result
