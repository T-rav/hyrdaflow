"""Unit tests for FakeBeads — verifies it faithfully mirrors BeadsManager's API."""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_beads import FakeBeads

_CWD = Path("/tmp/fake-beads-test")


# ---------------------------------------------------------------------------
# ensure_installed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ensure_installed_returns_none() -> None:
    beads = FakeBeads()
    result = await beads.ensure_installed()
    assert result is None


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_is_idempotent() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    await beads.init(cwd=_CWD)  # calling twice must not raise
    assert beads._initialized is True


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_returns_unique_ids() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    id1 = await beads.create_task(title="alpha", priority="0", cwd=_CWD)
    id2 = await beads.create_task(title="beta", priority="1", cwd=_CWD)
    assert id1 != id2


@pytest.mark.asyncio()
async def test_create_task_stores_title_and_priority() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    bead_id = await beads.create_task(title="my task", priority="1", cwd=_CWD)
    task = await beads.show(bead_id, cwd=_CWD)
    assert task.title == "my task"
    assert task.priority == 1


# ---------------------------------------------------------------------------
# add_dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_records_edge() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    parent = await beads.create_task(title="parent", priority="0", cwd=_CWD)
    child = await beads.create_task(title="child", priority="1", cwd=_CWD)
    await beads.add_dependency(child, parent, cwd=_CWD)
    shown = await beads.show(child, cwd=_CWD)
    assert parent in shown.depends_on


@pytest.mark.asyncio()
async def test_add_dependency_unknown_child_raises() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    parent = await beads.create_task(title="p", priority="0", cwd=_CWD)
    with pytest.raises(KeyError):
        await beads.add_dependency("bd-fake-999", parent, cwd=_CWD)


@pytest.mark.asyncio()
async def test_add_dependency_unknown_parent_raises() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    child = await beads.create_task(title="c", priority="1", cwd=_CWD)
    with pytest.raises(KeyError):
        await beads.add_dependency(child, "bd-fake-999", cwd=_CWD)


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_sets_status_in_progress() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    bead_id = await beads.create_task(title="claimable", priority="0", cwd=_CWD)
    await beads.claim(bead_id, cwd=_CWD)
    task = await beads.show(bead_id, cwd=_CWD)
    assert task.status == "in_progress"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_close_sets_status_closed() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    bead_id = await beads.create_task(title="closeable", priority="0", cwd=_CWD)
    await beads.close(bead_id, reason="done", cwd=_CWD)
    task = await beads.show(bead_id, cwd=_CWD)
    assert task.status == "closed"


# ---------------------------------------------------------------------------
# list_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_ready_excludes_tasks_with_open_deps() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    parent = await beads.create_task(title="parent", priority="0", cwd=_CWD)
    child = await beads.create_task(title="child", priority="1", cwd=_CWD)
    await beads.add_dependency(child, parent, cwd=_CWD)

    ready = await beads.list_ready(cwd=_CWD)
    ready_ids = [t.id for t in ready]
    assert parent in ready_ids
    assert child not in ready_ids


@pytest.mark.asyncio()
async def test_list_ready_includes_task_once_dep_closed() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    parent = await beads.create_task(title="parent", priority="0", cwd=_CWD)
    child = await beads.create_task(title="child", priority="1", cwd=_CWD)
    await beads.add_dependency(child, parent, cwd=_CWD)

    await beads.close(parent, reason="done", cwd=_CWD)
    ready = await beads.list_ready(cwd=_CWD)
    ready_ids = [t.id for t in ready]
    assert child in ready_ids


@pytest.mark.asyncio()
async def test_list_ready_excludes_closed_tasks() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    bead_id = await beads.create_task(title="t", priority="0", cwd=_CWD)
    await beads.close(bead_id, reason="done", cwd=_CWD)

    ready = await beads.list_ready(cwd=_CWD)
    assert not any(t.id == bead_id for t in ready)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_show_returns_bead_task_shape() -> None:
    beads = FakeBeads()
    await beads.init(cwd=_CWD)
    bead_id = await beads.create_task(title="show me", priority="0", cwd=_CWD)
    task = await beads.show(bead_id, cwd=_CWD)
    assert task.id == bead_id
    assert task.title == "show me"
    assert task.priority == 0
    assert task.status == "open"
    assert task.depends_on == []
