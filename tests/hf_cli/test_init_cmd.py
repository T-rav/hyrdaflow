from __future__ import annotations

import base64
import tarfile
from pathlib import Path

from hf_cli import embedded_assets, init_cmd


def _write_asset_tree(root: Path) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".pi").mkdir(parents=True, exist_ok=True)
    (root / ".githooks").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text('{"ok": true}')
    (root / ".codex" / "README.md").write_text("codex")
    (root / ".pi" / "README.md").write_text("pi")
    (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\necho ok\n")


def _clear_embedded(monkeypatch) -> None:
    monkeypatch.setattr(embedded_assets, "ASSET_ARCHIVE_B64", "", raising=False)


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

    _clear_embedded(monkeypatch)
    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    assert (target / ".claude" / "settings.json").exists()
    assert (target / ".codex" / "README.md").exists()
    assert (target / ".pi" / "README.md").exists()
    assert (target / ".githooks" / "pre-commit").exists()
    assert ".hydraflow/prep" in (target / ".gitignore").read_text()


def test_run_init_prefers_embedded_archive_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    _write_asset_tree(repo_root)
    target = tmp_path / "target"
    target.mkdir()

    fake_module_path = repo_root / "hf_cli" / "init_cmd.py"
    fake_module_path.parent.mkdir(parents=True, exist_ok=True)
    fake_module_path.write_text("# marker")
    monkeypatch.setattr(init_cmd, "__file__", str(fake_module_path))

    archive = tmp_path / "embedded.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        archive_src = tmp_path / "archive_src"
        (archive_src / ".claude").mkdir(parents=True, exist_ok=True)
        (archive_src / ".claude" / "settings.json").write_text('{"from":"archive"}')
        tar.add(
            archive_src / ".claude" / "settings.json",
            arcname=".claude/settings.json",
        )

    monkeypatch.setattr(
        embedded_assets,
        "ASSET_ARCHIVE_B64",
        base64.b64encode(archive.read_bytes()).decode(),
        raising=False,
    )

    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    # Archive source should win when available.
    assert (target / ".claude" / "settings.json").read_text() == '{"from":"archive"}'


def test_run_init_uses_embedded_archive(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()
    data_root = tmp_path / "embedded-src"
    _write_asset_tree(data_root)
    archive = tmp_path / "embedded.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(
            data_root / ".codex" / "README.md",
            arcname=".codex/README.md",
        )
    monkeypatch.setattr(
        embedded_assets,
        "ASSET_ARCHIVE_B64",
        base64.b64encode(archive.read_bytes()).decode(),
        raising=False,
    )
    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    assert (target / ".codex" / "README.md").exists()


def test_run_init_embedded_archive_blocks_path_traversal(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "pwned.txt"

    archive = tmp_path / "embedded-bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        good_src = tmp_path / "good.txt"
        good_src.write_text("ok")
        bad_src = tmp_path / "bad.txt"
        bad_src.write_text("bad")
        tar.add(good_src, arcname=".codex/README.md")
        tar.add(bad_src, arcname="../../pwned.txt")

    monkeypatch.setattr(
        embedded_assets,
        "ASSET_ARCHIVE_B64",
        base64.b64encode(archive.read_bytes()).decode(),
        raising=False,
    )

    rc = init_cmd.run_init(["--target", str(target)])
    assert rc == 0
    assert (target / ".codex" / "README.md").read_text() == "ok"
    assert not outside.exists()
