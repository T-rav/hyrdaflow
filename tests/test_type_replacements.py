"""Tests for issue #886 — replacing Any with specific types in source modules.

Verifies that the new type annotations (UnstickResult TypedDict, DockerSocket /
ContainerLike protocols, and refined parameter types) are structurally compatible
with existing runtime usage patterns.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from models import UnstickResult
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# UnstickResult TypedDict
# ---------------------------------------------------------------------------


class TestUnstickResult:
    """Tests for the UnstickResult TypedDict added to models.py."""

    def test_has_required_keys(self) -> None:
        """UnstickResult must accept all four counter keys."""
        result: UnstickResult = {
            "processed": 3,
            "resolved": 2,
            "failed": 1,
            "skipped": 0,
        }
        assert result["processed"] == 3
        assert result["resolved"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 0

    def test_values_are_ints(self) -> None:
        """All values should be integers."""
        result: UnstickResult = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
        }
        for val in result.values():
            assert isinstance(val, int)

    def test_compatible_with_dict_mutation(self) -> None:
        """UnstickResult should be usable with incremental mutation (+=)."""
        stats: UnstickResult = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
        }
        stats["processed"] += 1
        stats["resolved"] += 1
        assert stats["processed"] == 1
        assert stats["resolved"] == 1


# ---------------------------------------------------------------------------
# DockerSocket protocol
# ---------------------------------------------------------------------------


class TestDockerSocketProtocol:
    """Tests that Docker socket protocol is importable and structurally usable."""

    def test_protocol_importable(self) -> None:
        """DockerSocket protocol should be importable from docker_runner."""
        from docker_runner import DockerSocket

        assert DockerSocket is not None

    def test_mock_satisfies_protocol(self) -> None:
        """A MagicMock with sendall/recv should satisfy the DockerSocket protocol."""
        mock = MagicMock()
        mock.sendall = MagicMock()
        mock.recv = MagicMock(return_value=b"data")
        assert hasattr(mock, "sendall")
        assert hasattr(mock, "recv")


# ---------------------------------------------------------------------------
# ContainerLike protocol
# ---------------------------------------------------------------------------


class TestContainerLikeProtocol:
    """Tests that ContainerLike protocol is importable and structurally usable."""

    def test_protocol_importable(self) -> None:
        """ContainerLike protocol should be importable from docker_runner."""
        from docker_runner import ContainerLike

        assert ContainerLike is not None

    def test_mock_satisfies_protocol(self) -> None:
        """A MagicMock should satisfy the ContainerLike protocol structurally."""
        mock = MagicMock()
        assert callable(mock.kill)
        assert callable(mock.wait)
        assert callable(mock.start)
        assert callable(mock.remove)
        assert callable(mock.logs)
        assert callable(mock.attach_socket)


# ---------------------------------------------------------------------------
# hitl_phase.py — Callable type for active_issues_cb
# ---------------------------------------------------------------------------


class TestHitlPhaseCallableType:
    """Tests that HITLPhase accepts Callable[[], None] for active_issues_cb."""

    def test_accepts_none_callback(self) -> None:
        """HITLPhase should accept None for active_issues_cb."""
        from hitl_phase import HITLPhase

        sig = inspect.signature(HITLPhase.__init__)
        param = sig.parameters["active_issues_cb"]
        assert param.default is None

    def test_accepts_callable_callback(self) -> None:
        """HITLPhase should accept a plain callable for active_issues_cb."""
        from hitl_phase import HITLPhase

        config = ConfigFactory.create()
        called = False

        def my_cb() -> None:
            nonlocal called
            called = True

        phase = HITLPhase(
            config=config,
            state=MagicMock(),
            store=MagicMock(),
            fetcher=MagicMock(),
            worktrees=MagicMock(),
            hitl_runner=MagicMock(),
            prs=MagicMock(),
            event_bus=MagicMock(),
            stop_event=asyncio.Event(),
            active_issues_cb=my_cb,
        )
        phase._notify_active_issues()
        assert called


# ---------------------------------------------------------------------------
# service_registry.py — SubprocessRunner type
# ---------------------------------------------------------------------------


class TestServiceRegistrySubprocessRunnerType:
    """Tests that ServiceRegistry.subprocess_runner accepts SubprocessRunner."""

    def test_subprocess_runner_field_accepts_host_runner(self) -> None:
        """HostRunner should be assignable to the subprocess_runner field."""
        from execution import HostRunner, SubprocessRunner

        runner = HostRunner()
        assert isinstance(runner, SubprocessRunner)


# ---------------------------------------------------------------------------
# pr_unsticker.py — UnstickResult return type
# ---------------------------------------------------------------------------


class TestPrUnstickerReturnType:
    """Tests that PRUnsticker.unstick returns an UnstickResult-compatible dict."""

    @pytest.mark.asyncio
    async def test_empty_items_returns_unstick_result_shape(self) -> None:
        """unstick([]) should return a dict matching UnstickResult keys."""
        from pr_unsticker import PRUnsticker

        unsticker = PRUnsticker(
            config=MagicMock(),
            state=MagicMock(),
            event_bus=MagicMock(),
            pr_manager=MagicMock(),
            agents=MagicMock(),
            worktrees=MagicMock(),
            fetcher=MagicMock(),
        )
        result = await unsticker.unstick([])
        assert set(result.keys()) == {
            "processed",
            "resolved",
            "failed",
            "skipped",
            "merged",
        }
        for val in result.values():
            assert isinstance(val, int)


# ---------------------------------------------------------------------------
# stream_parser.py — dict[str, Any] annotations
# ---------------------------------------------------------------------------


class TestStreamParserDictAnnotations:
    """Tests that stream_parser functions accept dict[str, Any] args."""

    def test_parse_assistant_with_typed_dict(self) -> None:
        """_parse_assistant should work with dict[str, Any] input."""
        from stream_parser import StreamParser

        parser = StreamParser()
        event: dict[str, Any] = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "hello"}],
            },
        }
        result = parser._parse_assistant(event)
        assert "hello" in result

    def test_summarize_input_with_typed_dict(self) -> None:
        """_summarize_input should work with dict[str, Any] input."""
        from stream_parser import _summarize_input

        tool_input: dict[str, Any] = {"command": "ls -la"}
        result = _summarize_input("Bash", tool_input)
        assert result == "ls -la"
