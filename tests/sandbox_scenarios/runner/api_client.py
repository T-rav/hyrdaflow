"""SandboxAPIClient — async HTTP client targeting the in-container hydraflow.

Used by Playwright fixtures and by scenario assert_outcome implementations
to read API state without going through the UI.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class SandboxAPIClient:
    """Tiny async-friendly wrapper over the dashboard REST API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.environ.get(
            "SANDBOX_API_BASE", "http://hydraflow:5555"
        )

    async def get(self, path: str) -> dict:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:  # noqa: S310 — sandbox-only internal URL
            return json.loads(resp.read().decode())

    async def wait_until(
        self,
        path: str,
        predicate,
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> dict:
        """Poll path until predicate(payload) returns True or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        last = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                last = await self.get(path)
                if predicate(last):
                    return last
            except Exception:  # noqa: BLE001 — best-effort polling
                pass
            await asyncio.sleep(poll_interval)
        raise TimeoutError(
            f"timeout waiting for predicate on {path}; last payload: {last!r}"
        )
