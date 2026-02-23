"""Tests for analysis.py — PlanAnalyzer pre-implementation analysis."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis import PlanAnalyzer
from models import AnalysisSection, AnalysisVerdict
from tests.conftest import AnalysisResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAN_ALL_EXIST = """\
## Files to Modify

### `models.py`
- Add AnalysisVerdict enum

### `orchestrator.py`
- Integrate analysis step

## New Files

### `analysis.py`
- New analysis module

## Testing Strategy

All tests use `tmp_path` fixtures. Run with pytest.
"""


def _setup_repo(tmp_path: Path, files: list[str] | None = None) -> Path:
    """Create a minimal repo structure for analysis tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / ".hydraflow" / "plans").mkdir(parents=True)

    # Create pyproject.toml with pytest config
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )

    for f in files or []:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {f}\n")

    return repo


# ---------------------------------------------------------------------------
# _extract_file_paths tests
# ---------------------------------------------------------------------------


class TestExtractFilePaths:
    """Tests for PlanAnalyzer._extract_file_paths."""

    def test_extract_file_paths_from_list_items(self) -> None:
        section = "- models.py: Add enum\n- config.py: Update config"
        result = PlanAnalyzer._extract_file_paths(section)
        assert "models.py" in result
        assert "config.py" in result

    def test_extract_file_paths_from_backticks(self) -> None:
        section = "Modify `path/to/file.py` and `other/file.ts`."
        result = PlanAnalyzer._extract_file_paths(section)
        assert "path/to/file.py" in result
        assert "other/file.ts" in result

    def test_extract_file_paths_from_headings(self) -> None:
        section = "### config.py\nSome description\n### models.py\nOther desc"
        result = PlanAnalyzer._extract_file_paths(section)
        assert "config.py" in result
        assert "models.py" in result

    def test_extract_file_paths_with_subdirectories(self) -> None:
        section = "- `tests/test_models.py`: Test the models"
        result = PlanAnalyzer._extract_file_paths(section)
        assert "tests/test_models.py" in result

    def test_extract_file_paths_deduplicates(self) -> None:
        section = "- `models.py`: once\n### `models.py`\nAgain"
        result = PlanAnalyzer._extract_file_paths(section)
        assert result.count("models.py") == 1

    def test_extract_file_paths_empty_section(self) -> None:
        result = PlanAnalyzer._extract_file_paths("")
        assert result == []

    def test_extract_file_paths_from_bold(self) -> None:
        section = "Modify **path/to/file.py** for the change."
        result = PlanAnalyzer._extract_file_paths(section)
        assert "path/to/file.py" in result

    def test_extract_file_paths_strips_leading_dot_slash(self) -> None:
        section = "- `./src/main.py`: entry point"
        result = PlanAnalyzer._extract_file_paths(section)
        assert "src/main.py" in result

    def test_extract_file_paths_numbered_headings(self) -> None:
        section = "### 1. `agent.py` — AgentRunner\nDesc"
        result = PlanAnalyzer._extract_file_paths(section)
        assert "agent.py" in result

    def test_extract_file_paths_filters_non_code_extensions(self) -> None:
        section = "- `notes.txt`: not a code file\n- `data.csv`: data"
        result = PlanAnalyzer._extract_file_paths(section)
        assert result == []


# ---------------------------------------------------------------------------
# _extract_section tests
# ---------------------------------------------------------------------------


class TestExtractSection:
    """Tests for PlanAnalyzer._extract_section."""

    def test_extract_section_finds_files_to_modify(self) -> None:
        text = "## Files to Modify\n\n- `models.py`\n\n## New Files\n\n- `analysis.py`"
        result = PlanAnalyzer._extract_section(text, "Files to Modify")
        assert "models.py" in result
        assert "analysis.py" not in result

    def test_extract_section_case_insensitive(self) -> None:
        text = "## files to modify\n\n- `models.py`\n\n## Other"
        result = PlanAnalyzer._extract_section(text, "Files to Modify")
        assert "models.py" in result

    def test_extract_section_returns_empty_when_missing(self) -> None:
        text = "## Summary\n\nSome text."
        result = PlanAnalyzer._extract_section(text, "Files to Modify")
        assert result == ""

    def test_extract_section_stops_at_next_heading(self) -> None:
        text = (
            "## Files to Modify\n\n- `models.py`\n\n## Testing Strategy\n\nUse pytest."
        )
        result = PlanAnalyzer._extract_section(text, "Files to Modify")
        assert "models.py" in result
        assert "pytest" not in result


# ---------------------------------------------------------------------------
# File validation tests
# ---------------------------------------------------------------------------


