from __future__ import annotations

from task_source import TaskFetcher, TaskTransitioner


class _FetcherImpl:
    async def fetch_all(self):
        return []


class _TransitionerImpl:
    async def transition(
        self, task_id: int, new_stage: str, *, pr_number: int | None = None
    ) -> None:
        return None

    async def post_comment(self, task_id: int, body: str) -> None:
        return None

    async def close_task(self, task_id: int) -> None:
        return None

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        return 1


def test_task_source_protocols_are_runtime_checkable() -> None:
    assert isinstance(_FetcherImpl(), TaskFetcher)
    assert isinstance(_TransitionerImpl(), TaskTransitioner)
