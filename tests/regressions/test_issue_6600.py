"""Regression test for issue #6600.

``_hitl_routes.py:146`` calls ``asyncio.create_task(ctx.warm_hitl_summary(...))``
without storing the task reference or attaching a done callback.  If the task
raises an exception that escapes the coroutine, it is silently swallowed by the
event loop — no log, no Sentry event, no retry.  The unstored reference also
makes the task eligible for premature garbage collection.

The correct pattern (established in ``events.py:348``) is to store the task
in a set, attach a ``done_callback`` that logs exceptions, and discard the
task from the set when it completes.

These tests intercept ``asyncio.create_task`` in the HITL route handler and
verify the returned task is protected.  They will FAIL (RED) until the
create_task call site is fixed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestIssue6600FireAndForgetTask:
    """create_task for warm_hitl_summary must be protected from silent failure."""

    @pytest.mark.asyncio
    async def test_create_task_result_has_done_callback(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The task returned by create_task must have add_done_callback called.

        The current code discards the task reference and never attaches a
        done_callback.  Following the ``events.py:348`` pattern, the fix
        should call ``task.add_done_callback(...)`` so exceptions are logged
        instead of silently lost.

        This test FAILS (RED) until a done_callback is attached.
        """
        from config import Credentials
        from dashboard_routes import create_router
        from models import HITLItem
        from pr_manager import PRManager

        # Enable the summarisation path so create_task is reached.
        config.transcript_summarization_enabled = True
        config.dry_run = False

        creds = Credentials(gh_token="test-token")

        pr_mgr = PRManager(config, event_bus)
        hitl_item = HITLItem(issue=42, title="Stuck on CI", pr=100)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
            credentials=creds,
        )

        # Find the get_hitl endpoint registered on the router.
        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint
                break
        assert get_hitl is not None, "Could not find /api/hitl route"

        # Intercept asyncio.create_task: return a MagicMock task so we can
        # assert whether add_done_callback was called on it.
        mock_task = MagicMock(spec=asyncio.Task)
        captured_coros: list = []

        def spy_create_task(coro, **kwargs):
            # Close the coroutine to avoid RuntimeWarning about it never
            # being awaited — we don't need it to actually run.
            captured_coros.append(coro)
            coro.close()
            return mock_task

        with patch("asyncio.create_task", side_effect=spy_create_task):
            await get_hitl()

        # Precondition: the warm_hitl_summary path was reached.
        assert len(captured_coros) >= 1, (
            "Expected asyncio.create_task to be called for warm_hitl_summary, "
            "but it was never called.  Check that the test setup satisfies all "
            "five conditions at _hitl_routes.py:139-145."
        )

        # The bug: add_done_callback is never called on the task.
        (
            mock_task.add_done_callback.assert_called(
                # message shown when assertion fails (i.e. when the bug exists)
            ),
            (
                "asyncio.create_task() for warm_hitl_summary returned a task but "
                "add_done_callback was never called on it.  Exceptions from the "
                "background task will be silently swallowed.  See issue #6600."
            ),
        )

    @pytest.mark.asyncio
    async def test_create_task_result_is_stored(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The task returned by create_task must be stored to prevent GC.

        Python's GC can collect a Task with no external references before it
        completes, silently cancelling it.  The task should be stored in a
        set (like ``_pending_persists`` in ``events.py``) and discarded via
        a done_callback when it finishes.

        This test inspects the source of ``_hitl_routes`` to verify the
        ``create_task`` result is assigned to a variable (i.e. the return
        value is not discarded as a bare expression statement).

        This test FAILS (RED) until the task reference is stored.
        """
        import ast
        import inspect

        from dashboard_routes import _hitl_routes

        source = inspect.getsource(_hitl_routes)
        tree = ast.parse(source)

        # Find all calls to asyncio.create_task or create_task in the module.
        bare_create_task_calls = []
        for node in ast.walk(tree):
            # Look for expression statements (bare calls, not assignments).
            if not isinstance(node, ast.Expr):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            # Check if the call is asyncio.create_task(...) or create_task(...)
            func = call.func
            is_create_task = False
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "create_task"
                or isinstance(func, ast.Name)
                and func.id == "create_task"
            ):
                is_create_task = True
            if is_create_task:
                bare_create_task_calls.append(node)

        assert len(bare_create_task_calls) == 0, (
            f"Found {len(bare_create_task_calls)} bare asyncio.create_task() "
            f"call(s) whose return value is discarded (line(s): "
            f"{[n.lineno for n in bare_create_task_calls]}).  "
            f"The task reference must be stored to prevent premature GC.  "
            f"See issue #6600."
        )
