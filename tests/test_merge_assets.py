"""Tests for scripts/merge_assets.py — namespace-aware asset merge."""

import json
import os
import sys
from pathlib import Path

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merge_assets import (
    chain_hooks,
    clean_assets,
    copy_namespaced_files,
    load_manifest,
    merge_assets,
    merge_settings_file,
    save_manifest,
)

# ---------------------------------------------------------------------------
# load_manifest / save_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_returns_empty_when_file_missing(self, tmp_path):
        result = load_manifest(tmp_path / "nonexistent.json")
        assert result == {"files": []}

    def test_loads_existing_manifest(self, tmp_path):
        manifest_path = tmp_path / "assets.json"
        data = {"version": 1, "files": [".claude/commands/hf.issue.md"]}
        manifest_path.write_text(json.dumps(data))
        result = load_manifest(manifest_path)
        assert result["files"] == [".claude/commands/hf.issue.md"]


class TestSaveManifest:
    def test_creates_parent_dirs(self, tmp_path):
        manifest_path = tmp_path / "nested" / "dir" / "assets.json"
        save_manifest(manifest_path, [".claude/commands/hf.issue.md"])
        assert manifest_path.exists()

    def test_round_trip(self, tmp_path):
        manifest_path = tmp_path / "assets.json"
        files = [".claude/hooks/hf.block.sh", ".claude/commands/hf.adr.md"]
        save_manifest(manifest_path, files)
        data = json.loads(manifest_path.read_text())
        assert data["version"] == 1
        assert "installed_at" in data
        # Files should be sorted
        assert data["files"] == sorted(files)

    def test_overwrites_existing(self, tmp_path):
        manifest_path = tmp_path / "assets.json"
        save_manifest(manifest_path, ["a"])
        save_manifest(manifest_path, ["b"])
        data = json.loads(manifest_path.read_text())
        assert data["files"] == ["b"]


# ---------------------------------------------------------------------------
# copy_namespaced_files
# ---------------------------------------------------------------------------


