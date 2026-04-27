"""FakeHTTP — route-table response stubbing for scenario tests."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Response:
    status_code: int
    text: str = ""
    _json: Any = None

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"HTTP {self.status_code}"
            raise RuntimeError(msg)


@dataclass
class _RecordedRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json: Any = None
    data: Any = None


class _RouteBuilder:
    def __init__(self, owner: FakeHTTP, key: tuple[str, str]) -> None:
        self._owner = owner
        self._key = key

    def respond(
        self, *, status_code: int, json: Any = None, text: str = ""
    ) -> _RouteBuilder:
        self._owner._routes.setdefault(self._key, deque()).append(
            _Response(status_code=status_code, text=text, _json=json)
        )
        return self


class FakeHTTP:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], deque[_Response]] = {}
        self.requests: list[_RecordedRequest] = []

    def when(self, method: str, url: str) -> _RouteBuilder:
        return _RouteBuilder(self, (method.upper(), url))

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: Any = None,
        timeout: float | None = None,
    ) -> _Response:
        _ = timeout
        self.requests.append(
            _RecordedRequest(
                method=method.upper(),
                url=url,
                headers=dict(headers) if headers else {},
                json=json,
                data=data,
            )
        )
        key = (method.upper(), url)
        if key not in self._routes or not self._routes[key]:
            msg = f"no route for {method.upper()} {url}"
            raise LookupError(msg)
        queue = self._routes[key]
        # Pop if more than one; otherwise repeat last.
        if len(queue) > 1:
            return queue.popleft()
        return queue[0]
