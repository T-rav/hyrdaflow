"""CI workflow scaffolding for GitHub Actions.

Generates a `.github/workflows/quality.yml` workflow with stack-specific
lint/test/build-style checks for common ecosystems.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from manifest import detect_language  # noqa: F401 - re-export for compatibility tests
from polyglot_prep import detect_prep_stack


@dataclasses.dataclass
class CIScaffoldResult:
    """Result of CI workflow scaffolding."""

    created: bool
    skipped: bool
    skip_reason: str = ""
    language: str = ""
    workflow_path: str = ""


def has_quality_workflow(repo_root: Path) -> tuple[bool, str]:
    """Check whether an existing quality workflow already exists.

    Scans `.github/workflows/*.yml` and `*.yaml` for either:
    - `prep-managed: quality-workflow`
    - legacy `make quality`
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
            if (
                "prep-managed: quality-workflow" in contents
                or "make quality" in contents
            ):
                return True, wf_file.name

    return False, ""


_UNIVERSAL_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  discover-projects:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.scan.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
      - name: Discover project paths
        id: scan
        shell: bash
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          root = Path(".")
          ignored = {
              ".git", ".github", ".venv", "venv", "node_modules",
              "dist", "build", "target", ".next", ".turbo", ".idea",
              "__pycache__", ".pytest_cache"
          }
          markers = {
              "Makefile", "makefile", "GNUmakefile",
              "pyproject.toml", "requirements.txt", "setup.py",
              "package.json", "go.mod", "Cargo.toml", "pom.xml",
              "build.gradle", "build.gradle.kts", "Gemfile",
              "CMakeLists.txt"
          }

          paths = set()
          for path in root.rglob("*"):
              if any(part in ignored for part in path.parts):
                  continue
              if not path.is_file():
                  continue
              if (
                  path.name in markers
                  or path.name.endswith(".sln")
                  or path.name.endswith(".csproj")
              ):
                  rel = path.parent.relative_to(root)
                  paths.add(str(rel) if str(rel) else ".")

          items = [{"project_dir": p} for p in sorted(paths)]
          payload = json.dumps({"include": items})
          with open(".github_output", "w", encoding="utf-8") as f:
              f.write(f"matrix={payload}\\n")
          print(f"matrix={payload}")
          PY
          cat .github_output >> "$GITHUB_OUTPUT"

  quality:
    runs-on: ubuntu-latest
    needs: discover-projects
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.discover-projects.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        if: ${{ hashFiles(format('{0}/pyproject.toml', matrix.project_dir), format('{0}/requirements.txt', matrix.project_dir), format('{0}/setup.py', matrix.project_dir)) != '' }}
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Set up Node
        if: ${{ hashFiles(format('{0}/package.json', matrix.project_dir)) != '' }}
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Set up Java
        if: ${{ hashFiles(format('{0}/pom.xml', matrix.project_dir), format('{0}/build.gradle', matrix.project_dir), format('{0}/build.gradle.kts', matrix.project_dir)) != '' }}
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '21'
      - name: Set up Ruby
        if: ${{ hashFiles(format('{0}/Gemfile', matrix.project_dir)) != '' }}
        uses: ruby/setup-ruby@v1
      - name: Set up .NET
        if: ${{ hashFiles(format('{0}/*.sln', matrix.project_dir), format('{0}/*.csproj', matrix.project_dir)) != '' }}
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'
      - name: Set up Go
        if: ${{ hashFiles(format('{0}/go.mod', matrix.project_dir)) != '' }}
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'
      - name: Quality Lite
        shell: bash
        run: |
          set -euo pipefail
          cd "${{ matrix.project_dir }}"
          if [ -f Makefile ] || [ -f makefile ] || [ -f GNUmakefile ]; then
            make quality-lite
            exit 0
          fi
          echo "Missing Makefile in ${{ matrix.project_dir }}. Run 'make prep' to scaffold make targets." >&2
          exit 1
      - name: Quality Full
        shell: bash
        run: |
          set -euo pipefail
          cd "${{ matrix.project_dir }}"
          if [ -f Makefile ] || [ -f makefile ] || [ -f GNUmakefile ]; then
            make quality
            exit 0
          fi
          echo "Missing Makefile in ${{ matrix.project_dir }}. Run 'make prep' to scaffold make targets." >&2
          exit 1
"""

_WORKFLOW_TEMPLATES: dict[str, str] = {
    "python": _UNIVERSAL_WORKFLOW,
    "javascript": _UNIVERSAL_WORKFLOW,
    "node": _UNIVERSAL_WORKFLOW,
    "mixed": _UNIVERSAL_WORKFLOW,
    "java": _UNIVERSAL_WORKFLOW,
    "ruby": _UNIVERSAL_WORKFLOW,
    "rails": _UNIVERSAL_WORKFLOW,
    "csharp": _UNIVERSAL_WORKFLOW,
    "go": _UNIVERSAL_WORKFLOW,
    "rust": _UNIVERSAL_WORKFLOW,
    "cpp": _UNIVERSAL_WORKFLOW,
    "unknown": _UNIVERSAL_WORKFLOW,
}


def generate_workflow(language: str) -> str:
    """Return the GitHub Actions workflow YAML for the given language."""
    return _WORKFLOW_TEMPLATES.get(language, _UNIVERSAL_WORKFLOW)


_WORKFLOW_REL_PATH = ".github/workflows/quality.yml"


def scaffold_ci(repo_root: Path, *, dry_run: bool = False) -> CIScaffoldResult:
    """Scaffold a GitHub Actions CI workflow for common stacks."""
    found, existing_name = has_quality_workflow(repo_root)
    if found:
        return CIScaffoldResult(
            created=False,
            skipped=True,
            skip_reason=(
                f"Existing workflow '{existing_name}' already runs quality checks"
            ),
        )

    language = detect_prep_stack(repo_root)
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
