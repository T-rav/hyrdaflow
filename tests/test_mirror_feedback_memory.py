"""Tests for `scripts/mirror_feedback_memory.py`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "mirror_feedback_memory.py"


def _load_module():
    """Import the script as a module without invoking its CLI."""
    spec = importlib.util.spec_from_file_location("mirror_feedback_memory", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mirror_feedback_memory"] = mod
    spec.loader.exec_module(mod)
    return mod


mfm = _load_module()


def _write_memory(
    dir_: Path,
    slug: str,
    *,
    name: str = "Test rule",
    description: str = "test desc",
    body: str = "Rule prose.\n\n**Why:** because.\n\n**How to apply:** do X.\n",
    extra_front: dict[str, str] | None = None,
) -> Path:
    front = {
        "name": name,
        "description": description,
        "type": "feedback",
    }
    if extra_front:
        front.update(extra_front)
    front_yaml = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    p = dir_ / f"feedback_{slug}.md"
    p.write_text(f"---\n{front_yaml}\n---\n\n{body}")
    return p


def test_mirror_one_writes_redacted_file(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    src = _write_memory(memory_dir, "alpha", name="Alpha rule")
    target = mfm.mirror_one(src, repo_root)

    assert (
        target == repo_root / "docs" / "wiki" / "memory-feedback" / "feedback-alpha.md"
    )
    assert target.exists()
    text = target.read_text()
    assert text.startswith("---\n")
    assert "Alpha rule" in text
    assert "Rule prose." in text
    assert "**Why:** because." in text


def test_mirror_strips_origin_session_id(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    src = _write_memory(
        memory_dir,
        "beta",
        extra_front={"originSessionId": "secret-uuid-do-not-leak"},
    )
    target = mfm.mirror_one(src, repo_root)

    assert "originSessionId" not in target.read_text()
    assert "secret-uuid" not in target.read_text()


def test_mirror_replaces_home_paths(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    home = str(Path.home())
    body_with_home = f"Rule.\n\n**Why:** see {home}/some/path/file.md\n"
    src = _write_memory(memory_dir, "gamma", body=body_with_home)
    target = mfm.mirror_one(src, repo_root)

    text = target.read_text()
    assert home not in text
    assert "~/some/path/file.md" in text


def test_mirror_redacts_non_allowlisted_emails(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    body = (
        "See feedback from user@gmail.com (private) and bot@anthropic.com (allowed)\n"
        "and noreply@hydraflow.local (allowed) and stranger@evil.example.org (private).\n"
    )
    src = _write_memory(memory_dir, "delta", body=body)
    target = mfm.mirror_one(src, repo_root)

    text = target.read_text()
    assert "user@gmail.com" not in text
    assert "stranger@evil.example.org" not in text
    assert "<email>" in text
    assert "bot@anthropic.com" in text
    assert "noreply@hydraflow.local" in text


def test_mirror_idempotent(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    src = _write_memory(memory_dir, "epsilon")
    first = mfm.mirror_one(src, repo_root).read_text()
    second = mfm.mirror_one(src, repo_root).read_text()
    assert first == second


def test_mirror_frontmatter_has_required_fields(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    src = _write_memory(memory_dir, "zeta", name="Zeta rule", description="zeta desc")
    target = mfm.mirror_one(src, repo_root)

    text = target.read_text()
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert front["source"] == "feedback_zeta.md"
    assert front["name"] == "Zeta rule"
    assert front["description"] == "zeta desc"
    assert front["status"] == "pending"
    assert front["issue"] is None
    assert front["promoted_in"] is None
    assert front["wontfix_reason"] is None
    assert "created" in front


def test_lenient_frontmatter_handles_backtick_value(tmp_path: Path) -> None:
    """Source memories occasionally have values starting with backticks (YAML rejects)."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    src = memory_dir / "feedback_backtick.md"
    src.write_text(
        "---\n"
        "name: Auto-merge not enabled\n"
        "description: `gh pr merge --auto` returns an error on this repo\n"
        "type: feedback\n"
        "---\n\n"
        "Rule body.\n"
    )

    target = mfm.mirror_one(src, repo_root)
    text = target.read_text()
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert "auto" in front["description"].lower()


def test_main_skips_non_feedback_files(tmp_path: Path) -> None:
    """The hook fires on every Write — non-feedback files must exit cleanly."""
    not_a_memory = tmp_path / "random_note.md"
    not_a_memory.write_text("# random\n")

    rc = mfm.main(["mirror_feedback_memory.py", str(not_a_memory)])
    assert rc == 0
    # Should NOT have written anything anywhere.
    assert not (tmp_path / "docs").exists()


def test_main_handles_missing_file(tmp_path: Path, capsys) -> None:
    """Missing path → non-zero exit, stderr message; never crash."""
    rc = mfm.main(["mirror_feedback_memory.py", str(tmp_path / "nope.md")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_slug_from_filename() -> None:
    assert (
        mfm.slug_from_filename("feedback_subagent_batch_size.md")
        == "feedback-subagent-batch-size"
    )
    assert mfm.slug_from_filename("feedback_x.md") == "feedback-x"


def test_render_mirror_is_a_function(tmp_path: Path) -> None:
    """`render_mirror` should be callable as a pure function returning text."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    src = _write_memory(memory_dir, "eta")
    rendered = mfm.render_mirror(src)
    assert isinstance(rendered, str)
    assert rendered.startswith("---\n")
    assert rendered.endswith("\n")


@pytest.mark.parametrize("home_var", [str(Path.home()), str(Path.home()) + "/"])
def test_redact_handles_home_with_trailing_slash(home_var: str) -> None:
    body = f"see {home_var}foo/bar.md"
    out = mfm.redact(body)
    assert str(Path.home()) not in out
