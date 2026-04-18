"""FakeDocker — scripted agent-cli event stream."""

from __future__ import annotations

import pytest

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


async def test_fail_next_timeout_raises_on_consumption() -> None:
    fake = FakeDocker()
    fake.fail_next(kind="timeout")
    with pytest.raises(TimeoutError):
        async for _ in await fake.run_agent(command=["agent"]):
            pass


async def test_fail_next_oom_emits_exit_137() -> None:
    fake = FakeDocker()
    fake.fail_next(kind="oom")
    events = [e async for e in await fake.run_agent(command=["agent"])]
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is False
    assert events[-1]["exit_code"] == 137


async def test_fail_next_exit_nonzero_emits_exit_1() -> None:
    fake = FakeDocker()
    fake.fail_next(kind="exit_nonzero")
    events = [e async for e in await fake.run_agent(command=["agent"])]
    assert events[-1] == {"type": "result", "success": False, "exit_code": 1}


async def test_fail_next_malformed_stream_emits_garbage_then_result() -> None:
    fake = FakeDocker()
    fake.fail_next(kind="malformed_stream")
    events = [e async for e in await fake.run_agent(command=["agent"])]
    assert events[0]["type"] == "garbage"
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is False


async def test_fail_next_is_single_shot() -> None:
    fake = FakeDocker()
    fake.fail_next(kind="exit_nonzero")
    first = [e async for e in await fake.run_agent(command=["a"])]
    second = [e async for e in await fake.run_agent(command=["b"])]
    assert first[-1]["success"] is False
    assert second[-1]["success"] is True


async def test_script_run_with_commits_writes_files_and_commits(tmp_path) -> None:
    import subprocess

    # Init a real git repo in tmp_path
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    fake = FakeDocker()
    fake.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("file.txt", "hello")],
        cwd=tmp_path,
    )

    events = [e async for e in await fake.run_agent(command=["agent"])]
    assert events[-1]["type"] == "result"
    assert (tmp_path / "file.txt").read_text() == "hello"

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "fake-commit" in log.stdout
