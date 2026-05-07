"""FakeCoverageAuditorLoop — weekly un-cassetted-method detector.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.7. Introspects fake classes under `src/mockworld/fakes/` via
``ast.parse`` and compares two method sets to their coverage sources:

- ``adapter-surface`` — public non-private methods. Covered by a
  cassette under ``tests/trust/contracts/cassettes/<adapter>/`` whose
  ``input.command`` names the method.
- ``test-helper`` — helpers the scenarios drive (``script_*``,
  ``fail_service``, ``heal_service``, ``set_state``). Covered by a
  scenario test under ``tests/scenarios/`` that calls the helper.

Files `hydraflow-find` + `fake-coverage-gap` + one of
`adapter-surface` | `test-helper` per uncovered method. Escalates
after 3 attempts to `hitl-escalation` + `fake-coverage-stuck`.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import yaml

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.fake_coverage_auditor_loop")

_MAX_ATTEMPTS = 3
_HELPER_PREFIXES = ("script_",)
_HELPER_NAMES = frozenset({"fail_service", "heal_service", "set_state"})


def _is_helper(name: str) -> bool:
    return any(name.startswith(p) for p in _HELPER_PREFIXES) or name in _HELPER_NAMES


def catalog_fake_methods(fake_dir: Path) -> dict[str, dict[str, list[str]]]:
    """AST-scan ``fake_dir/*.py`` for classes starting with ``Fake``.

    Returns::

        {
          "FakeGitHub": {
            "adapter-surface": ["create_issue", "close_issue", ...],
            "test-helper":     ["script_ci", "fail_service", ...],
          },
          ...
        }
    """
    catalog: dict[str, dict[str, list[str]]] = {}
    if not fake_dir.exists():
        return catalog
    for path in sorted(fake_dir.glob("*.py")):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            logger.debug("syntax error parsing %s", path)
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("Fake"):
                continue
            surface: list[str] = []
            helpers: list[str] = []
            for child in node.body:
                if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                name = child.name
                if name.startswith("_"):
                    continue
                if _is_helper(name):
                    helpers.append(name)
                else:
                    surface.append(name)
            catalog[node.name] = {
                "adapter-surface": sorted(surface),
                "test-helper": sorted(helpers),
            }
    return catalog


def catalog_cassette_methods(cassette_dir: Path) -> set[str]:
    """Return the set of real-adapter methods recorded under ``cassette_dir``.

    Each cassette is a YAML file with an ``input.command`` field naming
    the method invoked (per §4.2 cassette schema, landed in
    `src/contracts/_schema.py`).
    """
    methods: set[str] = set()
    if not cassette_dir.exists():
        return methods
    for path in cassette_dir.rglob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        inp = data.get("input")
        if not isinstance(inp, dict):
            continue
        cmd = inp.get("command")
        if isinstance(cmd, str):
            methods.add(cmd)
    return methods


# Map from fake class name → cassette sub-directory.
_FAKE_TO_CASSETTE_DIR: dict[str, str] = {
    "FakeGitHub": "github",
    "FakeDocker": "docker",
    "FakeGit": "git",
    "FakeBeads": "beads",
    "FakeSentry": "sentry",
    "FakeHTTP": "http",
    "FakeSubprocessRunner": "subprocess",
    "FakeFS": "fs",
    "FakeLLM": "llm",
}


class FakeCoverageAuditorLoop(BaseBackgroundLoop):
    """Weekly fake-surface coverage auditor (spec §4.7)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="fake_coverage_auditor",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.fake_coverage_auditor_interval

    async def _grep_scenario_for_helper(self, helper: str) -> bool:
        """Return True iff ``tests/scenarios/`` contains a call to ``helper``."""
        repo = self._config.repo_root
        scenario_dir = repo / "tests" / "scenarios"
        if not scenario_dir.exists():
            return False
        cmd = [
            "rg",
            "--type=py",
            "-l",
            "--fixed-strings",
            f"{helper}(",
            str(scenario_dir),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        # rg exits 0 on match, 1 on no-match, 2+ on error.
        return proc.returncode == 0 and bool(stdout.strip())

    async def _file_surface_gap(self, fake: str, method: str) -> int:
        title = f"Un-cassetted adapter method: {fake}.{method}"
        subdir = _FAKE_TO_CASSETTE_DIR.get(fake, "?")
        body = (
            f"## Fake coverage gap — adapter surface\n\n"
            f"Fake class `{fake}` exposes a public method `{method}` with no "
            f"matching cassette under "
            f"`tests/trust/contracts/cassettes/{subdir}/`.\n\n"
            f"**Repair:** record a cassette that exercises the real-adapter "
            f"counterpart and commit. Spec §4.7; filed by `fake_coverage_auditor`."
        )
        return await self._pr.create_issue(
            title,
            body,
            ["hydraflow-find", "fake-coverage-gap", "adapter-surface"],
        )

    async def _file_helper_gap(self, fake: str, method: str) -> int:
        title = f"Un-exercised test helper: {fake}.{method}"
        body = (
            f"## Fake coverage gap — test helper\n\n"
            f"Fake class `{fake}` exposes helper `{method}` but no scenario "
            f"under `tests/scenarios/` invokes it (grep-based search).\n\n"
            f"**Repair:** add a scenario that calls `{method}` so the helper "
            f"is part of the working contract. Spec §4.7."
        )
        return await self._pr.create_issue(
            title,
            body,
            ["hydraflow-find", "fake-coverage-gap", "test-helper"],
        )

    async def _file_escalation(self, key: str, attempts: int) -> int:
        title = f"HITL: fake coverage gap {key} unresolved after {attempts}"
        body = (
            f"`fake_coverage_auditor` has re-filed the `{key}` gap "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "fake-coverage-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for closed ``fake-coverage-stuck`` escalations."""
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
            "--label",
            "hitl-escalation",
            "--label",
            "fake-coverage-stuck",
            "--author",
            "@me",
            "--limit",
            "100",
            "--json",
            "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for key in list(keep):
                if (
                    key.startswith("fake_coverage_auditor:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_fake_coverage_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    async def _do_work(self) -> WorkCycleResult:
        """Scan fakes, compare to cassettes + scenario grep, file gaps."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        repo = self._config.repo_root
        fake_dir = repo / "src" / "mockworld" / "fakes"
        cassette_root = repo / "tests" / "trust" / "contracts" / "cassettes"
        catalog = catalog_fake_methods(fake_dir)
        if not catalog:
            return {"status": "no_fakes", "filed": 0}

        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        all_known: dict[str, list[str]] = {}
        for fake, sets in catalog.items():
            surface_methods = sets["adapter-surface"]
            helper_methods = sets["test-helper"]
            cassette_subdir = cassette_root / _FAKE_TO_CASSETTE_DIR.get(fake, "")
            cassetted = catalog_cassette_methods(cassette_subdir)

            covered: list[str] = []
            for method in surface_methods:
                if method in cassetted:
                    covered.append(method)
                    continue
                key = f"fake_coverage_auditor:{fake}.{method}:adapter-surface"
                if key in dedup:
                    continue
                attempts = self._state.inc_fake_coverage_attempts(
                    f"{fake}.{method}:adapter-surface"
                )
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        f"{fake}.{method}:adapter-surface", attempts
                    )
                    escalated += 1
                else:
                    await self._file_surface_gap(fake, method)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

            for method in helper_methods:
                if await self._grep_scenario_for_helper(method):
                    covered.append(method)
                    continue
                key = f"fake_coverage_auditor:{fake}.{method}:test-helper"
                if key in dedup:
                    continue
                attempts = self._state.inc_fake_coverage_attempts(
                    f"{fake}.{method}:test-helper"
                )
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        f"{fake}.{method}:test-helper", attempts
                    )
                    escalated += 1
                else:
                    await self._file_helper_gap(fake, method)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

            all_known[fake] = sorted(covered)

        self._state.set_fake_coverage_last_known(all_known)
        self._emit_trace(t0, fakes_seen=len(catalog))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "fakes_seen": len(catalog),
        }

    def _emit_trace(self, t0: float, *, fakes_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["ast.parse", "fakes/"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"fakes_seen={fakes_seen}",
        )
