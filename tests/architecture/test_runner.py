import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def populated_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src/widget_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class WidgetLoop(BaseBackgroundLoop):\n"
        "    pass\n"
    )
    (repo / "tests/scenarios/fakes").mkdir(parents=True)
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "docs/adr/0001-thing.md").write_text("# ADR-0001\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "add",
            ".",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_emit_writes_all_nine_artifacts(populated_repo: Path):
    fa_path = populated_repo / "docs/arch/functional_areas.yml"
    fa_path.parent.mkdir(parents=True, exist_ok=True)
    fa_path.write_text(
        "areas:\n  orchestration:\n    label: Orchestration\n    description: x\n"
    )
    from arch.runner import emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    expected = {
        "loops.md",
        "ports.md",
        "labels.md",
        "modules.md",
        "events.md",
        "adr_xref.md",
        "mockworld.md",
        "changelog.md",
        "functional_areas.md",
    }
    assert {p.name for p in out.iterdir() if p.suffix == ".md"} == expected
    assert (out.parent / ".meta.json").exists()


def test_check_returns_zero_when_in_sync(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 0


def test_check_returns_one_when_drifted(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    # Add a new loop AFTER baseline emit
    (populated_repo / "src/widget2_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class Widget2Loop(BaseBackgroundLoop):\n    pass\n"
    )
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 1