class TestCopyNamespacedFiles:
    def test_copies_only_hf_prefixed_files(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.adr.md").write_text("adr")
        (source / ".claude" / "commands" / "hf.issue.md").write_text("issue")
        (source / ".claude" / "commands" / "user-cmd.md").write_text("user")

        result = copy_namespaced_files(source, target, ".claude/commands", "hf.")
        assert sorted(result) == [
            ".claude/commands/hf.adr.md",
            ".claude/commands/hf.issue.md",
        ]
        assert (target / ".claude" / "commands" / "hf.adr.md").read_text() == "adr"
        assert (target / ".claude" / "commands" / "hf.issue.md").read_text() == "issue"
        # User file should NOT be copied
        assert not (target / ".claude" / "commands" / "user-cmd.md").exists()

    def test_preserves_existing_user_files(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.new.md").write_text("new")
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "my-custom.md").write_text("custom")

        copy_namespaced_files(source, target, ".claude/commands", "hf.")
        assert (
            target / ".claude" / "commands" / "my-custom.md"
        ).read_text() == "custom"
        assert (target / ".claude" / "commands" / "hf.new.md").read_text() == "new"

    def test_creates_target_subdirs(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / ".claude" / "hooks").mkdir(parents=True)
        (source / ".claude" / "hooks" / "hf.block.sh").write_text("block")

        copy_namespaced_files(source, target, ".claude/hooks", "hf.")
        assert (target / ".claude" / "hooks" / "hf.block.sh").exists()

    def test_returns_empty_when_source_dir_missing(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        result = copy_namespaced_files(source, target, ".claude/commands", "hf.")
        assert result == []


class TestCopyNamespacedFilesCodexSkills:
    """Codex skills are directories, not individual files."""

    def test_copies_hf_prefixed_directories(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        # HF skill directory
        (source / ".codex" / "skills" / "hf.adr").mkdir(parents=True)
        (source / ".codex" / "skills" / "hf.adr" / "SKILL.md").write_text("adr skill")
        (source / ".codex" / "skills" / "hf.adr" / "config.json").write_text("{}")
        # User skill directory
        (source / ".codex" / "skills" / "user-skill").mkdir(parents=True)
        (source / ".codex" / "skills" / "user-skill" / "SKILL.md").write_text("user")

        result = copy_namespaced_files(source, target, ".codex/skills", "hf.")
        assert ".codex/skills/hf.adr" in result
        assert (
            target / ".codex" / "skills" / "hf.adr" / "SKILL.md"
        ).read_text() == "adr skill"
        assert (
            target / ".codex" / "skills" / "hf.adr" / "config.json"
        ).read_text() == "{}"
        # User skill NOT copied
        assert not (target / ".codex" / "skills" / "user-skill").exists()

    def test_preserves_existing_user_skill_dirs(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / ".codex" / "skills" / "hf.test").mkdir(parents=True)
        (source / ".codex" / "skills" / "hf.test" / "SKILL.md").write_text("test")
        (target / ".codex" / "skills" / "custom-skill").mkdir(parents=True)
        (target / ".codex" / "skills" / "custom-skill" / "README.md").write_text("mine")

        copy_namespaced_files(source, target, ".codex/skills", "hf.")
        assert (
            target / ".codex" / "skills" / "custom-skill" / "README.md"
        ).read_text() == "mine"


# ---------------------------------------------------------------------------
# chain_hooks
# ---------------------------------------------------------------------------


class TestChainHooks:
    def test_creates_dispatcher_when_no_existing_hook(self, tmp_path):
        source = tmp_path / "source" / ".githooks"
        target = tmp_path / "target" / ".githooks"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\necho hf\n")
        os.chmod(source / "pre-commit", 0o755)

        result = chain_hooks(source, target)
        assert ".githooks/hf-pre-commit" in result
        assert ".githooks/pre-commit" in result

        hf_hook = target / "hf-pre-commit"
        assert hf_hook.exists()
        assert hf_hook.read_text() == "#!/bin/bash\necho hf\n"
        assert os.access(hf_hook, os.X_OK)

        dispatcher = target / "pre-commit"
        content = dispatcher.read_text()
        assert "hf-pre-commit" in content
        assert os.access(dispatcher, os.X_OK)

    def test_appends_chain_to_existing_hook(self, tmp_path):
        source = tmp_path / "source" / ".githooks"
        target = tmp_path / "target" / ".githooks"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\necho hf\n")
        (target / "pre-commit").write_text("#!/bin/bash\necho user hook\n")
        os.chmod(target / "pre-commit", 0o755)

        chain_hooks(source, target)
        content = (target / "pre-commit").read_text()
        assert "echo user hook" in content
        assert "# --- HydraFlow hook chain (do not edit) ---" in content
        assert "hf-pre-commit" in content
        assert "# --- End HydraFlow hook chain ---" in content

    def test_idempotent_chain_no_double_append(self, tmp_path):
        source = tmp_path / "source" / ".githooks"
        target = tmp_path / "target" / ".githooks"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\necho hf\n")
        (target / "pre-commit").write_text("#!/bin/bash\necho user\n")

        chain_hooks(source, target)
        first_content = (target / "pre-commit").read_text()
        chain_hooks(source, target)
        second_content = (target / "pre-commit").read_text()
        assert first_content == second_content

    def test_multiple_hooks(self, tmp_path):
        source = tmp_path / "source" / ".githooks"
        target = tmp_path / "target" / ".githooks"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\necho pc\n")
        (source / "pre-push").write_text("#!/bin/bash\necho pp\n")

        result = chain_hooks(source, target)
        assert ".githooks/hf-pre-commit" in result
        assert ".githooks/hf-pre-push" in result


# ---------------------------------------------------------------------------
# merge_settings_file
# ---------------------------------------------------------------------------


class TestMergeSettingsFile:
    def test_creates_when_target_missing(self, tmp_path):
        source_path = tmp_path / "source" / "settings.json"
        target_path = tmp_path / "target" / "settings.json"
        source_path.parent.mkdir(parents=True)
        target_path.parent.mkdir(parents=True)
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "hf.block.sh",
                                "_hydraflow": True,
                            }
                        ],
                    }
                ]
            }
        }
        source_path.write_text(json.dumps(settings))

        merge_settings_file(source_path, target_path)
        result = json.loads(target_path.read_text())
        assert len(result["hooks"]["PreToolUse"]) == 1

    def test_merges_into_existing_settings(self, tmp_path):
        source_path = tmp_path / "source" / "settings.json"
        target_path = tmp_path / "target" / "settings.json"
        source_path.parent.mkdir(parents=True)
        target_path.parent.mkdir(parents=True)

        source_settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "hf.block.sh",
                                "_hydraflow": True,
                            }
                        ],
                    }
                ]
            },
            "permissions": {"allow": ["hf-pattern"]},
        }
        target_settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "user-hook.sh"}],
                    }
                ]
            },
            "permissions": {"allow": ["user-pattern"], "deny": ["bad-thing"]},
        }
        source_path.write_text(json.dumps(source_settings))
        target_path.write_text(json.dumps(target_settings))

        merge_settings_file(source_path, target_path)
        result = json.loads(target_path.read_text())

        # Should have both matchers or merged hooks for Bash
        bash_entries = [
            e for e in result["hooks"]["PreToolUse"] if e["matcher"] == "Bash"
        ]
        assert len(bash_entries) >= 1
        # User hook should be preserved
        all_commands = []
        for entry in bash_entries:
            for hook in entry["hooks"]:
                all_commands.append(hook["command"])
        assert "user-hook.sh" in all_commands
        assert "hf.block.sh" in all_commands

        # Permissions merged
        assert "user-pattern" in result["permissions"]["allow"]
        assert "hf-pattern" in result["permissions"]["allow"]
        assert "bad-thing" in result["permissions"]["deny"]

    def test_updates_existing_hf_entries(self, tmp_path):
        """When HydraFlow entries already exist, they should be replaced (not duplicated)."""
        source_path = tmp_path / "source" / "settings.json"
        target_path = tmp_path / "target" / "settings.json"
        source_path.parent.mkdir(parents=True)
        target_path.parent.mkdir(parents=True)

        hf_hook = {
            "type": "command",
            "command": "hf.block-v2.sh",
            "_hydraflow": True,
        }
        old_hf_hook = {
            "type": "command",
            "command": "hf.block.sh",
            "_hydraflow": True,
        }
        source_settings = {
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [hf_hook]}]}
        }
        target_settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "user.sh"},
                            old_hf_hook,
                        ],
                    }
                ]
            }
        }
        source_path.write_text(json.dumps(source_settings))
        target_path.write_text(json.dumps(target_settings))

        merge_settings_file(source_path, target_path)
        result = json.loads(target_path.read_text())

        bash_entry = [
            e for e in result["hooks"]["PreToolUse"] if e["matcher"] == "Bash"
        ][0]
        commands = [h["command"] for h in bash_entry["hooks"]]
        assert "user.sh" in commands
        assert "hf.block-v2.sh" in commands
        # Old HF hook should be removed
        assert "hf.block.sh" not in commands


