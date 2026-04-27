"""Contract tests: FakeDocker events must match docker-cli cassettes.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2. `FakeDocker.run_agent` is an async iterator — the harness materializes
the yielded events into a JSON-Lines-shaped stdout block so the cassette
schema (exit_code/stdout/stderr) still fits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mockworld.fakes.fake_docker import FakeDocker
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "docker"


async def _collect_events(iterator: Any) -> list[dict[str, Any]]:
    """Drain an async iterator of events returned by FakeDocker.run_agent."""
    events = []
    async for event in await iterator:
        events.append(event)
    return events


async def _invoke_fake_docker(cassette: Cassette) -> FakeOutput:
    """Dispatch the cassette input through FakeDocker's matching method."""
    fake = FakeDocker()
    method = cassette.input.command
    args = cassette.input.args

    if method == "run_agent":
        image = args[0]
        cmd = list(args[1:])
        # Script a success event for a fresh container run.
        fake.script_run([{"type": "result", "success": True, "exit_code": 0}])
        events = await _collect_events(fake.run_agent(command=[image, *cmd]))
        exit_code = events[-1]["exit_code"]
        stdout = "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n"
        return FakeOutput(exit_code=exit_code, stdout=stdout, stderr="")

    if method == "run_agent_with_fault":
        fault = args[0]
        fake.fail_next(kind=fault)  # type: ignore[arg-type]
        events = await _collect_events(fake.run_agent(command=["alpine:3.19"]))
        exit_code = events[-1]["exit_code"]
        stdout = "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n"
        return FakeOutput(exit_code=exit_code, stdout=stdout, stderr="")

    msg = f"FakeDocker has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_docker_matches_cassette(cassette_path: Path) -> None:
    """Replay a docker cassette; assert FakeDocker's events match."""
    await replay_cassette(cassette_path, _invoke_fake_docker)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
