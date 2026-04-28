"""FakeLLM streaming extension — captured agent-cli events per issue."""

from __future__ import annotations

from pathlib import Path

from mockworld.fakes.fake_llm import FakeLLM


async def test_script_stream_attaches_events_to_worker_result() -> None:
    llm = FakeLLM()
    llm.agents.script_stream(
        42,
        [
            {"type": "tool_use", "name": "edit"},
            {"type": "result", "success": True, "exit_code": 0},
        ],
    )

    class _Task:
        id = 42

    result = await llm.agents.run(_Task(), worktree_path=Path("/tmp/wt"), branch="b")

    assert result.issue_number == 42
    events = llm.agents.events_for(42)
    assert [e["type"] for e in events] == ["tool_use", "result"]


def test_events_for_missing_issue_returns_empty_list() -> None:
    llm = FakeLLM()
    assert llm.agents.events_for(999) == []