# ---------------------------------------------------------------------------
# merge_assets (full integration)
# ---------------------------------------------------------------------------


class TestMergeAssets:
    def _setup_source(self, source):
        """Create a minimal source tree."""
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.adr.md").write_text("adr cmd")
        (source / ".claude" / "hooks").mkdir(parents=True)
        (source / ".claude" / "hooks" / "hf.block.sh").write_text("block")
        (source / ".claude" / "agents").mkdir(parents=True)
        (source / ".claude" / "agents" / "hf.quality.md").write_text("quality")
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "hf.block.sh",
                                "_hydraflow": True,
                            }
                        ],
                    }
                ]
            }
        }
        (source / ".claude" / "settings.json").write_text(json.dumps(settings))
        (source / ".codex" / "skills" / "hf.adr").mkdir(parents=True)
        (source / ".codex" / "skills" / "hf.adr" / "SKILL.md").write_text("skill")
        (source / ".pi" / "skills").mkdir(parents=True)
        (source / ".pi" / "skills" / "hf-adr.md").write_text("pi skill")
        (source / ".githooks").mkdir(parents=True)
        (source / ".githooks" / "pre-commit").write_text("#!/bin/bash\necho hf\n")

    def test_merge_into_empty_target(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        self._setup_source(source)

        merge_assets(source, target)

        assert (target / ".claude" / "commands" / "hf.adr.md").exists()
        assert (target / ".claude" / "hooks" / "hf.block.sh").exists()
        assert (target / ".claude" / "agents" / "hf.quality.md").exists()
        assert (target / ".codex" / "skills" / "hf.adr" / "SKILL.md").exists()
        assert (target / ".pi" / "skills" / "hf-adr.md").exists()
        assert (target / ".githooks" / "hf-pre-commit").exists()
        assert (target / ".claude" / "settings.json").exists()

        manifest = json.loads((target / ".hydraflow" / "assets.json").read_text())
        assert len(manifest["files"]) > 0

    def test_merge_preserves_user_files(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        self._setup_source(source)

        # User files in target
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "my-custom.md").write_text("mine")
        (target / ".codex" / "skills" / "my-skill").mkdir(parents=True)
        (target / ".codex" / "skills" / "my-skill" / "SKILL.md").write_text("mine")
        (target / ".githooks").mkdir(parents=True)
        (target / ".githooks" / "pre-commit").write_text("#!/bin/bash\necho user\n")
        os.chmod(target / ".githooks" / "pre-commit", 0o755)

        merge_assets(source, target)

        assert (target / ".claude" / "commands" / "my-custom.md").read_text() == "mine"
        assert (
            target / ".codex" / "skills" / "my-skill" / "SKILL.md"
        ).read_text() == "mine"
        # User hook should still contain user content
        pre_commit = (target / ".githooks" / "pre-commit").read_text()
        assert "echo user" in pre_commit

    def test_second_merge_cleans_old_manifest(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        self._setup_source(source)

        merge_assets(source, target)

        # Now remove a file from source and re-merge
        (source / ".claude" / "agents" / "hf.quality.md").unlink()
        merge_assets(source, target)

        # Old file should be removed
        assert not (target / ".claude" / "agents" / "hf.quality.md").exists()


# ---------------------------------------------------------------------------
# clean_assets
# ---------------------------------------------------------------------------


class TestCleanAssets:
    def test_removes_managed_files_preserves_user(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Setup source and merge
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.adr.md").write_text("adr")
        (source / ".githooks").mkdir(parents=True)
        (source / ".githooks" / "pre-commit").write_text("#!/bin/bash\necho hf\n")
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "hf.block.sh",
                                "_hydraflow": True,
                            }
                        ],
                    }
                ]
            }
        }
        (source / ".claude" / "settings.json").write_text(json.dumps(settings))

        # Add user files in target
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "my-cmd.md").write_text("user")

        merge_assets(source, target)
        assert (target / ".claude" / "commands" / "hf.adr.md").exists()

        clean_assets(target)

        # HF file removed
        assert not (target / ".claude" / "commands" / "hf.adr.md").exists()
        # User file preserved
        assert (target / ".claude" / "commands" / "my-cmd.md").read_text() == "user"
        # Manifest removed
        assert not (target / ".hydraflow" / "assets.json").exists()

    def test_clean_removes_hook_chains(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / ".githooks").mkdir(parents=True)
        (source / ".githooks" / "pre-commit").write_text("#!/bin/bash\necho hf\n")
        (target / ".githooks").mkdir(parents=True)
        (target / ".githooks" / "pre-commit").write_text("#!/bin/bash\necho user\n")
        os.chmod(target / ".githooks" / "pre-commit", 0o755)

        # Need a minimal source for merge_assets
        (source / ".claude" / "settings.json").parent.mkdir(parents=True)
        (source / ".claude" / "settings.json").write_text("{}")

        merge_assets(source, target)
        content = (target / ".githooks" / "pre-commit").read_text()
        assert "HydraFlow hook chain" in content

        clean_assets(target)
        if (target / ".githooks" / "pre-commit").exists():
            content = (target / ".githooks" / "pre-commit").read_text()
            assert "HydraFlow hook chain" not in content

    def test_clean_noop_when_no_manifest(self, tmp_path):
        """clean_assets should be safe to call when nothing was ever installed."""
        target = tmp_path / "target"
        target.mkdir()
        clean_assets(target)  # Should not raise
