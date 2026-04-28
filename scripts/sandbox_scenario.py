"""sandbox_scenario — host-side harness for the sandbox tier.

Subcommands:
    run NAME       — Compute seed, build (if needed), boot stack, run one
                     scenario, capture artifacts, tear down.
    run-all        — Same, but iterates the catalog; produces a summary
                     table and exits nonzero if any failed.
    status         — Show current stack state without booting.
    down           — Tear down the stack and remove volumes.
    shell          — Drop into bash inside the hydraflow container.
    seed NAME      — Compute and write the JSON seed without booting.

Returns exit code 0 on full success, 1 on any scenario failure, 2 on
infrastructure failure (build / healthcheck / playwright crash).
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.sandbox.yml"
SEEDS_DIR = REPO_ROOT / "tests" / "sandbox_scenarios" / "seeds"
RESULTS_DIR = Path("/tmp/sandbox-results")  # noqa: S108  # nosec B108  # Sandbox CLI artifacts dir; not a security boundary, contents are mkdir'd per-run.

# Ensure `tests.sandbox_scenarios.scenarios.*` and `mockworld.*` are
# importable when this script is invoked directly (e.g.
# `python scripts/sandbox_scenario.py`). Under pytest the rootdir +
# editable-install pth file handle this, but the CLI entrypoint doesn't
# get that for free.
for _p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def load_scenario(name: str):
    """Import a scenario module by NAME."""
    return importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")


def write_seed(name: str) -> Path:
    """Compute the scenario's seed and write it to SEEDS_DIR."""
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_scenario(name)
    out = SEEDS_DIR / f"{mod.NAME}.json"
    out.write_text(mod.seed().to_json())
    return out


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        check=False,
    )


def cmd_seed(name: str) -> int:
    out = write_seed(name)
    print(f"Wrote seed: {out}")
    return 0


def cmd_down() -> int:
    print("Stopping stack...")
    _compose("down", "-v")
    print("Done.")
    return 0


def cmd_status() -> int:
    return _compose("ps").returncode


def cmd_shell() -> int:
    return _compose("exec", "hydraflow", "/bin/bash").returncode


def _wait_for_healthy(timeout: float = 60.0) -> bool:
    """Poll docker compose ps for hydraflow (healthy) up to timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "ps",
                "--format",
                "json",
                "hydraflow",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if "(healthy)" in result.stdout or '"Health":"healthy"' in result.stdout:
            return True
        time.sleep(2)
    return False


def cmd_run(name: str) -> int:
    print(f"[1/5] Computing seed for {name}...")
    seed_path = write_seed(name)

    # Make sure the seed file the container reads matches THIS scenario.
    # The container always reads /seed/scenario.json, so symlink it.
    target = SEEDS_DIR / "scenario.json"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(seed_path.name)

    print("[2/5] Building images (cached when possible)...")
    # ``playwright`` must be built explicitly because the MS image ships no
    # test runner — ``Dockerfile.playwright`` adds pytest at build time so
    # ``compose run playwright pytest …`` works on the air-gapped network.
    rc = _compose("build", "hydraflow", "ui", "playwright").returncode
    if rc != 0:
        print(f"BUILD FAILED ({rc})")
        return 2

    print("[3/5] Starting stack on internal network...")
    rc = _compose("up", "-d", "hydraflow", "ui").returncode
    if rc != 0:
        print(f"UP FAILED ({rc})")
        return 2

    print("[4/5] Waiting for hydraflow /healthz...")
    if not _wait_for_healthy(60):
        print("HEALTHCHECK TIMEOUT — collecting logs")
        _compose("logs", "hydraflow")
        cmd_down()
        return 2

    print("[5/5] Running playwright assertions...")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # ``-c tests/sandbox_scenarios/pytest.ini`` makes that file the
    # rootdir-config so pytest does NOT autoload the project-wide
    # ``tests/conftest.py`` (which imports pydantic/HydraFlow internals
    # that the slim playwright image doesn't have). The runner's own
    # conftest under ``tests/sandbox_scenarios/runner/`` still loads
    # because it's inside the new rootdir.
    rc = _compose(
        "run",
        "--rm",
        "-e",
        f"SCENARIO_NAME={name}",
        "playwright",
        "pytest",
        "-c",
        "tests/sandbox_scenarios/pytest.ini",
        f"tests/sandbox_scenarios/runner/test_scenarios.py::test_scenario[{name}]",
        "-v",
        "--junitxml=/results/junit.xml",
    ).returncode

    if rc != 0:
        print(f"FAILED {name}")
        _compose("logs", "hydraflow")
    else:
        print(f"PASSED {name}")

    cmd_down()
    return rc


def cmd_run_all() -> int:
    """Iterate every scenario; print summary; exit nonzero on any failure."""
    from tests.sandbox_scenarios.runner.loader import load_all_scenarios

    scenarios = load_all_scenarios()
    results: list[tuple[str, int, float]] = []
    for s in scenarios:
        if s.NAME == "s00_smoke":
            print(f"SKIPPED {s.NAME} (parity-only, no Tier-2 implementation)")
            continue
        start = time.monotonic()
        rc = cmd_run(s.NAME)
        elapsed = time.monotonic() - start
        results.append((s.NAME, rc, elapsed))

    print("\n--- Summary ---")
    fails = 0
    for name, rc, elapsed in results:
        status = "PASSED" if rc == 0 else "FAILED"
        if rc != 0:
            fails += 1
        print(f"{status:8s} {name:40s} ({elapsed:5.1f}s)")
    print(f"\n{len(results) - fails} passed, {fails} failed")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sandbox_scenario")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("down")
    sub.add_parser("shell")
    sub.add_parser("run-all")
    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("name")

    args = parser.parse_args()
    nullary = {
        "status": cmd_status,
        "down": cmd_down,
        "shell": cmd_shell,
        "run-all": cmd_run_all,
    }
    unary = {
        "run": cmd_run,
        "seed": cmd_seed,
    }
    if args.cmd in nullary:
        return nullary[args.cmd]()
    if args.cmd in unary:
        return unary[args.cmd](args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
