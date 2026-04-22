from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_arch.py"


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_rules_prints_skipped_and_exits_zero(tmp_path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIPPED" in (r.stdout + r.stderr)


def test_with_violations_exits_one_and_prints_human_report(tmp_path) -> None:
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
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "src/low.py" in r.stdout
    assert "layer" in r.stdout


def test_skipped_detection_uses_line_prefix_not_substring(tmp_path) -> None:
    """SKIPPED must match a full-line prefix on stderr, not a substring anywhere
    in stderr. Guards against a future stderr line (warning, deprecation, etc.)
    that happens to contain the word "SKIPPED" being misread as "rule module
    absent" when rules are in fact present and violated."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "low.py").write_text("import high\n")
    (tmp_path / "src" / "high.py").write_text("x = 1\n")
    (tmp_path / ".hydraflow").mkdir()
    # Rule module with a debug print containing the word SKIPPED. The parent
    # must still detect violations and exit 1, not mistake this for a skip.
    (tmp_path / ".hydraflow" / "arch_rules.py").write_text(
        "import sys\n"
        "print('warning: SKIPPED something unrelated', file=sys.stderr)\n"
        "from hydraflow.arch import LayerMap, Allowlist, python_ast_extractor\n"
        "EXTRACTOR = python_ast_extractor\n"
        "LAYERS = LayerMap({'src/low.py': 1, 'src/high.py': 2})\n"
        "ALLOWLIST = Allowlist({})\n"
        "FITNESS = []\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, (
        f"expected exit 1, got {r.returncode}; stderr:\n{r.stderr}"
    )
    assert "Architecture violations" in r.stdout
    assert "SKIPPED: no .hydraflow/arch_rules.py" not in r.stdout
