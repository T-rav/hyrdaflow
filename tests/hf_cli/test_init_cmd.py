from __future__ import annotations

import tarfile
from pathlib import Path

from hf_cli import init_cmd


def _write_asset_tree(root: Path) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".githooks").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text('{"ok": true}')
    (root / ".codex" / "README.md").write_text("codex")
    (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\necho ok\n")


def test_run_init_falls_back_to_source_tree_when_archive_missing(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    _write_asset_tree(repo_root)
    target = tmp_path / "target"
    target.mkdir()

    # Make init_cmd resolve repo root from our temp tree.
    fake_module_path = repo_root / "hf_cli" / "init_cmd.py"
    fake_module_path.parent.mkdir(parents=True, exist_ok=True)
    fake_module_path.write_text("# marker")
    monkeypatch.setattr(init_cmd, "__file__", str(fake_module_path))

    # resources.files(...)/assets.tar.gz should resolve to a missing file.
    pkg_dir = tmp_path / "pkg" / "hf_cli"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(init_cmd.resources, "files", lambda _pkg: pkg_dir)

    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    assert (target / ".claude" / "settings.json").exists()
    assert (target / ".codex" / "README.md").exists()
    assert (target / ".githooks" / "pre-commit").exists()
    assert ".hydraflow/prep" in (target / ".gitignore").read_text()


def test_run_init_prefers_archive_when_available(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    _write_asset_tree(repo_root)
    target = tmp_path / "target"
    target.mkdir()

    fake_module_path = repo_root / "hf_cli" / "init_cmd.py"
    fake_module_path.parent.mkdir(parents=True, exist_ok=True)
    fake_module_path.write_text("# marker")
    monkeypatch.setattr(init_cmd, "__file__", str(fake_module_path))

    # Build a package-like dir containing only assets.tar.gz.
    pkg_dir = tmp_path / "pkg" / "hf_cli"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    archive = pkg_dir / "assets.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        archive_src = tmp_path / "archive_src"
        (archive_src / ".claude").mkdir(parents=True, exist_ok=True)
        (archive_src / ".claude" / "settings.json").write_text('{"from":"archive"}')
        tar.add(
            archive_src / ".claude" / "settings.json",
            arcname=".claude/settings.json",
        )

    monkeypatch.setattr(init_cmd.resources, "files", lambda _pkg: pkg_dir)

    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    # Archive source should win when available.
    assert (target / ".claude" / "settings.json").read_text() == '{"from":"archive"}'
