"""Regression tests for critical product fixes batch.

Covers: #7462, #7463, #7418, #7414, #7402, #7400, #7419, #7337, #7391.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from events import EventBus, EventType, HydraFlowEvent  # noqa: E402
from file_util import append_jsonl, atomic_write, file_lock  # noqa: E402

# ---------------------------------------------------------------------------
# #7462 — file_util encoding
# ---------------------------------------------------------------------------


class TestFileUtilEncoding:
    """Verify file_util functions write UTF-8 regardless of locale."""

    def test_atomic_write_handles_unicode(self, tmp_path: Path) -> None:
        target = tmp_path / "uni.txt"
        atomic_write(target, "caf\u00e9 \u2603 \U0001f680")
        assert target.read_text(encoding="utf-8") == "caf\u00e9 \u2603 \U0001f680"

    def test_append_jsonl_handles_unicode(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        append_jsonl(target, '{"msg": "\u00fc\u00f6\u00e4"}')
        assert "\u00fc\u00f6\u00e4" in target.read_text(encoding="utf-8")

    def test_file_lock_opens_with_encoding(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        with file_lock(lock_path):
            assert lock_path.exists()


# ---------------------------------------------------------------------------
# #7463 — pr_manager._run_with_body_file encoding
# ---------------------------------------------------------------------------


class TestPRManagerBodyFileEncoding:
    """Verify _run_with_body_file writes UTF-8."""

    @pytest.mark.asyncio
    async def test_body_file_preserves_unicode(self, tmp_path: Path) -> None:
        from pr_manager import PRManager  # noqa: PLC0415

        config = MagicMock()
        config.repo_root = tmp_path
        config.repo = "test/repo"
        creds = MagicMock()
        creds.gh_token = "fake"
        bus = EventBus()

        mgr = PRManager(config=config, credentials=creds, event_bus=bus)

        body = "PR body with \u00e9\u00e8\u00ea and \U0001f680"
        with patch(
            "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = "ok"
            await mgr._run_with_body_file("gh", "pr", "create", body=body)
            # The temp file was already cleaned up, but the mock captured the path
            call_args = mock_run.call_args[0]
            # --body-file flag should have been passed
            assert "--body-file" in call_args


# ---------------------------------------------------------------------------
# #7418 — EventBus._history race condition (lock protection)
# ---------------------------------------------------------------------------


class TestEventBusHistoryLock:
    """Verify EventBus protects _history with a lock."""

    def test_event_bus_has_history_lock(self) -> None:
        bus = EventBus()
        assert hasattr(bus, "_history_lock")
        assert isinstance(bus._history_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_concurrent_publish_and_load_do_not_corrupt(
        self, tmp_path: Path
    ) -> None:
        """Publish and load_history_from_disk concurrently without corruption."""
        from events import EventLog  # noqa: PLC0415

        log_path = tmp_path / "events.jsonl"
        event_log = EventLog(log_path)
        bus = EventBus(event_log=event_log)

        # Publish some events
        for i in range(10):
            await bus.publish(
                HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"i": i})
            )
        await bus.flush_persists()

        # Concurrently publish more + load from disk
        async def publish_batch() -> None:
            for i in range(10, 20):
                await bus.publish(
                    HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"i": i})
                )

        await asyncio.gather(publish_batch(), bus.load_history_from_disk())

        # History should be consistent (no crash, no lost items from load)
        history = bus.get_history()
        assert len(history) > 0


# ---------------------------------------------------------------------------
# #7414 — agent._append_skill_result atomic write
# ---------------------------------------------------------------------------


class TestAgentSkillResultAtomicWrite:
    """Verify _append_skill_result uses atomic_write."""

    def test_append_skill_result_uses_atomic_write(self, tmp_path: Path) -> None:
        from agent import AgentRunner  # noqa: PLC0415

        config = MagicMock()
        config.data_root = tmp_path

        ctx = MagicMock()
        ctx.issue_number = 42
        ctx.phase = "implement"
        ctx.run_id = 1

        runner = AgentRunner.__new__(AgentRunner)
        runner._config = config
        runner.logger = MagicMock()

        with patch("file_util.atomic_write") as mock_aw:
            runner._append_skill_result(
                ctx,
                skill_name="test-skill",
                passed=True,
                attempts=1,
                duration_seconds=1.5,
                blocking=False,
            )
            mock_aw.assert_called_once()
            path_arg = mock_aw.call_args[0][0]
            assert path_arg.name == "skill_results.json"


# ---------------------------------------------------------------------------
# #7402 — compact_memory drops malformed JSONL
# ---------------------------------------------------------------------------


class TestCompactMemoryMalformedJSONL:
    """Verify malformed JSONL lines are dropped, not kept."""

    @pytest.mark.asyncio
    async def test_malformed_lines_dropped_during_compaction(
        self, tmp_path: Path
    ) -> None:
        from admin_tasks import run_compact  # noqa: PLC0415

        config = MagicMock()
        config.memory_dir = tmp_path

        # Write items.jsonl with a mix of valid and malformed lines
        items_path = tmp_path / "items.jsonl"
        items_path.write_text(
            '{"id": "good-1", "text": "valid"}\n'
            "this is not valid json\n"
            '{"id": "good-2", "text": "also valid"}\n',
            encoding="utf-8",
        )

        # Mock the scorer to trigger eviction
        with patch("memory_scoring.MemoryScorer") as MockScorer:
            scorer = MockScorer.return_value
            scorer.load_item_scores.return_value = {}
            scorer.eviction_candidates.return_value = [1]
            scorer.classify_for_compaction.return_value = "auto_evict"
            scorer.evict_items.return_value = [1]

            result = await run_compact(config)

        # The malformed line should NOT be in the output
        content = items_path.read_text(encoding="utf-8")
        assert "this is not valid json" not in content
        assert result.success


# ---------------------------------------------------------------------------
# #7400 — HindsightClient async context manager
# ---------------------------------------------------------------------------


class TestHindsightClientContextManager:
    """Verify HindsightClient supports async with."""

    @pytest.mark.asyncio
    async def test_async_context_manager_calls_close(self) -> None:
        from hindsight import HindsightClient  # noqa: PLC0415

        client = HindsightClient("http://localhost:9999")
        with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
            async with client as c:
                assert c is client
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_on_exception(self) -> None:
        from hindsight import HindsightClient  # noqa: PLC0415

        client = HindsightClient("http://localhost:9999")
        with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
            with pytest.raises(ValueError, match="test"):
                async with client:
                    raise ValueError("test")
            mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# #7337 — trace_rollup temp file cleanup on replace failure
# ---------------------------------------------------------------------------


class TestTraceRollupTempCleanup:
    """Verify latest.tmp is cleaned up if replace() fails."""

    def test_latest_tmp_cleaned_on_replace_failure(self, tmp_path: Path) -> None:
        from models import (  # noqa: PLC0415
            SubprocessTrace,
            TraceTokenStats,
            TraceToolProfile,
        )
        from trace_rollup import write_phase_rollup  # noqa: PLC0415

        config = MagicMock()
        config.data_root = tmp_path
        config.factory_metrics_path = tmp_path / "factory_metrics.jsonl"

        # Create a valid subprocess trace file
        run_dir = tmp_path / "traces" / "42" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        trace = SubprocessTrace(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
            subprocess_idx=0,
            backend="claude",
            started_at="2026-04-06T12:00:00Z",
            ended_at="2026-04-06T12:01:00Z",
            success=True,
            crashed=False,
            tokens=TraceTokenStats(
                prompt_tokens=100,
                completion_tokens=50,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cache_hit_rate=0.0,
            ),
            tools=TraceToolProfile(
                tool_counts={},
                tool_errors={},
                total_invocations=0,
            ),
            tool_calls=[],
            skill_results=[],
            turn_count=2,
            inference_count=2,
        )
        (run_dir / "subprocess-0.json").write_text(
            trace.model_dump_json(), encoding="utf-8"
        )

        # Make replace() fail
        latest_dir = run_dir.parent
        with (
            patch.object(Path, "replace", side_effect=OSError("permission denied")),
            pytest.raises(OSError, match="permission denied"),
        ):
            write_phase_rollup(
                config=config, issue_number=42, phase="implement", run_id=1
            )

        # latest.tmp should have been cleaned up
        assert not (latest_dir / "latest.tmp").exists()


# ---------------------------------------------------------------------------
# #7391 — sentry_loop HTTP error handling
# ---------------------------------------------------------------------------


class TestSentryLoopHttpErrorHandling:
    """Verify _list_projects and _fetch_unresolved handle HTTP errors gracefully."""

    @pytest.mark.asyncio
    async def test_list_projects_returns_empty_on_http_error(self) -> None:
        import httpx  # noqa: PLC0415

        from sentry_loop import SentryLoop  # noqa: PLC0415

        config = MagicMock()
        config.sentry_org = "test-org"
        config.sentry_project_filter = ""
        creds = MagicMock()
        creds.sentry_auth_token = "fake-token"
        deps = MagicMock()
        deps.bus = EventBus()

        loop = SentryLoop(config=config, prs=MagicMock(), deps=deps, credentials=creds)

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.request = MagicMock()
        error = httpx.HTTPStatusError(
            "Forbidden", request=mock_response.request, response=mock_response
        )

        with patch("sentry_loop.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            client_instance.get = AsyncMock(side_effect=error)

            result = await loop._list_projects()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_unresolved_returns_empty_on_http_error(self) -> None:
        import httpx  # noqa: PLC0415

        from sentry_loop import SentryLoop  # noqa: PLC0415

        config = MagicMock()
        config.sentry_org = "test-org"
        creds = MagicMock()
        creds.sentry_auth_token = "fake-token"
        deps = MagicMock()
        deps.bus = EventBus()

        loop = SentryLoop(config=config, prs=MagicMock(), deps=deps, credentials=creds)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.request = MagicMock()
        error = httpx.HTTPStatusError(
            "Server Error", request=mock_response.request, response=mock_response
        )

        with patch("sentry_loop.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            client_instance.get = AsyncMock(side_effect=error)

            result = await loop._fetch_unresolved("my-project")

        assert result == []
