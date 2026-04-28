"""SandboxAPIClient — async HTTP client targeting the in-container hydraflow.

Used by Playwright fixtures and by scenario assert_outcome implementations
to read API state without going through the UI.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from urllib.parse import urljoin

import httpx


class SandboxAPIClient:
    """Tiny async-friendly wrapper over the dashboard REST API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.environ.get(
            "SANDBOX_API_BASE", "http://hydraflow:5555"
        )

    async def get(self, path: str) -> dict:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            return resp.json()

    async def wait_until(
        self,
        path: str,
        predicate: Callable[[dict], bool],
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> dict:
        """Poll path until predicate(payload) returns True or timeout."""
        deadline = asyncio.get_running_loop().time() + timeout
        last = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                last = await self.get(path)
                if predicate(last):
                    return last
            except (httpx.HTTPError, ConnectionError, ValueError):
                pass
            await asyncio.sleep(poll_interval)
        raise TimeoutError(
            f"timeout waiting for predicate on {path}; last payload: {last!r}"
        )
