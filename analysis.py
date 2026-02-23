"""Pre-implementation plan analysis — validates plan-to-codebase consistency."""

from __future__ import annotations

import re
from pathlib import Path

from models import AnalysisResult, AnalysisSection, AnalysisVerdict

# File extensions considered valid code/config references in plans.
_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".toml",
        ".cfg",
        ".html",
        ".css",
    }
)


class PlanAnalyzer:
    """Analyzes a plan for consistency before implementation begins."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def analyze(self, plan_text: str, issue_number: int) -> AnalysisResult:
        """Run all analysis checks and return the combined result."""
        file_section = self._validate_file_references(plan_text)
        test_section = self._validate_test_patterns(plan_text)

        return AnalysisResult(
            issue_number=issue_number,
            sections=[file_section, test_section],
        )

    @staticmethod
    def _extract_section(plan_text: str, heading: str) -> str:
        """Extract content between a ``## heading`` and the next ``##`` heading."""
        pattern = rf"##\s+{re.escape(heading)}[^\n]*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, plan_text, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_file_paths(section_text: str) -> list[str]:
        """Extract file paths from a plan section text."""
        if not section_text:
            return []

        found: set[str] = set()

        # Backtick-wrapped paths: `path/to/file.py`
        for m in re.finditer(r"`([\w./\-]+\.\w+)`", section_text):
            found.add(m.group(1))

        # Heading-style: ### `config.py` or ### config.py or ### 1. `agent.py` — desc
        for m in re.finditer(r"###\s+(?:\d+\.\s+)?`?([\w./\-]+\.\w+)`?", section_text):
            found.add(m.group(1))

        # List-item paths: - path.py: desc  or  - path.py — desc  or  * path.py
        for m in re.finditer(
            r"^[-*]\s+`?([\w./\-]+\.\w+)`?", section_text, re.MULTILINE
        ):
            found.add(m.group(1))

        # Bold paths: **path/to/file.py**
        for m in re.finditer(r"\*\*([\w./\-]+\.\w+)\*\*", section_text):
            found.add(m.group(1))

        # Filter to known code extensions and normalise
        result: list[str] = []
        for path in sorted(found):
            # Strip leading ./
            cleaned = path.removeprefix("./")
            suffix = Path(cleaned).suffix.lower()
            if suffix in _CODE_EXTENSIONS:
                result.append(cleaned)

        return result

    def _validate_file_references(self, plan_text: str) -> AnalysisSection:
        """Validate files in ``## Files to Modify`` and ``## New Files`` exist."""
        modify_section = self._extract_section(plan_text, "Files to Modify")
        modify_files = self._extract_file_paths(modify_section)

        details: list[str] = []
        missing_count = 0

        for fp in modify_files:
            full = self._repo_root / fp
            if not full.is_file():
                details.append(f"Missing file: `{fp}`")
                missing_count += 1

        # Check new file parent directories
        new_warnings = self._check_new_file_directories(plan_text)
        details.extend(new_warnings)

        if missing_count > 0 or new_warnings:
            total = len(modify_files)
            details.insert(
                0,
                f"{total - missing_count}/{total} referenced files exist in the repository.",
            )
            return AnalysisSection(
                name="File Validation",
                verdict=AnalysisVerdict.WARN,
                details=details,
            )

        total = len(modify_files)
        return AnalysisSection(
            name="File Validation",
            verdict=AnalysisVerdict.PASS,
            details=[f"All {total} referenced files exist in the repository."]
            if total > 0
            else ["No files to modify section found."],
        )

    def _check_new_file_directories(self, plan_text: str) -> list[str]:
        """Check that parent directories for new files exist."""
        new_section = self._extract_section(plan_text, "New Files")
        new_files = self._extract_file_paths(new_section)
        warnings: list[str] = []

        for fp in new_files:
            parent = (self._repo_root / fp).parent
            if not parent.is_dir():
                warnings.append(f"Parent directory missing for new file: `{fp}`")

        return warnings

    def _validate_test_patterns(self, plan_text: str) -> AnalysisSection:
        """Validate test patterns referenced in the plan."""
        test_section = self._extract_section(plan_text, "Testing Strategy")
        if not test_section:
            return AnalysisSection(
                name="Test Pattern Check",
                verdict=AnalysisVerdict.PASS,
                details=["No testing strategy section found."],
            )

        details: list[str] = []
        warnings = 0

        # Check that tests/ directory exists
        tests_dir = self._repo_root / "tests"
        if not tests_dir.is_dir():
            details.append("Test directory `tests/` not found in repository.")
            warnings += 1
        else:
            details.append("Test directory `tests/` exists.")

        # Check pyproject.toml for pytest configuration
        pyproject = self._repo_root / "pyproject.toml"
        if pyproject.is_file():
            content = pyproject.read_text()
            if "[tool.pytest" in content:
                details.append("pytest configuration found in `pyproject.toml`.")
            else:
                details.append("No pytest configuration found in `pyproject.toml`.")
                warnings += 1
        else:
            details.append("`pyproject.toml` not found.")
            warnings += 1

        # Check Makefile for test target
        makefile = self._repo_root / "Makefile"
        if makefile.is_file():
            mk_content = makefile.read_text()
            if "test" in mk_content:
                details.append("Test target found in `Makefile`.")
            else:
                details.append("No test target found in `Makefile`.")
                warnings += 1

        verdict = AnalysisVerdict.WARN if warnings > 0 else AnalysisVerdict.PASS
        return AnalysisSection(
            name="Test Pattern Check",
            verdict=verdict,
            details=details,
        )
