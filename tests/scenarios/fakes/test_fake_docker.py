"""FakeDocker — scripted agent-cli event stream."""

from __future__ import annotations

from tests.scenarios.fakes.fake_docker import FakeDocker
from tests.scenarios.ports import DockerPort


def test_fake_docker_satisfies_port() -> None:
    assert isinstance(FakeDocker(), DockerPort)


async def test_scripted_event_stream_is_replayed_in_order() -> None:
    fake = FakeDocker()
    fake.script_run(
        [
            {"type": "tool_use", "name": "read_file", "input": {"path": "x.py"}},
            {"type": "message", "text": "Reading x.py"},
            {"type": "result", "success": True, "exit_code": 0},
        ]
    )

    events = []
    async for ev in await fake.run_agent(command=["agent"]):
        events.append(ev)

    assert [e["type"] for e in events] == ["tool_use", "message", "result"]


async def test_multiple_scripted_runs_pop_in_order() -> None:
    fake = FakeDocker()
    fake.script_run([{"type": "result", "success": True, "exit_code": 0}])
    fake.script_run([{"type": "result", "success": False, "exit_code": 1}])

    first = [e async for e in await fake.run_agent(command=["a"])]
    second = [e async for e in await fake.run_agent(command=["b"])]

    assert first[0]["success"] is True
    assert second[0]["success"] is False


async def test_default_run_emits_success_result() -> None:
    fake = FakeDocker()
    events = [e async for e in await fake.run_agent(command=["agent"])]
    assert events[-1] == {"type": "result", "success": True, "exit_code": 0}


async def test_run_agent_records_invocations() -> None:
    fake = FakeDocker()
    async for _ in await fake.run_agent(
        command=["agent", "--task", "42"],
        env={"FOO": "BAR"},
    ):
        pass
    assert len(fake.invocations) == 1
    assert fake.invocations[0].command == ["agent", "--task", "42"]
    assert fake.invocations[0].env == {"FOO": "BAR"}
