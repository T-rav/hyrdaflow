"""CI workflow scaffolding for GitHub Actions.

Generates a `.github/workflows/quality.yml` workflow that runs `make quality`
on pull requests and pushes to main. Supports Python, JavaScript/TypeScript,
and mixed-language repositories.

Part of the HydraFlow prep epic (#561). Language detection is provided by
the shared ``manifest.detect_language`` utility (consolidated in #896).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from manifest import detect_language


@dataclasses.dataclass
class CIScaffoldResult:
    """Result of CI workflow scaffolding."""

    created: bool
    skipped: bool
    skip_reason: str = ""
    language: str = ""
    workflow_path: str = ""


# --- Existing Workflow Detection ---


def has_quality_workflow(repo_root: Path) -> tuple[bool, str]:
    """Check whether an existing workflow already runs ``make quality``.

    Scans ``.github/workflows/*.yml`` and ``*.yaml`` for the literal string
    ``make quality``. Returns ``(True, filename)`` on first match, or
    ``(False, "")`` if none found.
    """
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False, ""

    for pattern in ("*.yml", "*.yaml"):
        for wf_file in sorted(workflows_dir.glob(pattern)):
            try:
                contents = wf_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if "make quality" in contents:
                return True, wf_file.name

    return False, ""


# --- Workflow Templates ---

_PYTHON_WORKFLOW = """\
name: Quality

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install ruff pyright pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Run quality checks
        run: make quality
"""

_JAVASCRIPT_WORKFLOW = """\
name: Quality

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        run: npm ci
      - name: Run quality checks
        run: make quality
"""

_MIXED_WORKFLOW = """\
name: Quality

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install Python dependencies
        run: |
          pip install ruff pyright pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Install Node dependencies
        run: npm ci
      - name: Run quality checks
        run: make quality
"""

_UNKNOWN_WORKFLOW = """\
name: Quality

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run quality checks
        run: make quality
"""

_WORKFLOW_TEMPLATES: dict[str, str] = {
    "python": _PYTHON_WORKFLOW,
    "javascript": _JAVASCRIPT_WORKFLOW,
    "mixed": _MIXED_WORKFLOW,
    "unknown": _UNKNOWN_WORKFLOW,
}


def generate_workflow(language: str) -> str:
    """Return the GitHub Actions workflow YAML for the given language."""
    return _WORKFLOW_TEMPLATES.get(language, _UNKNOWN_WORKFLOW)


# --- Orchestrator ---

_WORKFLOW_REL_PATH = ".github/workflows/quality.yml"


def scaffold_ci(repo_root: Path, *, dry_run: bool = False) -> CIScaffoldResult:
    """Scaffold a GitHub Actions CI workflow that runs ``make quality``.

    If an existing workflow already contains ``make quality``, the operation
    is skipped. Otherwise, ``.github/workflows/quality.yml`` is generated
    with language-appropriate setup steps.
    """
    found, existing_name = has_quality_workflow(repo_root)
    if found:
        return CIScaffoldResult(
            created=False,
            skipped=True,
            skip_reason=(
                f"Existing workflow '{existing_name}' already runs quality checks"
            ),
        )

    language = detect_language(repo_root)
    content = generate_workflow(language)
    workflow_path = repo_root / _WORKFLOW_REL_PATH

    if not dry_run:
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(content, encoding="utf-8")

    return CIScaffoldResult(
        created=not dry_run,
        skipped=False,
        language=language,
        workflow_path=_WORKFLOW_REL_PATH,
    )
