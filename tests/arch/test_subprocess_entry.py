from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(repo: Path) -> tuple[int, list[dict], str]:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "arch.subprocess_entry", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    violations = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, violations, proc.stderr


def test_no_rule_module_exits_zero_with_skipped_marker(tmp_path) -> None:
    rc, violations, stderr = _run(tmp_path)
    assert rc == 0
    assert violations == []
    assert "SKIPPED" in stderr


def test_valid_rules_with_violation_exits_one(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "low.py").write_text("import high\n")
    (tmp_path / "src" / "high.py").write_text("x = 1\n")
    (tmp_path / ".hydraflow").mkdir()
    (tmp_path / ".hydraflow" / "arch_rules.py").write_text(
        "from hydraflow.arch import LayerMap, Allowlist, python_ast_extractor\n"
        "EXTRACTOR = python_ast_extractor\n"
        "LAYERS = LayerMap({'src/low.py': 1, 'src/high.py': 2})\n"
        "ALLOWLIST = Allowlist({})\n"
        "FITNESS = []\n"
    )
    rc, violations, _ = _run(tmp_path)
    assert rc == 1
    assert len(violations) == 1
    assert violations[0]["rule"] == "layer"


def test_broken_rule_module_exits_two(tmp_path) -> None:
    (tmp_path / ".hydraflow").mkdir()
    (tmp_path / ".hydraflow" / "arch_rules.py").write_text("this is not python(((")
    rc, _, stderr = _run(tmp_path)
    assert rc == 2
    assert "SyntaxError" in stderr or "invalid syntax" in stderr


def test_validate_config_error_exits_two_not_one(tmp_path) -> None:
    """A Fitness rule with outside_layer absent from LayerMap is a config bug,
    not a violation. Must surface as exit 2 so CI doesn't conflate it with a
    real violation and swallow the diagnostic."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / ".hydraflow").mkdir()
    (tmp_path / ".hydraflow" / "arch_rules.py").write_text(
        "from hydraflow.arch import LayerMap, Allowlist, Fitness, python_ast_extractor\n"
        "EXTRACTOR = python_ast_extractor\n"
        "LAYERS = LayerMap({'src/a.py': 1})\n"
        "ALLOWLIST = Allowlist({})\n"
        "FITNESS = [Fitness.forbidden_symbol('junk', outside_layer=99)]\n"
    )
    rc, _, stderr = _run(tmp_path)
    assert rc == 2, f"expected exit 2, got {rc}; stderr:\n{stderr}"
    assert "VALIDATE_ERROR" in stderr
    assert "outside_layer" in stderr
