"""HTTPPort — generic httpx-compatible surface for scenario tests."""

from __future__ import annotations

from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class HTTPResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...
    def raise_for_status(self) -> None: ...


@runtime_checkable
class HTTPPort(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        timeout: float | None = None,
    ) -> HTTPResponse: ...
