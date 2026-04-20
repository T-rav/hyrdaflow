"""Smoke test: boot the dashboard via MockWorld and hit GET /."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.scenario_browser
async def test_dashboard_boots_and_serves_root(world):
    url = await world.start_dashboard()

    async with httpx.AsyncClient() as client:
        response = await client.get(url + "/")

    assert response.status_code == 200


@pytest.mark.scenario_browser
async def test_dashboard_with_orchestrator_serves_root(world):
    url = await world.start_dashboard(with_orchestrator=True)

    async with httpx.AsyncClient() as client:
        response = await client.get(url + "/")

    assert response.status_code == 200
