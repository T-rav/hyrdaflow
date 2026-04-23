"""Shared replay harness for fake contract tests.

Each test_fake_*_contract.py uses `replay_cassette` to:
1. Load + validate a YAML cassette,
2. Invoke its adapter-specific fake via a callback,
3. Normalize both sides and assert field-by-field equality.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from tests.trust.contracts._schema import Cassette, apply_normalizers, load_cassette


@dataclass(frozen=True)
class FakeOutput:
    """Shape the fake-invoker callback must return."""

    exit_code: int
    stdout: str
    stderr: str


FakeInvoker = Callable[[Cassette], Awaitable[FakeOutput]]


async def replay_cassette(path: Path, invoke_fake: FakeInvoker) -> None:
    """Replay *path* through *invoke_fake*; assert equality under normalizers.

    Raises AssertionError on mismatch so pytest reports it. The harness does
    not catch schema errors — let them propagate so a bad cassette fails
    loudly rather than silently being treated as "fake diverged".
    """
    cassette = load_cassette(path)
    got = await invoke_fake(cassette)

    want_stdout = apply_normalizers(cassette.output.stdout, cassette.normalizers)
    got_stdout = apply_normalizers(got.stdout, cassette.normalizers)

    want_stderr = apply_normalizers(cassette.output.stderr, cassette.normalizers)
    got_stderr = apply_normalizers(got.stderr, cassette.normalizers)

    assert got.exit_code == cassette.output.exit_code, (
        f"{path.name}: exit_code mismatch — "
        f"cassette={cassette.output.exit_code} fake={got.exit_code}"
    )
    assert got_stdout == want_stdout, (
        f"{path.name}: stdout drift after normalizers {cassette.normalizers}\n"
        f"--- cassette ---\n{want_stdout}\n--- fake ---\n{got_stdout}"
    )
    assert got_stderr == want_stderr, (
        f"{path.name}: stderr drift after normalizers {cassette.normalizers}\n"
        f"--- cassette ---\n{want_stderr}\n--- fake ---\n{got_stderr}"
    )


def list_cassettes(directory: Path) -> list[Path]:
    """Return sorted list of `*.yaml` files under *directory* (non-recursive)."""
    return sorted(directory.glob("*.yaml"))
