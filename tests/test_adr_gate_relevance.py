"""Fix for Minor #7 from end-of-batch review.

P2's gate passed a PR when ANY ADR file was touched. Loophole: a PR
touching src/repo_wiki.py (cited only by ADR-0032) could clear the
gate by adding a sentence to unrelated ADR-0001.

Fix: the gate now resolves hits per-file — each touched ADR'd file
must have at least one of its citing ADRs modified in the diff.
Tested against the pure ``evaluate_gate`` function.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_adr_touchpoints import evaluate_gate  # noqa: E402

from adr_index import ADR  # noqa: E402


def _adr(number: int) -> ADR:
    return ADR(
        number=number,
        title=f"Fixture {number}",
        status="Accepted",
        summary="",
        source_files=frozenset(),
    )


def test_gate_passes_when_no_hits() -> None:
    assert evaluate_gate(changed=["README.md"], hits={}) == (True, {})


def test_gate_fails_when_touched_adr_is_unrelated() -> None:
    """Touching ADR-0001 does NOT clear a hit on ADR-0032."""
    adr_32 = _adr(32)
    hits = {"src/repo_wiki.py": [adr_32]}
    changed = ["src/repo_wiki.py", "docs/adr/0001-unrelated.md"]

    passed, unresolved = evaluate_gate(changed, hits)

    assert not passed
    assert "src/repo_wiki.py" in unresolved


def test_gate_passes_when_touched_adr_is_the_citing_one() -> None:
    adr_32 = _adr(32)
    hits = {"src/repo_wiki.py": [adr_32]}
    changed = ["src/repo_wiki.py", "docs/adr/0032-per-repo-wiki.md"]

    passed, unresolved = evaluate_gate(changed, hits)

    assert passed
    assert unresolved == {}


def test_gate_partial_resolution_fails() -> None:
    """A PR touching one citing ADR doesn't clear a separate file's hit."""
    adr_32 = _adr(32)
    adr_21 = _adr(21)
    hits = {
        "src/repo_wiki.py": [adr_32],  # fired by ADR-0032
        "src/state.py": [adr_21],  # fired by ADR-0021
    }
    # Author updated ADR-0032 but forgot ADR-0021
    changed = [
        "src/repo_wiki.py",
        "src/state.py",
        "docs/adr/0032-per-repo-wiki.md",
    ]

    passed, unresolved = evaluate_gate(changed, hits)

    assert not passed
    assert "src/state.py" in unresolved
    assert "src/repo_wiki.py" not in unresolved


def test_gate_multi_adr_per_file_either_suffices() -> None:
    """When a file is cited by multiple ADRs, touching any of them clears."""
    adr_32 = _adr(32)
    adr_21 = _adr(21)
    hits = {"src/repo_wiki.py": [adr_32, adr_21]}

    # Touch only ADR-0021
    changed = ["src/repo_wiki.py", "docs/adr/0021-persistence.md"]
    passed, unresolved = evaluate_gate(changed, hits)
    assert passed

    # Touch only ADR-0032
    changed = ["src/repo_wiki.py", "docs/adr/0032-per-repo-wiki.md"]
    passed, unresolved = evaluate_gate(changed, hits)
    assert passed
