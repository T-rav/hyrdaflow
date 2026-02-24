"""Makefile scaffolding for target repos.

Generates or merges Makefile targets (help, lint, lint-check, lint-fix,
typecheck, security, test, quality-lite, quality) based on detected prep
stack (Python, Node, Java, Ruby/Rails, C#, Go, Rust, C++).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from manifest import detect_language  # noqa: F401 - compatibility re-export
from polyglot_prep import detect_prep_stack
from prep_ignore import PREP_IGNORED_DIRS, load_git_submodule_roots

_PYTHON_TARGETS: dict[str, str] = {
    "lint": "\truff check . --fix && ruff format .\n",
    "lint-check": "\truff check . && ruff format . --check\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tpyright\n",
    "security": "\tbandit -r . --severity-level medium\n",
    "test": "\tpytest tests/ -x -q\n",
}

_JS_TARGETS: dict[str, str] = {
    "lint": "\tnpx eslint . --fix\n",
    "lint-check": "\tnpx eslint .\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tnpx tsc --noEmit\n",
    "security": "\tnpm audit --audit-level=moderate\n",
    "test": "\tnpx vitest run --exclude='hydraflow/**'\n",
}

_JAVA_TARGETS: dict[str, str] = {
    "lint": (
        "\tif [ -f pom.xml ]; then mvn -B -DskipTests checkstyle:check; "
        "elif [ -f gradlew ]; then ./gradlew checkstyleMain checkstyleTest; "
        'else echo "No Java lint command configured" >&2; exit 1; fi\n'
    ),
    "lint-check": "\t$(MAKE) lint\n",
    "lint-fix": (
        "\tif [ -f pom.xml ]; then mvn -B spotless:apply || true; "
        "elif [ -f gradlew ]; then ./gradlew spotlessApply || true; "
        'else echo "No Java lint-fix command configured" >&2; exit 1; fi\n'
    ),
    "typecheck": (
        "\tif [ -f pom.xml ]; then mvn -B -DskipTests compile; "
        "elif [ -f gradlew ]; then ./gradlew classes; "
        'else echo "No Java typecheck command configured" >&2; exit 1; fi\n'
    ),
    "security": (
        "\tif [ -f pom.xml ]; then mvn -B -DskipTests org.owasp:dependency-check-maven:check || true; "
        "elif [ -f gradlew ]; then ./gradlew dependencyCheckAnalyze || true; "
        'else echo "No Java security command configured" >&2; exit 1; fi\n'
    ),
    "test": (
        "\tif [ -f pom.xml ]; then mvn -B test; "
        "elif [ -f gradlew ]; then ./gradlew test; "
        'else echo "No Java test command configured" >&2; exit 1; fi\n'
    ),
}

_RUBY_TARGETS: dict[str, str] = {
    "lint": "\tbundle exec rubocop -A\n",
    "lint-check": "\tbundle exec rubocop\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tbundle exec steep check || bundle exec sorbet tc || true\n",
    "security": "\tbundle exec brakeman -q || true\n",
    "test": "\tbundle exec rspec || bundle exec rake test\n",
}

_RAILS_TARGETS: dict[str, str] = {
    "lint": "\tbundle exec rubocop -A\n",
    "lint-check": "\tbundle exec rubocop\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tbundle exec steep check || bundle exec sorbet tc || true\n",
    "security": "\tbundle exec brakeman -q\n",
    "test": "\tbundle exec rails test || bundle exec rspec\n",
}

_CSHARP_TARGETS: dict[str, str] = {
    "lint": "\tdotnet format\n",
    "lint-check": "\tdotnet format --verify-no-changes\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tdotnet build --configuration Release --no-restore\n",
    "security": "\tdotnet list package --vulnerable --include-transitive\n",
    "test": "\tdotnet test --configuration Release --no-build\n",
}

_GO_TARGETS: dict[str, str] = {
    "lint": "\tgofmt -w . && go vet ./...\n",
    "lint-check": '\ttest -z "$$(gofmt -l .)" && go vet ./...\n',
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tgo test ./... -run TestDoesNotExist\n",
    "security": "\tgovulncheck ./... || true\n",
    "test": "\tgo test ./...\n",
}

_RUST_TARGETS: dict[str, str] = {
    "lint": "\tcargo fmt && cargo clippy --all-targets -- -D warnings\n",
    "lint-check": "\tcargo fmt --check && cargo clippy --all-targets -- -D warnings\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": "\tcargo check --all-targets\n",
    "security": "\tcargo audit || true\n",
    "test": "\tcargo test --all-targets\n",
}

_CPP_TARGETS: dict[str, str] = {
    "lint": "\tclang-format -i $$(find . -name '*.cpp' -o -name '*.h' -o -name '*.hpp' 2>/dev/null) || true\n",
    "lint-check": "\tclang-format --dry-run --Werror $$(find . -name '*.cpp' -o -name '*.h' -o -name '*.hpp' 2>/dev/null) || true\n",
    "lint-fix": "\t$(MAKE) lint\n",
    "typecheck": '\tif [ -f CMakeLists.txt ]; then cmake -S . -B build; cmake --build build; else echo "No CMakeLists.txt found" >&2; exit 1; fi\n',
    "security": "\tcppcheck --enable=warning,style,performance --error-exitcode=1 . || true\n",
    "test": '\tif [ -d build ]; then ctest --test-dir build --output-on-failure; else echo "Build dir missing; run make typecheck first" >&2; exit 1; fi\n',
}

_COVERAGE_CHECK_RECIPE = (
    "\t@python - <<'PY'\n"
    "\timport json\n"
    "\timport os\n"
    "\tfrom pathlib import Path\n"
    "\timport xml.etree.ElementTree as ET\n"
    "\troot = Path('.')\n"
    "\ttarget = float(os.environ.get('COVERAGE_TARGET', '70'))\n"
    "\tpct = None\n"
    "\tsource = ''\n"
    "\tfor p in [root/'coverage'/'coverage-summary.json', root/'coverage-summary.json']:\n"
    "\t    if p.is_file():\n"
    "\t        try:\n"
    "\t            pct = float(json.loads(p.read_text()).get('total', {}).get('lines', {}).get('pct'))\n"
    "\t            source = str(p)\n"
    "\t            break\n"
    "\t        except Exception:\n"
    "\t            pass\n"
    "\tif pct is None:\n"
    "\t    for p in [root/'coverage.xml', root/'cobertura.xml', root/'jacoco.xml']:\n"
    "\t        if p.is_file():\n"
    "\t            try:\n"
    "\t                r = ET.parse(p).getroot()\n"
    "\t                lr = r.attrib.get('line-rate')\n"
    "\t                if lr is not None:\n"
    "\t                    pct = float(lr) * 100.0\n"
    "\t                    source = str(p)\n"
    "\t                    break\n"
    "\t            except Exception:\n"
    "\t                pass\n"
    "\tif pct is None:\n"
    "\t    for p in [root/'coverage'/'lcov.info', root/'lcov.info']:\n"
    "\t        if p.is_file():\n"
    "\t            try:\n"
    "\t                lf = lh = 0\n"
    "\t                for line in p.read_text().splitlines():\n"
    "\t                    if line.startswith('LF:'):\n"
    "\t                        lf += int(line[3:])\n"
    "\t                    elif line.startswith('LH:'):\n"
    "\t                        lh += int(line[3:])\n"
    "\t                if lf > 0:\n"
    "\t                    pct = (lh / lf) * 100.0\n"
    "\t                    source = str(p)\n"
    "\t                    break\n"
    "\t            except Exception:\n"
    "\t                pass\n"
    "\tif pct is None and (root / 'coverage.out').is_file():\n"
    "\t    p = root / 'coverage.out'\n"
    "\t    try:\n"
    "\t        total = covered = 0\n"
    "\t        for line in p.read_text().splitlines():\n"
    "\t            if line.startswith('mode:'):\n"
    "\t                continue\n"
    "\t            parts = line.split()\n"
    "\t            if len(parts) != 3:\n"
    "\t                continue\n"
    "\t            stmts = int(parts[1])\n"
    "\t            hits = int(parts[2])\n"
    "\t            total += stmts\n"
    "\t            if hits > 0:\n"
    "\t                covered += stmts\n"
    "\t        if total > 0:\n"
    "\t            pct = (covered / total) * 100.0\n"
    "\t            source = str(p)\n"
    "\texcept Exception:\n"
    "\t    pass\n"
    "\tif pct is None:\n"
    "\t    raise SystemExit('coverage-check: no coverage artifact found')\n"
    "\tif pct < target:\n"
    "\t    raise SystemExit(f'coverage-check: {pct:.1f}% from {source} is below {target:.0f}%')\n"
    "\tprint(f'coverage-check: {pct:.1f}% from {source} (>= {target:.0f}%)')\n"
    "\tPY\n"
)

# quality targets are prerequisite-only targets
_QUALITY_LITE_LINE = "quality-lite: lint-check typecheck security\n"
_QUALITY_LINE = "quality: quality-lite test coverage-check\n"
_DEFAULT_GOAL_LINE = ".DEFAULT_GOAL := help"
_COVERAGE_MIN_LINE = "COVERAGE_MIN ?= 70"
_COVERAGE_TARGET_LINE = "COVERAGE_TARGET ?= 70"
_HELP_RECIPE = (
    '\t@echo "Available targets:"\n'
    '\t@echo "  help         Show this help"\n'
    '\t@echo "  lint         Run lint auto-fixes"\n'
    '\t@echo "  lint-check   Run lint checks"\n'
    '\t@echo "  lint-fix     Alias for lint"\n'
    '\t@echo "  typecheck    Run type checks"\n'
    '\t@echo "  security     Run security checks"\n'
    '\t@echo "  test         Run tests"\n'
    '\t@echo "  coverage-check Enforce coverage floor from reports"\n'
    '\t@echo "  coverage vars COVERAGE_MIN=70 COVERAGE_TARGET=70"\n'
    '\t@echo "  quality-lite Run lint/type/security"\n'
    '\t@echo "  quality      Run quality-lite + tests"\n'
)

_ALL_TARGET_NAMES = [
    "help",
    "lint",
    "lint-check",
    "lint-fix",
    "typecheck",
    "security",
    "test",
    "coverage-check",
    "quality-lite",
    "quality",
]

_MAKEFILE_NAMES = ("GNUmakefile", "makefile", "Makefile")


@dataclasses.dataclass
class ScaffoldResult:
    """Result of a Makefile scaffolding operation."""

    created: bool = False
    targets_added: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    language: str = "unknown"


@dataclasses.dataclass
class MultiScaffoldResult:
    """Result of scaffolding Makefiles across discovered project paths."""

    results: dict[str, ScaffoldResult] = dataclasses.field(default_factory=dict)


_PROJECT_MARKERS: tuple[str, ...] = (
    "Makefile",
    "makefile",
    "GNUmakefile",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "CMakeLists.txt",
)


def discover_project_paths(repo_root: Path) -> list[Path]:
    """Discover project directories that should get Makefile scaffolding."""
    paths: set[Path] = set()
    submodule_roots = load_git_submodule_roots(repo_root)
    for path in repo_root.rglob("*"):
        if any(part in PREP_IGNORED_DIRS for part in path.parts):
            continue
        resolved = path.resolve()
        if any(
            root == resolved or root in resolved.parents for root in submodule_roots
        ):
            continue
        if not path.is_file():
            continue
        if path.name in _PROJECT_MARKERS or path.name.endswith((".sln", ".csproj")):
            paths.add(path.parent)
    return sorted(paths)


def parse_makefile(content: str) -> dict[str, str]:
    """Extract target-name -> recipe-text mappings from Makefile content.

    Ignores comments, variable assignments, and .PHONY declarations.
    """
    targets: dict[str, str] = {}
    current_target: str | None = None
    recipe_lines: list[str] = []

    for line in content.split("\n"):
        # Skip .PHONY declarations
        if line.startswith(".PHONY"):
            continue

        # Check for target definition: "name:" or "name: deps"
        # Exclude variable assignments like CC := gcc or CC ::= gcc
        target_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?![=:])(.*)$", line)
        if target_match:
            # Save previous target
            if current_target is not None:
                targets[current_target] = "\n".join(recipe_lines)
            current_target = target_match.group(1)
            recipe_lines = []
            continue

        # Recipe line (tab-indented)
        if line.startswith("\t") and current_target is not None:
            recipe_lines.append(line.lstrip("\t"))
            continue

        # Blank or non-recipe line ends current target
        if current_target is not None and not line.startswith("\t"):
            targets[current_target] = "\n".join(recipe_lines)
            current_target = None
            recipe_lines = []

    # Save last target
    if current_target is not None:
        targets[current_target] = "\n".join(recipe_lines)

    return targets


def _targets_for_language(language: str) -> dict[str, str]:
    """Return the target templates for a given language."""
    templates: dict[str, dict[str, str]] = {
        "python": _PYTHON_TARGETS,
        "javascript": _JS_TARGETS,
        "node": _JS_TARGETS,
        "java": _JAVA_TARGETS,
        "ruby": _RUBY_TARGETS,
        "rails": _RAILS_TARGETS,
        "csharp": _CSHARP_TARGETS,
        "go": _GO_TARGETS,
        "rust": _RUST_TARGETS,
        "cpp": _CPP_TARGETS,
    }
    base = templates.get(language)
    if not base:
        return {}
    targets = dict(base)
    targets["coverage-check"] = _COVERAGE_CHECK_RECIPE
    return targets


def generate_makefile(language: str) -> str:
    """Build a complete Makefile string from the template for the given language."""
    targets = _targets_for_language(language)
    if not targets:
        return ""

    lines: list[str] = []
    lines.append(_DEFAULT_GOAL_LINE)
    lines.append(_COVERAGE_MIN_LINE)
    lines.append(_COVERAGE_TARGET_LINE)
    lines.append("")
    lines.append(f".PHONY: {' '.join(_ALL_TARGET_NAMES)}")
    lines.append("")
    lines.append("help:")
    lines.append(_HELP_RECIPE)

    for name, recipe in targets.items():
        lines.append(f"{name}:")
        lines.append(recipe)

    lines.append(_QUALITY_LITE_LINE)
    lines.append(_QUALITY_LINE)

    return "\n".join(lines)


def merge_makefile(existing_content: str, language: str) -> tuple[str, list[str]]:
    """Merge missing targets into an existing Makefile.

    Returns (new_content, warnings). Existing targets are never overwritten.
    Warnings are emitted when an existing target has a different recipe.
    """
    template_targets = _targets_for_language(language)
    if not template_targets:
        return existing_content, []

    # Include prerequisite-only quality targets in the full set to check.
    all_template: dict[str, str | None] = dict(template_targets)
    all_template["help"] = _HELP_RECIPE
    all_template["quality-lite"] = None
    all_template["quality"] = None  # prerequisite-only, no recipe body

    existing_targets = parse_makefile(existing_content)

    warnings: list[str] = []
    targets_to_add: list[str] = []

    for name, template_recipe in all_template.items():
        if name in existing_targets:
            # Compare recipes (only for targets with recipe bodies)
            if template_recipe is not None:
                existing_recipe = existing_targets[name]
                expected_recipe = template_recipe.strip("\n").lstrip("\t")
                if existing_recipe.strip() != expected_recipe.strip():
                    warnings.append(
                        f"Target '{name}' exists with different recipe: "
                        f"found '{existing_recipe.strip()}', "
                        f"expected '{expected_recipe.strip()}'"
                    )
        else:
            targets_to_add.append(name)

    # Warn if existing quality targets have different prerequisites.
    if "quality-lite" in existing_targets:
        quality_lite_match = re.search(
            r"^quality-lite\s*:(?![=:])\s*(.*)",
            existing_content,
            re.MULTILINE,
        )
        if quality_lite_match:
            existing_deps = quality_lite_match.group(1).strip()
            expected_deps = "lint-check typecheck security"
            if existing_deps != expected_deps:
                warnings.append(
                    f"Target 'quality-lite' exists with different prerequisites: "
                    f"found '{existing_deps}', expected '{expected_deps}'"
                )

    if "quality" in existing_targets:
        quality_match = re.search(
            r"^quality\s*:(?![=:])\s*(.*)",
            existing_content,
            re.MULTILINE,
        )
        if quality_match:
            existing_deps = quality_match.group(1).strip()
            expected_deps = "quality-lite test coverage-check"
            if existing_deps != expected_deps:
                warnings.append(
                    f"Target 'quality' exists with different prerequisites: "
                    f"found '{existing_deps}', expected '{expected_deps}'"
                )

    if not targets_to_add:
        return existing_content, warnings

    # Build the new content by appending missing targets
    new_lines = existing_content.rstrip("\n")

    # Add a blank line separator
    new_lines += "\n"

    for name in targets_to_add:
        if name in ("quality-lite", "quality"):
            continue  # Add prerequisite-only targets last.
        if name == "help":
            new_lines += f"\nhelp:\n{_HELP_RECIPE}"
            continue
        new_lines += f"\n{name}:\n{template_targets[name]}"

    if "quality-lite" in targets_to_add:
        new_lines += f"\n{_QUALITY_LITE_LINE}"
    if "quality" in targets_to_add:
        new_lines += f"\n{_QUALITY_LINE}"

    # Ensure .PHONY includes all targets — preserve existing .PHONY entries
    # that may not have target definitions in this file (e.g., from includes).
    existing_phony: set[str] = set()
    for _line in existing_content.split("\n"):
        if _line.startswith(".PHONY"):
            _rest = _line.split(":", 1)
            if len(_rest) > 1:
                existing_phony.update(_rest[1].split())
    all_target_names = (
        existing_phony | set(existing_targets.keys()) | set(targets_to_add)
    )
    phony_names = " ".join(sorted(all_target_names))

    if ".PHONY" in existing_content:
        # Replace existing .PHONY line(s)
        new_lines = re.sub(
            r"\.PHONY:.*",
            f".PHONY: {phony_names}",
            new_lines,
            count=1,
        )
    else:
        # Prepend .PHONY
        new_lines = f".PHONY: {phony_names}\n\n{new_lines}"

    if not re.search(r"^\.DEFAULT_GOAL\s*:?=", existing_content, re.MULTILINE):
        new_lines = f"{_DEFAULT_GOAL_LINE}\n\n{new_lines}"

    # Ensure trailing newline
    if not new_lines.endswith("\n"):
        new_lines += "\n"

    return new_lines, warnings


def _find_existing_makefile(repo_root: Path) -> Path | None:
    """Find an existing Makefile, checking GNUmakefile, makefile, Makefile."""
    for name in _MAKEFILE_NAMES:
        path = repo_root / name
        if path.exists():
            return path
    return None


def scaffold_makefile(repo_root: Path, dry_run: bool = False) -> ScaffoldResult:
    """Scaffold or merge Makefile targets for a repo.

    Detects language, checks for existing Makefile, generates or merges
    targets, and writes the result (unless dry_run is True).
    """
    language = detect_prep_stack(repo_root)
    result = ScaffoldResult(language=language)

    if language == "unknown":
        return result

    existing_path = _find_existing_makefile(repo_root)

    if existing_path is not None:
        existing_content = existing_path.read_text()

        # Treat empty/whitespace-only Makefiles as "no Makefile"
        if not existing_content.strip():
            content = generate_makefile(language)
            result.created = True
            result.targets_added = list(_ALL_TARGET_NAMES)
            if not dry_run:
                existing_path.write_text(content)
            return result

        existing_targets = parse_makefile(existing_content)
        new_content, warnings = merge_makefile(existing_content, language)
        result.warnings = warnings

        # Determine which targets were added
        template_targets = _targets_for_language(language)
        all_names = ["help", *template_targets.keys(), "quality-lite", "quality"]
        result.targets_added = [n for n in all_names if n not in existing_targets]
        result.skipped = [n for n in all_names if n in existing_targets]

        if result.targets_added and not dry_run:
            existing_path.write_text(new_content)
    else:
        content = generate_makefile(language)
        result.created = True
        result.targets_added = list(_ALL_TARGET_NAMES)
        if not dry_run:
            makefile_path = repo_root / "Makefile"
            makefile_path.write_text(content)

    return result


def scaffold_makefiles(repo_root: Path, dry_run: bool = False) -> MultiScaffoldResult:
    """Scaffold Makefiles for each discovered project path in a repository."""
    out = MultiScaffoldResult()
    for project_path in discover_project_paths(repo_root):
        result = scaffold_makefile(project_path, dry_run=dry_run)
        if result.language == "unknown":
            continue
        rel = str(project_path.relative_to(repo_root)) or "."
        out.results[rel] = result
    return out
