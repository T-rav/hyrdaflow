"""Contract tests: FakeWorkspace return-shape parity with WorkspacePort (ADR-0047).

Why no cassettes
----------------
The cassette/replay pattern (ADR-0047 §Part 1) targets CLI-based adapters
(github, git, docker) whose real-service output can be snapshot as YAML.
``FakeWorkspace`` wraps in-process Python objects — there is no CLI, no
subprocess, and no external service whose output drifts. Adding "workspace"
to ``KNOWN_ADAPTERS`` would be wrong (it is not in ``_FAKE_TO_CASSETTE_DIR``
in ``fake_coverage_auditor_loop.py`` for the same reason).

What this file asserts
-----------------------
1. ``FakeWorkspace`` satisfies the ``WorkspacePort`` Protocol at runtime
   (``isinstance`` check against the ``@runtime_checkable`` Protocol).
2. Every method declared on ``WorkspacePort`` is present on ``FakeWorkspace``
   with a matching async signature.
3. Return-type parity for every Port method:
   - ``create`` → ``Path``
   - ``destroy`` → ``None``
   - ``destroy_all`` → ``None``
   - ``merge_main`` → ``bool`` (True on the happy path)
   - ``get_conflicting_files`` → ``list[str]`` (empty on the happy path)
   - ``reset_to_main`` → ``None``
   - ``post_work_cleanup`` → ``None``
   - ``abort_merge`` → ``None``
   - ``start_merge_main`` → ``bool`` (True on the happy path)
4. Fault injection paths:  ``fail_next_create`` injects ``PermissionError``,
   ``OSError(28, …)`` (disk full), and ``RuntimeError`` (branch conflict).
5. Stateful tracking: ``created`` / ``destroyed`` lists accumulate correctly.

Approach: instantiate ``FakeWorkspace`` directly (no MockWorld), call each
Port method on thin inputs, and assert against the declared return type.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from mockworld.fakes.fake_workspace import FakeWorkspace
from ports import WorkspacePort

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fake(tmp_path: Path) -> FakeWorkspace:
    """Return a fresh FakeWorkspace rooted at *tmp_path*."""
    return FakeWorkspace(base_path=tmp_path)


# ---------------------------------------------------------------------------
# Test 1: Protocol satisfaction
# ---------------------------------------------------------------------------


def test_fake_workspace_satisfies_protocol(tmp_path: Path) -> None:
    """FakeWorkspace must satisfy WorkspacePort at runtime (runtime_checkable)."""
    fake = _make_fake(tmp_path)
    assert isinstance(fake, WorkspacePort), (
        "FakeWorkspace does not satisfy the WorkspacePort Protocol; "
        "a method is missing or has the wrong signature."
    )


# ---------------------------------------------------------------------------
# Test 2: every Port method is async
# ---------------------------------------------------------------------------


_PORT_METHODS = [
    "create",
    "destroy",
    "destroy_all",
    "merge_main",
    "get_conflicting_files",
    "reset_to_main",
    "post_work_cleanup",
    "abort_merge",
    "start_merge_main",
]


@pytest.mark.parametrize("method_name", _PORT_METHODS)
def test_fake_workspace_method_is_async(
    tmp_path: Path, method_name: str
) -> None:
    """Every WorkspacePort method on FakeWorkspace must be a coroutine function."""
    fake = _make_fake(tmp_path)
    method = getattr(fake, method_name, None)
    assert method is not None, (
        f"FakeWorkspace is missing Port method {method_name!r}"
    )
    assert inspect.iscoroutinefunction(method), (
        f"FakeWorkspace.{method_name} must be async (coroutine function)"
    )


# ---------------------------------------------------------------------------
# Test 3a: create — returns Path, creates directory, tracks issue_number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_path_and_creates_dir(tmp_path: Path) -> None:
    """create() returns a Path and creates the workspace directory."""
    fake = _make_fake(tmp_path)
    result = await fake.create(issue_number=42, branch="agent/issue-42")

    assert isinstance(result, Path), (
        f"WorkspacePort.create must return Path; got {type(result).__name__}"
    )
    assert result.exists(), "create() must create the returned directory"
    assert 42 in fake.created, "create() must append issue_number to fake.created"


# ---------------------------------------------------------------------------
# Test 3b: destroy — returns None, tracks issue_number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_destroy_returns_none_and_tracks(tmp_path: Path) -> None:
    """destroy() returns None and appends issue_number to fake.destroyed."""
    fake = _make_fake(tmp_path)
    result = await fake.destroy(issue_number=42)

    assert result is None, (
        f"WorkspacePort.destroy must return None; got {result!r}"
    )
    assert 42 in fake.destroyed


# ---------------------------------------------------------------------------
# Test 3c: destroy_all — returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_destroy_all_returns_none(tmp_path: Path) -> None:
    """destroy_all() returns None (no-op stub)."""
    fake = _make_fake(tmp_path)
    result = await fake.destroy_all()

    assert result is None, (
        f"WorkspacePort.destroy_all must return None; got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 3d: merge_main — returns bool, True on happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_main_returns_bool_true(tmp_path: Path) -> None:
    """merge_main() returns bool; True on the happy path."""
    fake = _make_fake(tmp_path)
    result = await fake.merge_main(
        worktree_path=tmp_path / "issue-1", branch="agent/issue-1"
    )

    assert isinstance(result, bool), (
        f"WorkspacePort.merge_main must return bool; got {type(result).__name__}"
    )
    assert result is True, "FakeWorkspace.merge_main must return True on happy path"


# ---------------------------------------------------------------------------
# Test 3e: get_conflicting_files — returns list[str], empty on happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conflicting_files_returns_list(tmp_path: Path) -> None:
    """get_conflicting_files() returns list[str]; empty list on happy path."""
    fake = _make_fake(tmp_path)
    result = await fake.get_conflicting_files(worktree_path=tmp_path / "issue-1")

    assert isinstance(result, list), (
        f"WorkspacePort.get_conflicting_files must return list; "
        f"got {type(result).__name__}"
    )
    assert all(isinstance(item, str) for item in result), (
        "WorkspacePort.get_conflicting_files must return list[str]; "
        f"got elements: {[type(i).__name__ for i in result]}"
    )
    assert result == [], (
        "FakeWorkspace.get_conflicting_files must return [] on happy path"
    )


# ---------------------------------------------------------------------------
# Test 3f: reset_to_main — returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_to_main_returns_none(tmp_path: Path) -> None:
    """reset_to_main() returns None (no-op stub)."""
    fake = _make_fake(tmp_path)
    result = await fake.reset_to_main(worktree_path=tmp_path / "issue-1")

    assert result is None, (
        f"WorkspacePort.reset_to_main must return None; got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 3g: post_work_cleanup — returns None, accepts keyword phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_work_cleanup_returns_none(tmp_path: Path) -> None:
    """post_work_cleanup() returns None; keyword arg phase= is accepted."""
    fake = _make_fake(tmp_path)
    result_default = await fake.post_work_cleanup(issue_number=42)
    result_explicit = await fake.post_work_cleanup(
        issue_number=42, phase="review"
    )

    assert result_default is None, (
        f"WorkspacePort.post_work_cleanup must return None; got {result_default!r}"
    )
    assert result_explicit is None, (
        "WorkspacePort.post_work_cleanup with explicit phase= must return None"
    )


# ---------------------------------------------------------------------------
# Test 3h: abort_merge — returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_merge_returns_none(tmp_path: Path) -> None:
    """abort_merge() returns None (no-op stub)."""
    fake = _make_fake(tmp_path)
    result = await fake.abort_merge(worktree_path=tmp_path / "issue-1")

    assert result is None, (
        f"WorkspacePort.abort_merge must return None; got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 3i: start_merge_main — returns bool, True on happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_merge_main_returns_bool_true(tmp_path: Path) -> None:
    """start_merge_main() returns bool; True on the happy path."""
    fake = _make_fake(tmp_path)
    result = await fake.start_merge_main(
        worktree_path=tmp_path / "issue-1", branch="agent/issue-1"
    )

    assert isinstance(result, bool), (
        f"WorkspacePort.start_merge_main must return bool; "
        f"got {type(result).__name__}"
    )
    assert result is True, (
        "FakeWorkspace.start_merge_main must return True on happy path"
    )


# ---------------------------------------------------------------------------
# Test 4: fault injection — permission error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_next_create_permission_error(tmp_path: Path) -> None:
    """fail_next_create(kind='permission') makes the next create() raise PermissionError."""
    fake = _make_fake(tmp_path)
    fake.fail_next_create(kind="permission")

    with pytest.raises(PermissionError):
        await fake.create(issue_number=1, branch="agent/issue-1")

    # Fault is single-shot; next call must succeed.
    result = await fake.create(issue_number=2, branch="agent/issue-2")
    assert isinstance(result, Path), "create() must succeed after the fault is consumed"


# ---------------------------------------------------------------------------
# Test 5: fault injection — disk full
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_next_create_disk_full(tmp_path: Path) -> None:
    """fail_next_create(kind='disk_full') makes the next create() raise OSError(28, …)."""
    fake = _make_fake(tmp_path)
    fake.fail_next_create(kind="disk_full")

    with pytest.raises(OSError) as exc_info:
        await fake.create(issue_number=3, branch="agent/issue-3")

    assert exc_info.value.errno == 28, (
        f"disk_full fault must raise OSError with errno=28; "
        f"got errno={exc_info.value.errno}"
    )

    # Fault is single-shot; next call must succeed.
    result = await fake.create(issue_number=4, branch="agent/issue-4")
    assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Test 6: fault injection — branch conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_next_create_branch_conflict(tmp_path: Path) -> None:
    """fail_next_create(kind='branch_conflict') makes the next create() raise RuntimeError."""
    fake = _make_fake(tmp_path)
    fake.fail_next_create(kind="branch_conflict")

    with pytest.raises(RuntimeError, match="worktree already exists"):
        await fake.create(issue_number=5, branch="agent/issue-5")

    # Fault is single-shot; next call must succeed.
    result = await fake.create(issue_number=6, branch="agent/issue-6")
    assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Test 7: stateful tracking — multiple creates and destroys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracking_accumulates_across_calls(tmp_path: Path) -> None:
    """created/destroyed lists accumulate correctly across multiple calls."""
    fake = _make_fake(tmp_path)

    await fake.create(issue_number=10, branch="agent/issue-10")
    await fake.create(issue_number=11, branch="agent/issue-11")
    await fake.destroy(issue_number=10)
    await fake.destroy(issue_number=10)  # idempotent second destroy

    assert fake.created == [10, 11], (
        f"fake.created must list issues in call order; got {fake.created}"
    )
    assert fake.destroyed == [10, 10], (
        f"fake.destroyed must record every destroy call; got {fake.destroyed}"
    )


# ---------------------------------------------------------------------------
# Test 8: create path is rooted under base_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_path_rooted_under_base(tmp_path: Path) -> None:
    """The Path returned by create() must live under the FakeWorkspace base_path."""
    fake = _make_fake(tmp_path)
    result = await fake.create(issue_number=99, branch="agent/issue-99")

    assert result.is_relative_to(tmp_path), (
        f"create() path {result} must be under base_path {tmp_path}"
    )
