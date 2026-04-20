"""Tests for the loop_port_seeding shared helper."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.scenario


async def test_seed_ports_initializes_dict_and_stores_values(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld
    from tests.scenarios.helpers.loop_port_seeding import seed_ports

    world = MockWorld(tmp_path)
    sentinel = object()
    seed_ports(world, my_port=sentinel)
    assert world._loop_ports["my_port"] is sentinel


async def test_seed_ports_overwrites_existing(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld
    from tests.scenarios.helpers.loop_port_seeding import seed_ports

    world = MockWorld(tmp_path)
    world._loop_ports = {"a": "old"}
    seed_ports(world, a="new")
    assert world._loop_ports["a"] == "new"
