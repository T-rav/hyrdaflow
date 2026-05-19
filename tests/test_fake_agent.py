"""Tests for FakeAgent — AgentPort conformance + behavioural assertions.

Covers:
- Protocol conformance (isinstance against AgentPort)
- Signature parity against the real AgentRunner
- Default behaviours (no scripting)
- Scripted execute / verify_result sequences (sticky-tail semantics)
- Observation lists (execute_calls, verify_calls)
- build_command override
- on_output callback forwarding
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mockworld.fakes.fake_agent import FakeAgent
from models import LoopResult
from ports import AgentPort

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestFakeAgentConformance:
    """FakeAgent must satisfy AgentPort via isinstance."""

    def test_isinstance_agent_port(self) -> None:
        assert isinstance(FakeAgent(), AgentPort), (
            "FakeAgent does not satisfy AgentPort. "
            "Ensure all three methods (build_command, execute, verify_result) "
            "are present with the correct signatures."
        )

    def test_is_fake_adapter_marker(self) -> None:
        assert FakeAgent._is_fake_adapter is True


# ---------------------------------------------------------------------------
# Signature parity — FakeAgent must match AgentPort exactly
# ---------------------------------------------------------------------------


def _named_params(cls: type, method: str) -> dict[str, inspect.Parameter]:
    sig = inspect.signature(getattr(cls, method))
    return {
        k: v
        for k, v in sig.parameters.items()
        if k != "self"
        and v.kind
        not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    }


class TestFakeAgentSignatures:
    """FakeAgent method signatures must be compatible with AgentPort's."""

    @pytest.mark.parametrize("method", ["build_command", "execute", "verify_result"])
    def test_port_params_present_on_fake(self, method: str) -> None:
        port_params = _named_params(AgentPort, method)
        fake_params = _named_params(FakeAgent, method)
        # All named port params must appear on the fake (no **kwargs absorb here)
        missing = set(port_params) - set(fake_params)
        assert not missing, (
            f"FakeAgent.{method} is missing params declared on AgentPort: {sorted(missing)}"
        )

    @pytest.mark.parametrize("method", ["build_command", "execute", "verify_result"])
    def test_required_vs_optional_matches(self, method: str) -> None:
        port_params = _named_params(AgentPort, method)
        fake_params = _named_params(FakeAgent, method)
        for name in set(port_params) & set(fake_params):
            port_req = port_params[name].default is inspect.Parameter.empty
            fake_req = fake_params[name].default is inspect.Parameter.empty
            assert port_req == fake_req, (
                f"FakeAgent.{method} param '{name}': "
                f"Port required={port_req}, Fake required={fake_req}"
            )


# ---------------------------------------------------------------------------
# Default behaviour (no scripting)
# ---------------------------------------------------------------------------


class TestFakeAgentDefaults:
    def test_build_command_default(self) -> None:
        agent = FakeAgent()
        cmd = agent.build_command()
        assert cmd == ["fake-agent"]

    def test_build_command_with_path(self) -> None:
        agent = FakeAgent()
        cmd = agent.build_command(Path("/tmp/wt"))
        assert cmd == ["fake-agent"]

    @pytest.mark.asyncio
    async def test_execute_returns_default_transcript(self) -> None:
        agent = FakeAgent()
        transcript = await agent.execute(
            cmd=["fake-agent"],
            prompt="do the thing",
            cwd=Path("/tmp/wt"),
            event_data={"issue": 1},
        )
        assert isinstance(transcript, str)
        assert len(transcript) > 0

    @pytest.mark.asyncio
    async def test_verify_result_default_passes(self) -> None:
        agent = FakeAgent()
        result = await agent.verify_result(Path("/tmp/wt"), "feat/my-branch")
        assert isinstance(result, LoopResult)
        assert result.passed is True

    def test_execute_calls_empty_initially(self) -> None:
        assert FakeAgent().execute_calls == []

    def test_verify_calls_empty_initially(self) -> None:
        assert FakeAgent().verify_calls == []


