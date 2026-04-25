"""Drift guard: ADR-0001's "five concurrent" framing vs the live loop count.

Marked xfail until Plan B amends ADR-0001 to either reference the live
loop registry (docs/arch/generated/loops.md) or historicize the original
"five" claim. Once the amendment lands, remove the xfail decorator.
"""

from pathlib import Path

import pytest

from arch.extractors.loops import extract_loops


@pytest.mark.xfail(
    reason="ADR-0001 is amended in Plan B; remove this xfail once the amendment lands.",
    strict=False,
)
def test_loop_count_matches_adr0001(real_repo_root: Path):
    adr = (real_repo_root / "docs/adr/0001-five-concurrent-async-loops.md").read_text()
    if "see `docs/arch/generated/loops.md`" in adr:
        return  # ADR has been updated to reference the live registry
    if "Background" in adr and "historical" in adr:
        return  # ADR has been historicized
    live_loops = extract_loops(real_repo_root / "src")
    pytest.fail(
        f"ADR-0001 still references its original framing but {len(live_loops)} loops exist. "
        "Plan B should amend ADR-0001 to either reference docs/arch/generated/loops.md "
        "or historicize the original claim with a 'Background' section."
    )
