"""Tests for agent_cli.py — CLI command builders for Claude, Codex, and Pi."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_cli import (
    build_agent_command,
    build_lightweight_command,
)


class TestBuildAgentCommand:
    """Tests for build_agent_command with various parameter combinations."""

    def test_claude_default_command_structure(self) -> None:
        """Claude command should include -p, --output-format, --model, --verbose, --permission-mode."""
        cmd = build_agent_command(tool="claude", model="sonnet")

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "stream-json"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "sonnet"
        assert "--verbose" in cmd
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"

    def test_codex_command_structure(self) -> None:
        """Codex command should include exec, --json, --model, --sandbox, etc."""
        cmd = build_agent_command(tool="codex", model="o4-mini")

        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "o4-mini"
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--skip-git-repo-check" in cmd

    def test_claude_with_disallowed_tools(self) -> None:
        """Claude command with disallowed_tools should include --disallowedTools flag."""
        cmd = build_agent_command(
            tool="claude", model="sonnet", disallowed_tools="Edit,Write"
        )

        assert "--disallowedTools" in cmd
        assert cmd[cmd.index("--disallowedTools") + 1] == "Edit,Write"

    def test_claude_with_max_turns(self) -> None:
        """Claude command with max_turns should include --max-turns flag."""
        cmd = build_agent_command(tool="claude", model="sonnet", max_turns=5)

        assert "--max-turns" in cmd
        assert cmd[cmd.index("--max-turns") + 1] == "5"

    def test_claude_with_both_optional_flags(self) -> None:
        """Both disallowed_tools and max_turns should produce both flags."""
        cmd = build_agent_command(
            tool="claude",
            model="opus",
            disallowed_tools="Bash",
            max_turns=10,
        )

        assert "--disallowedTools" in cmd
        assert cmd[cmd.index("--disallowedTools") + 1] == "Bash"
        assert "--max-turns" in cmd
        assert cmd[cmd.index("--max-turns") + 1] == "10"

    def test_claude_without_optional_flags(self) -> None:
        """Claude command with no optional params should omit --disallowedTools and --max-turns."""
        cmd = build_agent_command(tool="claude", model="haiku")

        assert "--disallowedTools" not in cmd
        assert "--max-turns" not in cmd

    def test_codex_ignores_disallowed_tools_and_max_turns(self) -> None:
        """Codex path returns a fixed array; disallowed_tools and max_turns are not applied."""
        cmd_plain = build_agent_command(tool="codex", model="o4-mini")
        cmd_with_opts = build_agent_command(
            tool="codex",
            model="o4-mini",
            disallowed_tools="Edit",
            max_turns=5,
        )

        assert cmd_plain == cmd_with_opts
        assert "--disallowedTools" not in cmd_with_opts
        assert "--max-turns" not in cmd_with_opts

    def test_pi_command_structure(self) -> None:
        """Pi command should run headless with JSON output and model selection."""
        cmd = build_agent_command(tool="pi", model="pi-max")

        assert cmd[0] == "pi"
        assert "-p" in cmd
        assert "--mode" in cmd
        assert cmd[cmd.index("--mode") + 1] == "json"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "pi-max"

    def test_pi_disallowed_tools_adds_system_guidance(self) -> None:
        """Pi receives disallowed-tools policy via appended system guidance."""
        cmd = build_agent_command(
            tool="pi",
            model="pi-max",
            disallowed_tools="Edit, Write",
        )

        assert "--append-system-prompt" in cmd
        prompts = [
            cmd[i + 1]
            for i, val in enumerate(cmd[:-1])
            if val == "--append-system-prompt"
        ]
        assert any(
            "Do not invoke these tools under any circumstances: Edit,Write" in p
            for p in prompts
        )
        assert "--disallowedTools" not in cmd

    def test_pi_max_turns_adds_stop_guidance(self) -> None:
        """Pi has no native --max-turns flag; we pass stop guidance via system prompt."""
        cmd = build_agent_command(tool="pi", model="pi-max", max_turns=3)

        assert "--append-system-prompt" in cmd
        guidance = cmd[cmd.index("--append-system-prompt") + 1]
        assert "at most 3 assistant turn(s)" in guidance
        assert "--max-turns" not in cmd

    def test_pi_combines_max_turns_and_disallowed_guidance(self) -> None:
        """Pi should include both max-turns and disallowed-tools guidance when set."""
        cmd = build_agent_command(
            tool="pi",
            model="pi-max",
            max_turns=3,
            disallowed_tools="Edit",
        )
        prompts = [
            cmd[i + 1]
            for i, val in enumerate(cmd[:-1])
            if val == "--append-system-prompt"
        ]
        assert any("at most 3 assistant turn(s)" in p for p in prompts)
        assert any("Do not invoke these tools" in p for p in prompts)

    def test_claude_max_turns_converted_to_string(self) -> None:
        """max_turns integer should be converted to a string in the command."""
        cmd = build_agent_command(tool="claude", model="sonnet", max_turns=42)

        idx = cmd.index("--max-turns")
        assert cmd[idx + 1] == "42"


class TestBuildLightweightCommand:
    """Tests for build_lightweight_command — simplified CLI builder for background workers."""

    def test_codex_includes_prompt_as_positional_arg(self) -> None:
        """Codex command should append the prompt as a positional argument."""
        cmd, cmd_input = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="summarize this"
        )

        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        assert cmd[cmd.index("--model") + 1] == "o4-mini"
        assert cmd[-1] == "summarize this"
        assert cmd_input is None

    def test_codex_includes_standard_flags(self) -> None:
        """Codex command should include sandbox and bypass flags."""
        cmd, _ = build_lightweight_command(tool="codex", model="o4-mini", prompt="test")

        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--skip-git-repo-check" in cmd

    def test_claude_uses_pipe_flag(self) -> None:
        """Claude command should use -p flag with prompt inline."""
        cmd, cmd_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt="explain this"
        )

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "explain this" in cmd
        assert cmd[cmd.index("--model") + 1] == "sonnet"
        assert cmd_input is None

    def test_other_tool_uses_pipe_flag(self) -> None:
        """Non-codex tools should use -p flag with the tool name as executable."""
        cmd, cmd_input = build_lightweight_command(
            tool="pi", model="pi-max", prompt="hello"
        )

        assert cmd[0] == "pi"
        assert "-p" in cmd
        assert "hello" in cmd
        assert cmd[cmd.index("--model") + 1] == "pi-max"
        assert cmd_input is None

    def test_input_always_none(self) -> None:
        """cmd_input should always be None for both codex and non-codex tools."""
        _, codex_input = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="test"
        )
        _, claude_input = build_lightweight_command(
            tool="claude", model="sonnet", prompt="test"
        )

        assert codex_input is None
        assert claude_input is None

    def test_codex_does_not_mutate_shared_state(self) -> None:
        """Calling build_lightweight_command twice should not share list references."""
        cmd1, _ = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="first"
        )
        cmd2, _ = build_lightweight_command(
            tool="codex", model="o4-mini", prompt="second"
        )

        assert cmd1[-1] == "first"
        assert cmd2[-1] == "second"
        assert cmd1 is not cmd2


class TestPluginDirFlags:
    """Tests for plugin directory injection into Claude commands."""

    def test_plugin_dir_flags_returns_empty_when_dirs_missing(self) -> None:
        """No flags when plugin directories don't exist on disk."""
        from unittest.mock import patch

        from agent_cli import _plugin_dir_flags

        with patch("agent_cli.Path.is_dir", return_value=False):
            assert _plugin_dir_flags() == []

    def test_plugin_dir_flags_includes_existing_dirs(self, tmp_path: Path) -> None:
        """Flags should include only directories that exist."""
        from unittest.mock import patch

        from agent_cli import _plugin_dir_flags

        fake_dir = str(tmp_path / "lightfactory")
        (tmp_path / "lightfactory").mkdir()

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (fake_dir,)):
            flags = _plugin_dir_flags()

        assert flags == ["--plugin-dir", fake_dir]

    def test_plugin_dir_flags_skips_missing_dirs(self, tmp_path: Path) -> None:
        """Directories that don't exist should be skipped."""
        from unittest.mock import patch

        from agent_cli import _plugin_dir_flags

        existing = str(tmp_path / "exists")
        (tmp_path / "exists").mkdir()
        missing = str(tmp_path / "missing")

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (existing, missing)):
            flags = _plugin_dir_flags()

        assert flags == ["--plugin-dir", existing]

    def test_claude_agent_command_includes_plugin_dirs(self, tmp_path: Path) -> None:
        """build_agent_command for claude should include --plugin-dir flags."""
        from unittest.mock import patch

        fake_dir = str(tmp_path / "superpowers")
        (tmp_path / "superpowers").mkdir()

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (fake_dir,)):
            cmd = build_agent_command(tool="claude", model="sonnet")

        assert "--plugin-dir" in cmd
        assert cmd[cmd.index("--plugin-dir") + 1] == fake_dir

    def test_codex_command_does_not_include_plugin_dirs(self, tmp_path: Path) -> None:
        """Codex commands should not include --plugin-dir flags."""
        from unittest.mock import patch

        fake_dir = str(tmp_path / "superpowers")
        (tmp_path / "superpowers").mkdir()

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (fake_dir,)):
            cmd = build_agent_command(tool="codex", model="o4-mini")

        assert "--plugin-dir" not in cmd

    def test_lightweight_claude_includes_plugin_dirs(self, tmp_path: Path) -> None:
        """build_lightweight_command for claude should include --plugin-dir flags."""
        from unittest.mock import patch

        fake_dir = str(tmp_path / "lightfactory")
        (tmp_path / "lightfactory").mkdir()

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (fake_dir,)):
            cmd, _ = build_lightweight_command(
                tool="claude", model="sonnet", prompt="test"
            )

        assert "--plugin-dir" in cmd
        assert cmd[cmd.index("--plugin-dir") + 1] == fake_dir

    def test_lightweight_pi_excludes_plugin_dirs(self, tmp_path: Path) -> None:
        """build_lightweight_command for pi should not include --plugin-dir flags."""
        from unittest.mock import patch

        fake_dir = str(tmp_path / "lightfactory")
        (tmp_path / "lightfactory").mkdir()

        with patch("agent_cli._DOCKER_PLUGIN_DIRS", (fake_dir,)):
            cmd, _ = build_lightweight_command(tool="pi", model="pi-max", prompt="test")

        assert "--plugin-dir" not in cmd

    def test_docker_plugin_dirs_constant_has_expected_entries(self) -> None:
        """The constant should list all three plugin repos."""
        from agent_cli import _DOCKER_PLUGIN_DIRS

        assert len(_DOCKER_PLUGIN_DIRS) == 3
        paths = {d.rsplit("/", 1)[-1] for d in _DOCKER_PLUGIN_DIRS}
        assert paths == {"claude-plugins-official", "superpowers", "lightfactory"}
