from __future__ import annotations

from task_source import TaskFetcher, TaskSource, TaskTransitioner


class _FetcherImpl:
    async def fetch_all(self):
        return []


class _SourceImpl:
    def get_triageable(self, n: int):
        return []

    def get_plannable(self, n: int):
        return []

    def get_implementable(self, n: int):
        return []

    def get_reviewable(self, n: int):
        return []

    def mark_active(self, task_id: int, stage: str) -> None:
        return None

    def mark_complete(self, task_id: int) -> None:
        return None

    def is_active(self, task_id: int) -> bool:
        return False


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
    assert isinstance(_SourceImpl(), TaskSource)
    assert isinstance(_TransitionerImpl(), TaskTransitioner)


def test_task_source_protocol_rejects_missing_required_method() -> None:
    class _IncompleteSource:
        def get_triageable(self, n: int):
            return []

        def get_plannable(self, n: int):
            return []

        def get_implementable(self, n: int):
            return []

        def get_reviewable(self, n: int):
            return []

        def mark_active(self, task_id: int, stage: str) -> None:
            return None

        def mark_complete(self, task_id: int) -> None:
            return None

    assert not isinstance(_IncompleteSource(), TaskSource)
