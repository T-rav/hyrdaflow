"""Protocol interfaces for pluggable task sources."""

from __future__ import annotations

from typing import runtime_checkable

from typing_extensions import Protocol

from models import Task


@runtime_checkable
class TaskFetcher(Protocol):
    """Returns all tasks currently in the pipeline."""

    async def fetch_all(self) -> list[Task]: ...


@runtime_checkable
class TaskTransitioner(Protocol):
    """Write interface for moving tasks through pipeline stages."""

    async def transition(
        self, issue_number: int, new_stage: str, *, pr_number: int | None = None
    ) -> None: ...
    async def post_comment(self, issue_number: int, body: str) -> None: ...
    async def close_task(self, issue_number: int) -> None: ...
    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int: ...