class TestFileValidation:
    """Tests for _validate_file_references."""

    def test_validate_file_references_all_exist(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, ["models.py", "orchestrator.py"])
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = (
            "## Files to Modify\n\n- `models.py`: change\n- `orchestrator.py`: change"
        )
        section = analyzer._validate_file_references(plan)

        assert section.verdict == AnalysisVerdict.PASS
        assert "2" in section.details[0]

    def test_validate_file_references_some_missing(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, ["models.py"])
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Files to Modify\n\n- `models.py`: exists\n- `missing.py`: gone"
        section = analyzer._validate_file_references(plan)

        assert section.verdict == AnalysisVerdict.WARN
        assert any("missing.py" in d for d in section.details)

    def test_validate_file_references_no_section(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path)
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Summary\n\nJust a summary."
        section = analyzer._validate_file_references(plan)

        assert section.verdict == AnalysisVerdict.PASS

    def test_validate_new_file_directories_exist(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path)
        analyzer = PlanAnalyzer(repo_root=repo)

        # tests/ dir exists from _setup_repo
        plan = "## New Files\n\n- `tests/test_new.py`: new test"
        warnings = analyzer._check_new_file_directories(plan)

        assert warnings == []

    def test_validate_new_file_directories_missing(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path)
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## New Files\n\n- `nonexistent_dir/new_file.py`: new module"
        warnings = analyzer._check_new_file_directories(plan)

        assert len(warnings) == 1
        assert "nonexistent_dir" in warnings[0]


# ---------------------------------------------------------------------------
# Test pattern validation tests
# ---------------------------------------------------------------------------


class TestTestPatternValidation:
    """Tests for _validate_test_patterns."""

    def test_validate_test_patterns_valid(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path)  # creates tests/ and pyproject.toml with pytest
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nWrite tests in `tests/` using pytest."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.PASS

    def test_validate_test_patterns_missing_test_dir(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        # pyproject.toml with pytest but no tests/ dir
        (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nTests in `tests/`."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.WARN
        assert any("tests/" in d for d in section.details)

    def test_validate_test_patterns_no_testing_section(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path)
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Summary\n\nNo testing section."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.PASS

    def test_validate_test_patterns_no_pyproject(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests").mkdir()
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nUse pytest."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.WARN
        assert any("pyproject.toml" in d for d in section.details)

    def test_validate_test_patterns_pyproject_without_pytest(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests").mkdir()
        (repo / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools']\n"
        )
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nUse pytest."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.WARN
        assert any("No pytest configuration" in d for d in section.details)

    def test_validate_test_patterns_makefile_with_test_target(
        self, tmp_path: Path
    ) -> None:
        repo = _setup_repo(tmp_path)
        (repo / "Makefile").write_text("test:\n\tpytest tests/\n")
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nRun make test."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.PASS
        assert any("Makefile" in d for d in section.details)

    def test_validate_test_patterns_makefile_without_test_target(
        self, tmp_path: Path
    ) -> None:
        repo = _setup_repo(tmp_path)
        (repo / "Makefile").write_text("build:\n\techo build\n")
        analyzer = PlanAnalyzer(repo_root=repo)

        plan = "## Testing Strategy\n\nRun make test."
        section = analyzer._validate_test_patterns(plan)

        assert section.verdict == AnalysisVerdict.WARN
        assert any("No test target" in d for d in section.details)


# ---------------------------------------------------------------------------
# Full analyze() tests
# ---------------------------------------------------------------------------


class TestAnalyze:
    """Tests for the full analyze() method."""

    def test_analyze_all_pass(self, tmp_path: Path) -> None:
        repo = _setup_repo(tmp_path, ["models.py", "orchestrator.py"])
        analyzer = PlanAnalyzer(repo_root=repo)

        result = analyzer.analyze(PLAN_ALL_EXIST, 42)

        assert not result.blocked
        assert len(result.sections) == 2
        assert all(
            s.verdict in (AnalysisVerdict.PASS, AnalysisVerdict.WARN)
            for s in result.sections
        )


# ---------------------------------------------------------------------------
# format_comment() tests
# ---------------------------------------------------------------------------


class TestFormatComment:
    """Tests for AnalysisResult.format_comment."""

    def test_format_comment_includes_all_sections(self) -> None:
        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.PASS,
                    details=["All good."],
                ),
                AnalysisSection(
                    name="Conflict Check",
                    verdict=AnalysisVerdict.WARN,
                    details=["Minor overlap."],
                ),
                AnalysisSection(
                    name="Test Pattern Check",
                    verdict=AnalysisVerdict.PASS,
                    details=["Tests valid."],
                ),
            ],
        )
        comment = result.format_comment()

        assert "## Pre-Implementation Analysis" in comment
        assert "File Validation" in comment
        assert "Conflict Check" in comment
        assert "Test Pattern Check" in comment

    def test_format_comment_shows_verdict_icons(self) -> None:
        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(name="A", verdict=AnalysisVerdict.PASS, details=[]),
                AnalysisSection(name="B", verdict=AnalysisVerdict.WARN, details=[]),
                AnalysisSection(name="C", verdict=AnalysisVerdict.BLOCK, details=[]),
            ],
        )
        comment = result.format_comment()

        assert "\u2705 PASS" in comment
        assert "\u26a0\ufe0f WARN" in comment
        assert "\U0001f6d1 BLOCK" in comment

    def test_format_comment_includes_details(self) -> None:
        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.WARN,
                    details=["Missing file: `foo.py`", "Missing file: `bar.py`"],
                ),
            ],
        )
        comment = result.format_comment()

        assert "- Missing file: `foo.py`" in comment
        assert "- Missing file: `bar.py`" in comment

    def test_format_comment_includes_footer(self) -> None:
        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(name="A", verdict=AnalysisVerdict.PASS, details=[]),
            ],
        )
        comment = result.format_comment()

        assert "*Generated by HydraFlow Analyzer*" in comment
