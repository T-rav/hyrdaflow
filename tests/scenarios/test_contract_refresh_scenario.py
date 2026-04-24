"""MockWorld scenario for ContractRefreshLoop (spec §4.2, Task 23).

Two scenarios cover the loop's ends-of-the-world:

* ``test_no_drift_is_clean`` — every recorder returns an empty list
  (the "tool missing / sandbox offline" signal) or matches the
  committed cassette. ``_do_work`` reports ``status="clean"`` and
  the stubbed PR opener is never called.
* ``test_drift_opens_refresh_pr`` — the git recorder produces a
  cassette that diverges from the committed one under
  ``config.repo_root``. The real :func:`contract_diff.detect_fleet_drift`
  fires, the loop stages the cassette and calls the stubbed
  :func:`auto_pr.open_automated_pr_async`; assertions confirm the PR
  shape (title, branch, labels, files).

The loop's external surfaces are handled as follows:

* The per-adapter recorders (:func:`contract_recording.record_github`
  / ``record_git`` / ``record_docker`` / ``record_claude_stream``)
  are monkey-patched on the loop's module via the builder's
  existing ``contract_refresh_record_*`` port seams.
* :func:`auto_pr.open_automated_pr_async` is monkey-patched on the
  loop's module via the new ``contract_refresh_auto_pr`` port seam
  (mirrors the F1 corpus-learning pattern in
  ``tests/scenarios/catalog/loop_registrations.py``).
* :func:`subprocess.run` (the replay gate) is monkey-patched at the
  module level for the drift scenario so the loop's
  ``make trust-contracts`` call does not spawn a real make.

The committed cassette is written under ``config.repo_root / tests /
trust / contracts / cassettes / git`` so the real
:func:`contract_diff._committed_cassettes_for` can find it. Everything
stays inside the MockWorld's ``tmp_path`` sandbox.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class _AutoPrResultStub:
    """Duck-typed stand-in for :class:`auto_pr.AutoPrResult`.

    The loop only reads ``status``/``pr_url``/``error`` and the real
    dataclass is frozen with a validated status literal. Keeping the
    stub local avoids coupling this scenario to ``auto_pr``'s
    construction rules — the same pattern used by the corpus-learning
    scenario.
    """

    def __init__(
        self,
        *,
        status: str,
        pr_url: str | None = None,
        error: str | None = None,
    ) -> None:
        self.status = status
        self.pr_url = pr_url
        self.branch = "contract-refresh/scenario-branch"
        self.error = error


def _write_committed_git_cassette(repo_root: Path, *, stdout: str) -> Path:
    """Seed a committed git cassette under the loop's repo_root.

    The committed location must match
    ``contract_diff._COMMITTED_DIR_RELPATH["git"]`` so the real diff
    layer can enumerate it.
    """
    committed_dir = repo_root / "tests" / "trust" / "contracts" / "cassettes" / "git"
    committed_dir.mkdir(parents=True, exist_ok=True)
    path = committed_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "deadbeef",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {"exit_code": 0, "stdout": stdout, "stderr": ""},
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


def _write_recorded_git_cassette(tmp_dir: Path, *, stdout: str) -> Path:
    """Write a tmp-dir "fresh recording" cassette the recorder seam returns."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-04-23T09:15:30Z",
        "recorder_sha": "cafef00d",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {"exit_code": 0, "stdout": stdout, "stderr": ""},
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


class TestContractRefreshScenario:
    """§4.2 Task 23 — contract refresh MockWorld scenarios."""

    async def test_no_drift_is_clean(self, tmp_path: Path) -> None:
        """All recorders empty → loop ticks, reports clean, no PR filed.

        An empty recorder list is the "tool missing / sandbox offline"
        signal the diff layer treats as no-signal, so the happy path
        on an operator's dev box (no ``docker``/``gh``/``claude`` to
        hand) still produces a clean tick rather than a catastrophic
        all-deleted sweep.
        """
        world = MockWorld(tmp_path)

        open_calls: list[dict[str, Any]] = []

        async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
            open_calls.append(kwargs)
            return _AutoPrResultStub(
                status="opened", pr_url="https://github.com/hydra/hydraflow/pull/1"
            )

        _seed_ports(world, contract_refresh_auto_pr=fake_open)

        stats = await world.run_with_loops(["contract_refresh"], cycles=1)

        tick = stats["contract_refresh"]
        assert tick["status"] == "clean", tick
        assert tick["adapters_drifted"] == 0, tick
        assert tick["adapters_refreshed"] == 0, tick
        assert open_calls == [], (
            "PR opener must not be called when every recorder reports no signal"
        )

    async def test_drift_opens_refresh_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mismatched git cassette → real diff fires, PR opens.

        The committed cassette ships stdout ``"[main abc1234] initial\\n"``;
        the recorder side emits ``"[main feedf00d] renamed\\n"``. The
        ``sha:short`` normalizer collapses the SHA tokens but the
        commit-message word ``initial`` vs ``renamed`` is a real
        contract change, so ``detect_fleet_drift`` produces exactly
        one drifted cassette and the loop calls the stubbed auto_pr
        seam with the contract-refresh label set.
        """
        world = MockWorld(tmp_path)

        # The loop's config.repo_root is `tmp_path / "repo"` (per
        # ``make_bg_loop_deps`` → ``ConfigFactory.create``), so the
        # committed cassette must live there to be found by real
        # ``contract_diff._committed_cassettes_for``.
        repo_root = tmp_path / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")

        recorded = _write_recorded_git_cassette(
            tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
        )

        open_calls: list[dict[str, Any]] = []

        async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
            open_calls.append(kwargs)
            return _AutoPrResultStub(
                status="opened",
                pr_url="https://github.com/hydra/hydraflow/pull/42",
            )

        # Replay gate: stub ``subprocess.run`` on the loop's module
        # so ``make trust-contracts`` does not actually spawn.
        import contract_refresh_loop as _module

        def _fake_run(argv: Any, *_a: Any, **_k: Any) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="OK\n", stderr=""
            )

        monkeypatch.setattr(_module.subprocess, "run", _fake_run)

        _seed_ports(
            world,
            contract_refresh_record_git=lambda *_a, **_k: [recorded],
            contract_refresh_auto_pr=fake_open,
        )

        stats = await world.run_with_loops(["contract_refresh"], cycles=1)

        tick = stats["contract_refresh"]
        assert tick["status"] == "refreshed", tick
        assert tick["adapters_drifted"] == 1, tick
        assert tick["adapters_refreshed"] == 1, tick
        assert tick["pr_url"] == "https://github.com/hydra/hydraflow/pull/42"

        # The auto_pr seam saw exactly one call with the expected PR
        # shape — title, branch, and the contract-refresh label set.
        assert len(open_calls) == 1
        kwargs = open_calls[0]
        assert kwargs["branch"].startswith("contract-refresh/")
        assert kwargs["pr_title"].startswith("contract-refresh: ")
        assert "git" in kwargs["pr_title"]
        labels = kwargs["labels"]
        assert "contract-refresh" in labels
        assert "auto-merge" in labels
        # The staged file lives under the loop's repo_root — not the
        # ephemeral tmp/rec/git the recorder wrote to — because
        # ``_stage_drifted_cassettes`` copies into the committed path.
        files = [Path(p) for p in kwargs["files"]]
        assert len(files) == 1
        assert files[0].name == "commit.yaml"
        assert files[0].is_relative_to(repo_root)
