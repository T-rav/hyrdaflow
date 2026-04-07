"""Regression test for #6164 — file_memory_suggestion must pass the real
Hindsight client to schedule_retain so writes actually reach the vector store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_file_memory_suggestion_passes_real_client(tmp_path):
    from memory import file_memory_suggestion
    from tests.helpers import ConfigFactory

    # CRITICAL: use ConfigFactory(repo_root=tmp_path) — the auto-resolver in
    # config._resolve_base_paths sets data_root to repo_root/.hydraflow when
    # data_root is the default Path(".") . If we pass HydraFlowConfig() without
    # repo_root, the resolver falls back to CWD/.hydraflow, which during a test
    # run pollutes the actual worktree's .hydraflow/memory/items.jsonl.
    cfg = ConfigFactory.create(repo_root=tmp_path)
    fake_client = MagicMock(name="HindsightClient")
    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "principle: a meaningful thing\n"
        "rationale: because it matters\n"
        "failure_mode: things break without it\n"
        "scope: hydraflow\n"
        "MEMORY_SUGGESTION_END\n"
    )

    # NOTE: patch hindsight.schedule_retain (definition module), not
    # memory.schedule_retain — memory.py does a deferred local import
    # inside file_memory_suggestion, so there is no module-level binding
    # to patch on the memory side. Without this, the patch would silently
    # fail to intercept the call.
    with patch("hindsight.schedule_retain") as mock_schedule:
        await file_memory_suggestion(
            transcript,
            source="review",
            reference="test",
            config=cfg,
            hindsight=fake_client,
        )

    mock_schedule.assert_called_once()
    assert mock_schedule.call_args.args[0] is fake_client, (
        "schedule_retain must receive the real client, not None"
    )
