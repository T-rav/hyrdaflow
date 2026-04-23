"""Tests for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from skill_prompt_eval_loop import SkillPromptEvalLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_skill_prompt_last_green.return_value = {}
    state.get_skill_prompt_attempts.return_value = 0
    state.inc_skill_prompt_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "skill_prompt_eval"
    assert loop._get_default_interval() == 604800


async def test_detects_regression_pass_to_fail(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_skill_prompt_last_green.return_value = {
        "case_shrink_001": "PASS",
        "case_scope_002": "PASS",
    }
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "FAIL",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            },
            {
                "case_id": "case_scope_002",
                "skill": "scope_check",
                "status": "PASS",
                "provenance": "hand-crafted",
                "expected_catcher": "scope_check",
            },
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "diff_sanity" in title
    assert "case_shrink_001" in title
    labels = pr.create_issue.await_args.args[2]
    assert "skill-prompt-drift" in labels


async def test_weak_case_sampling_files_corpus_case_weak(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    # 10 learning-loop cases, all PASS — loop expects some to be caught
    # (test provides `expected_catcher: diff_sanity` but the run returned
    # `skill=diff_sanity, status=PASS` meaning the skill let it through).
    cases = [
        {
            "case_id": f"case_learn_{i:03d}",
            "skill": "diff_sanity",
            "status": "PASS",
            "provenance": "learning-loop",
            "expected_catcher": "diff_sanity",
        }
        for i in range(10)
    ]

    async def fake_run_corpus() -> list[dict]:
        return cases

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    # 10% of 10 = 1 case sampled. Sampled case is flagged because
    # its expected catcher passed it. So 1 corpus-case-weak issue.
    assert stats["weak_cases_flagged"] >= 1
    weak_calls = [
        c
        for c in pr.create_issue.await_args_list
        if "corpus-case-weak" in (c.args[2] if len(c.args) > 2 else [])
    ]
    assert len(weak_calls) >= 1
