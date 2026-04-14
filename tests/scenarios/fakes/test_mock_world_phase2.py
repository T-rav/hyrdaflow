"""MockWorld composes phase-2 fakes alongside the originals."""

from __future__ import annotations

from pathlib import Path

from tests.scenarios.fakes.mock_world import MockWorld


async def test_world_exposes_phase2_fakes(tmp_path: Path) -> None:
    world = MockWorld(tmp_path)
    assert world.docker is not None
    assert world.git is not None
    assert world.fs is not None
    assert world.http is not None


async def test_fake_docker_invocations_accessible(tmp_path: Path) -> None:
    world = MockWorld(tmp_path)
    async for _ in await world.docker.run_agent(command=["agent"]):
        pass
    assert len(world.docker.invocations) == 1