# ---------------------------------------------------------------------------
# Scripted execute — queue + sticky-tail
# ---------------------------------------------------------------------------


class TestFakeAgentScriptedExecute:
    @pytest.mark.asyncio
    async def test_scripted_transcript_returned(self) -> None:
        agent = FakeAgent()
        agent.script_execute(["transcript A", "transcript B"])
        assert await agent.execute([], "p", Path("/"), {}) == "transcript A"
        assert await agent.execute([], "p", Path("/"), {}) == "transcript B"

    @pytest.mark.asyncio
    async def test_sticky_tail_after_queue_drains(self) -> None:
        agent = FakeAgent()
        agent.script_execute(["last transcript"])
        await agent.execute([], "p", Path("/"), {})  # pops "last transcript"
        # Queue is empty — sticky tail should repeat
        result = await agent.execute([], "p", Path("/"), {})
        assert result == "last transcript"

    @pytest.mark.asyncio
    async def test_execute_records_call(self) -> None:
        agent = FakeAgent()
        cmd = ["fake-agent", "--flag"]
        prompt = "implement #42"
        cwd = Path("/tmp/issue-42")
        event_data = {"issue": 42}
        await agent.execute(cmd, prompt, cwd, event_data)
        assert len(agent.execute_calls) == 1
        recorded_cmd, recorded_prompt, recorded_cwd, recorded_ed = agent.execute_calls[
            0
        ]
        assert recorded_cmd == cmd
        assert recorded_prompt == prompt
        assert recorded_cwd == cwd
        assert recorded_ed == event_data

    @pytest.mark.asyncio
    async def test_on_output_callback_invoked(self) -> None:
        agent = FakeAgent()
        agent.script_execute(["hello from fake"])
        received: list[str] = []
        await agent.execute(
            [], "", Path("/"), {}, on_output=lambda t: received.append(t) or False
        )
        assert received == ["hello from fake"]


# ---------------------------------------------------------------------------
# Scripted verify_result — queue + sticky-tail
# ---------------------------------------------------------------------------


class TestFakeAgentScriptedVerify:
    @pytest.mark.asyncio
    async def test_scripted_results_returned_in_order(self) -> None:
        agent = FakeAgent()
        agent.script_verify(
            [
                LoopResult(passed=False, summary="quality failed", attempts=1),
                LoopResult(passed=True, summary="OK", attempts=2),
            ]
        )
        r1 = await agent.verify_result(Path("/tmp/wt"), "feat/branch")
        assert r1.passed is False
        assert r1.summary == "quality failed"

        r2 = await agent.verify_result(Path("/tmp/wt"), "feat/branch")
        assert r2.passed is True

    @pytest.mark.asyncio
    async def test_sticky_tail_verify(self) -> None:
        agent = FakeAgent()
        scripted = LoopResult(passed=False, summary="persistent failure")
        agent.script_verify([scripted])
        await agent.verify_result(Path("/"), "b")
        second = await agent.verify_result(Path("/"), "b")
        assert second.passed is False
        assert second.summary == "persistent failure"

    @pytest.mark.asyncio
    async def test_verify_records_call(self) -> None:
        agent = FakeAgent()
        wt = Path("/tmp/wt-99")
        branch = "feat/fix-conflict-99"
        await agent.verify_result(wt, branch)
        assert agent.verify_calls == [(wt, branch)]


# ---------------------------------------------------------------------------
# build_command override
# ---------------------------------------------------------------------------


class TestFakeAgentBuildCommandOverride:
    def test_script_build_command(self) -> None:
        agent = FakeAgent()
        agent.script_build_command(["claude", "--profile", "prod"])
        assert agent.build_command() == ["claude", "--profile", "prod"]

    def test_build_command_does_not_mutate_internal_state(self) -> None:
        agent = FakeAgent()
        cmd = agent.build_command()
        cmd.append("--extra")
        assert agent.build_command() == ["fake-agent"]
