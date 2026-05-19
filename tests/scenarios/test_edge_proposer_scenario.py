"""MockWorld scenario for `EdgeProposerLoop` (ADR-0058).

Tier-3 expansion: the loop had neither catalog entry nor scenario coverage
when the missing-label bug (#?) shipped to production. Per
``docs/standards/testing/README.md``, a loop-observable bug fix requires a
scenario layer that exercises the loop through its real adapter.

Pattern B: real ``EdgeProposerLoop`` + real ``OpenAutoPRBotPRPort`` wired
against a tmp git repo, with ``subprocess_util.run_subprocess`` stubbed at
the I/O boundary so ``gh`` is never invoked but the auto_pr → label-ensure
→ pr-create wiring is exercised in full.
"""

from __future__ import annotations

import asyncio
import subprocess as _sp
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.scenario_loops


def _stub(
    pr_url: str = "https://github.com/x/y/pull/77",
    on_cmd: Callable[[tuple[str, ...]], None] | None = None,
) -> Callable[..., Awaitable[str]]:
    """`run_subprocess` stub: intercepts gh, lets git run real."""

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, timeout, runner
        if on_cmd is not None:
            on_cmd(cmd)
        if cmd[:3] == ("gh", "label", "create"):
            return ""
        if cmd[:3] == ("gh", "pr", "create"):
            return f"{pr_url}\n"
        if cmd[:3] == ("gh", "pr", "merge"):
            return ""
        try:
            return _sp.run(  # noqa: S603
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _sp.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


def _bootstrap_repo(tmp_path: Path) -> Path:
    """Init a tmp git repo + bare origin so push/worktree work end-to-end."""
    origin = tmp_path / "origin.git"
    _sp.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    _sp.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    for k, v in (
        ("user.email", "t@example.com"),
        ("user.name", "Tester"),
    ):
        _sp.run(
            ["git", "-C", str(repo), "config", k, v],
            check=True,
            capture_output=True,
        )
    (repo / "README.md").write_text("init\n")
    _sp.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    _sp.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(origin)],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(repo), "push", "-u", "origin", "main"],
        check=True,
        capture_output=True,
    )
    return repo


def _seed_terms(repo: Path) -> None:
    """Two terms (Alpha, Bravo) and source files where Alpha imports Bravo."""
    from ubiquitous_language import (  # noqa: PLC0415
        BoundedContext,
        Term,
        TermKind,
        TermStore,
    )

    src = repo / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "alpha.py").write_text("from bravo import Bravo\n\nclass Alpha:\n    pass\n")
    (src / "bravo.py").write_text("class Bravo:\n    pass\n")
    terms_dir = repo / "docs" / "wiki" / "terms"
    terms_dir.mkdir(parents=True, exist_ok=True)
    store = TermStore(terms_dir)
    store.write(
        Term(
            id="01H_ALPHA",
            name="Alpha",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Alpha depends on Bravo.",
            code_anchor="src/alpha.py:Alpha",
            confidence="accepted",
        )
    )
    store.write(
        Term(
            id="01H_BRAVO",
            name="Bravo",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Bravo used by Alpha.",
            code_anchor="src/bravo.py:Bravo",
            confidence="accepted",
        )
    )


def _make_loop(repo: Path):
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from edge_proposer_loop import EdgeProposerLoop  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from term_proposer_runtime import OpenAutoPRBotPRPort  # noqa: PLC0415
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    config = ConfigFactory.create(repo_root=repo)
    bus = EventBus()
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    pr_port = OpenAutoPRBotPRPort(repo_root=repo, gh_token="")
    return EdgeProposerLoop(config=config, deps=deps, pr_port=pr_port, repo_root=repo)


class TestEdgeProposerScenario:
    async def test_label_is_ensured_before_pr_create(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: loop → BotPRPort → auto_pr → `gh label create` → `gh pr create`.

        Regression for the production crash where the loop's PR label did not
        exist on the repo and ``gh pr create --label hydraflow-ul-edges`` failed
        with rc=1 (server.log 2026-05-13).
        """
        repo = _bootstrap_repo(tmp_path)
        _seed_terms(repo)
        calls: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            "subprocess_util.run_subprocess",
            _stub(on_cmd=lambda cmd: calls.append(cmd) if cmd[0] == "gh" else None),
        )

        loop = _make_loop(repo)
        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "ok"
        assert result["opened_pr"] is True

        label_idx = next(
            (
                i
                for i, c in enumerate(calls)
                if c[:3] == ("gh", "label", "create") and "hydraflow-ul-edges" in c
            ),
            None,
        )
        pr_idx = next(
            (i for i, c in enumerate(calls) if c[:3] == ("gh", "pr", "create")),
            None,
        )
        assert label_idx is not None, f"label-create not called; gh calls: {calls}"
        assert pr_idx is not None, "pr-create not called"
        assert label_idx < pr_idx, "label-create must precede pr-create"

    async def test_kill_switch_returns_disabled(self, tmp_path: Path) -> None:
        repo = _bootstrap_repo(tmp_path)
        (repo / "src").mkdir(exist_ok=True)
        loop = _make_loop(repo)
        loop._config = loop._config.model_copy(update={"edge_proposer_enabled": False})
        result = await loop._do_work()
        assert result == {"status": "disabled"}
