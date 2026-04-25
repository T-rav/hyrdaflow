"""Drift guard: ADR-0002's Mermaid state diagram vs the generated labels.md.

Currently xfail: HydraFlow has no canonical TRANSITIONS constant in src/
(transitions are scattered across imperative `swap_pipeline_labels()`
calls), and ADR-0002 has no Mermaid block to compare against. Per Plan A
Task 22 step 4 escape hatch, this test is marked xfail with a follow-up
to introduce a declarative transition table and a Mermaid diagram in
ADR-0002. Track in hydraflow-find issues.
"""

import re
from pathlib import Path

import pytest

_MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_EDGE_RE = re.compile(r"^\s*([\w-]+)\s*-->\s*([\w-]+)(?:\s*:\s*(.+))?$", re.MULTILINE)


def _edges(mermaid_text: str) -> set[tuple[str, str]]:
    return {
        (m.group(1).replace("_", "-"), m.group(2).replace("_", "-"))
        for m in _EDGE_RE.finditer(mermaid_text)
    }


def _first_mermaid_block(md_text: str) -> str:
    m = _MERMAID_BLOCK.search(md_text)
    if not m:
        return ""
    return m.group(1)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Plan A escape hatch: HydraFlow has no canonical TRANSITIONS in src/ and "
        "ADR-0002 has no Mermaid stateDiagram-v2 block. Plan B will introduce "
        "a declarative transition table; remove this xfail once both ends are "
        "live and the diagrams match."
    ),
)
def test_label_state_matches_adr0002(real_repo_root: Path):
    adr_path = real_repo_root / "docs/adr/0002-labels-as-state-machine.md"
    gen_path = real_repo_root / "docs/arch/generated/labels.md"
    if not gen_path.exists():
        pytest.skip(
            "docs/arch/generated/labels.md not yet emitted; run `make arch-regen`"
        )

    adr_block = _first_mermaid_block(adr_path.read_text())
    gen_block = _first_mermaid_block(gen_path.read_text())
    if not gen_block:
        pytest.fail(
            "labels extractor returned no transitions. "
            "Either the canonical transition declaration in src/ has a form the "
            "extractor doesn't handle (extend src/arch/extractors/labels.py), "
            "or the labels page is genuinely empty. "
            "Run `python -m arch.runner --emit` and inspect docs/arch/generated/labels.md."
        )
    if not adr_block:
        pytest.fail("ADR-0002 has no Mermaid block — add one.")

    adr_edges = _edges(adr_block)
    gen_edges = _edges(gen_block)
    missing = adr_edges - gen_edges
    extra = gen_edges - adr_edges
    if missing or extra:
        msg = []
        if missing:
            msg.append(f"In ADR-0002 but not in code: {sorted(missing)}")
        if extra:
            msg.append(f"In code but not in ADR-0002: {sorted(extra)}")
        pytest.fail(
            "Label state machine drift between code and ADR-0002:\n  "
            + "\n  ".join(msg)
            + "\n\nFix: update either the source transition table or ADR-0002."
        )
