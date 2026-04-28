"""sandbox_main bootstrap with empty seed — proves wiring resolves."""

from __future__ import annotations

import os
from unittest.mock import patch

from mockworld import sandbox_main


def test_load_seed_returns_empty_when_no_path() -> None:
    with (
        patch.object(sandbox_main.sys, "argv", ["sandbox_main"]),
        patch.dict(os.environ, {}, clear=False),
    ):
        # Clear the env var if set
        os.environ.pop("HYDRAFLOW_MOCKWORLD_SEED", None)
        seed = sandbox_main._load_seed()
    assert seed.issues == []
    assert seed.prs == []


def test_load_seed_reads_file_path_from_argv(tmp_path) -> None:
    seed_path = tmp_path / "scenario.json"
    seed_path.write_text(
        '{"repos": [], "issues": [{"number": 1, "title": "t", "body": "b", "labels": []}],'
        ' "prs": [], "scripts": {}, "cycles_to_run": 4, "loops_enabled": null}'
    )
    with patch.object(sandbox_main.sys, "argv", ["sandbox_main", str(seed_path)]):
        seed = sandbox_main._load_seed()
    assert len(seed.issues) == 1
    assert seed.issues[0]["number"] == 1
