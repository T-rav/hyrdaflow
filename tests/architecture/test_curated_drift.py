"""Drift guard run on a developer machine before push.

Mirrors what `arch-regen.yml` (Plan C) will invoke as
`python -m arch.runner --check`. Skips until the baseline is committed.
"""

from pathlib import Path

import pytest

from arch.runner import check


def test_curated_generated_is_in_sync_with_source(real_repo_root: Path):
    generated = real_repo_root / "docs/arch/generated"
    if not generated.exists():
        pytest.skip(
            "docs/arch/generated/ not yet committed (run `make arch-regen` and commit)"
        )
    rc = check(repo_root=real_repo_root, generated_dir=generated)
    if rc != 0:
        pytest.fail(
            "docs/arch/generated/ is stale relative to source. "
            "Run `make arch-regen` and recommit the changes."
        )
