"""Generate the documentation-coverage matrix.

Produces docs/arch/generated/coverage_matrix.md — an auto-regenerable
version of the hand-curated docs/arch/coverage_matrix.md.

Sections emitted
----------------
- Section 1: Loops (N × 7) — one row per BaseBackgroundLoop subclass.
- Section 2: Ports (9 × 7) — one row per *Port Protocol.
- Section 3: hand-curated prose; a cross-reference note is emitted instead.

Column predicates
-----------------
See constants ADR_EXCLUDED_REFS and STANDARD_CATEGORY_ALIASES below. The
predicate implementations mirror the spec recorded in the hand-curated
baseline (docs/arch/coverage_matrix.md, §"Column criteria").

Cell vocabulary
---------------
✅  present / covered
⚠️  partial (wiki index only, etc.)
❌  absent / missing
N/A column not applicable for this row type
"""

from __future__ import annotations

import re
from pathlib import Path

from arch._models import LoopInfo, PortInfo

# ---------------------------------------------------------------------------
# Constants — edit here to fix false-negatives, not inside predicate logic
# ---------------------------------------------------------------------------

#: ADR files that contain roll-call mentions of every loop and must not count
#: as substantive coverage.
ADR_EXCLUDED_REFS: tuple[str, ...] = (
    "0044-hydraflow-principles.md",
    "0049-trust-loop-kill-switch-convention.md",
)

#: Wiki files that count only as an index, not substantive coverage.
WIKI_EXCLUDED_FILES: tuple[str, ...] = (
    "index.md",
    "index.json",
)

#: Loop-name → alias list for grep variants.  Add entries when an extractor
#: would otherwise false-negative because the loop is referenced by a
#: non-canonical name in prose.
LOOP_ALIASES: dict[str, list[str]] = {
    # Example: "SomeLongLoop": ["the-short-name", "ShortName"],
}

PORT_ALIASES: dict[str, list[str]] = {
    # Example: "SomePort": ["some-port"],
}

#: Mapping from functional-area standard-category keyword to the phrase that
#: appears in docs/standards/**/*.md roll-up rules.
STANDARD_CATEGORY_MAP: dict[str, str] = {
    "caretaking": "caretaker loop",
    "trust_fleet": "trust fleet",
    "auto_agent": "Auto-Agent",
    "quality_gates": "CI monitor",
}

# ---------------------------------------------------------------------------
# Snake-case helper (acronym-aware, matches the spec formula)
# ---------------------------------------------------------------------------


def _snake(name: str) -> str:
    """Convert a CamelCase loop name to snake_case, handling acronyms.

    Mirrors the spec formula:
        re.sub(r"([A-Z]+)([A-Z][a-z])", r"\\1_\\2", name)
        then re.sub(r"([a-z\\d])([A-Z])", r"\\1_\\2", s).lower()

    >>> _snake("CIMonitorLoop")
    'ci_monitor_loop'
    >>> _snake("PRUnstickerLoop")
    'pr_unsticker_loop'
    >>> _snake("ADRReviewerLoop")
    'adr_reviewer_loop'
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


def _adr_check(name: str, adr_dir: Path, aliases: list[str]) -> str:
    """Return ✅ refs or ❌.

    Greps all docs/adr/*.md for the name (or any alias), excluding the
    ADR_EXCLUDED_REFS roll-call files. Returns ✅ with ADR number(s) if
    found; ❌ otherwise.
    """
    terms = [name] + aliases
    adr_files = sorted(adr_dir.glob("*.md"))
    hits: list[str] = []
    for adr_file in adr_files:
        if adr_file.name in ADR_EXCLUDED_REFS:
            continue
        try:
            text = adr_file.read_text()
        except OSError:
            continue
        pattern = "|".join(re.escape(t) for t in terms)
        if re.search(rf"\b(?:{pattern})\b", text):
            # Extract ADR number from filename e.g. "0029-foo.md" → "0029"
            m = re.match(r"(\d+)-", adr_file.name)
            if m:
                hits.append(m.group(1))
    if hits:
        return "✅ [" + ", ".join(hits) + "]"
    return "❌"


def _wiki_check(name: str, wiki_dir: Path, aliases: list[str]) -> str:
    """Return ✅ refs, ⚠️ (index-only), or ❌.

    If a substantive wiki file matches → ✅ with filename.
    If only the index matches → ⚠️ partial.
    """
    terms = [name] + aliases
    pattern = "|".join(re.escape(t) for t in terms)
    # Include all *.md and *.json recursively under wiki_dir so that
    # subdirectories (e.g. terms/) are covered.
    wiki_files: list[Path] = sorted(wiki_dir.rglob("*.md")) + sorted(
        wiki_dir.rglob("*.json")
    )

    substantive_hits: list[str] = []
    index_hit = False

    for wiki_file in wiki_files:
        try:
            text = wiki_file.read_text()
        except OSError:
            continue
        if not re.search(rf"\b(?:{pattern})\b", text):
            continue
        if wiki_file.name in WIKI_EXCLUDED_FILES:
            index_hit = True
        else:
            substantive_hits.append(wiki_file.name)

    if substantive_hits:
        return "✅ [" + ", ".join(sorted(set(substantive_hits))) + "]"
    if index_hit:
        return "⚠️ index-only"
    return "❌"


def _generated_check(name: str, loops_md: Path) -> str:
    """Return ✅ or ❌ based on whether the loop appears in loops.md with non-— Tick AND Kill cells."""
    if not loops_md.exists():
        return "❌"
    try:
        text = loops_md.read_text()
    except OSError:
        return "❌"
    # Table rows look like:
    # | **LoopName** | `module` | 300 | `KILL_VAR` | events | adrs |
    for line in text.splitlines():
        if f"**{name}**" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        # cols[0]="" cols[1]=**name** cols[2]=module cols[3]=tick cols[4]=kill ...
        if len(cols) < 6:
            continue
        tick = cols[3]
        kill = cols[4]
        if tick != "—" and kill != "—":
            return "✅ loops.md"
        return "❌"
    return "❌"


def _ports_generated_check(name: str, ports_md: Path) -> str:
    """Return ✅ if port appears in ports.md."""
    if not ports_md.exists():
        return "❌"
    try:
        text = ports_md.read_text()
    except OSError:
        return "❌"
    if f"### {name}" in text:
        return "✅ ports.md"
    return "❌"


def _build_area_map(fa_path: Path) -> dict[str, str]:
    """Parse functional_areas.yml and return {loop_name: area_key}.

    Returns an empty dict if the YAML doesn't exist or can't be parsed.
    Avoids importing arch._functional_areas_schema so this module has
    no runtime dependency beyond stdlib + pydantic.
    """
    if not fa_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]  # optional dep
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(fa_path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    result: dict[str, str] = {}
    for area_key, area_val in (data or {}).get("areas", {}).items():
        for loop_name in (area_val or {}).get("loops", []) or []:
            result[str(loop_name)] = area_key
        for port_name in (area_val or {}).get("ports", []) or []:
            result[str(port_name)] = area_key
    return result


#: Mapping from functional-area key → whether standards cover that category.
#: The factory_operation README explicitly binds "caretaker loop" as a standard.
#: Other area keys are ❌ unless a standard explicitly names them.
AREA_STANDARD_COVERAGE: dict[str, str] = {
    "caretaking": "caretaker loop",
    # trust_fleet, quality_gates, auto_agent have no matching standard phrase yet
}


def _standard_check_with_area(
    name: str,
    standards_dir: Path,
    fa_path: Path,
    area_map: dict[str, str],
    aliases: list[str],
) -> str:
    """Return ✅ (category) or ❌.

    Two-pass strategy:
    1. Direct grep for `name` in docs/standards/**/*.md.
    2. If the loop/port belongs to an area key that has known standards
       coverage, return ✅ (area phrase).
    """
    terms = [name] + aliases
    pattern = "|".join(re.escape(t) for t in terms)
    # Pass 1: direct name grep
    for md in sorted(standards_dir.rglob("*.md")):
        try:
            text = md.read_text()
        except OSError:
            continue
        if re.search(rf"\b(?:{pattern})\b", text):
            return f"✅ {md.name}"
    # Pass 2: area-based roll-up
    area_key = area_map.get(name)
    if area_key and area_key in AREA_STANDARD_COVERAGE:
        phrase = AREA_STANDARD_COVERAGE[area_key]
        return f"✅ ({phrase})"
    return "❌"


def _unit_check(name: str, tests_dir: Path) -> str:
    """Return ✅ with filename or ❌."""
    snake = _snake(name)
    # Look for test_<snake>*.py in tests/ (non-recursive for speed; also rglob)
    for pattern in (f"test_{snake}*.py", f"test_{snake}_*.py"):
        for candidate in sorted(tests_dir.glob(pattern)):
            if candidate.stat().st_size > 0:
                return f"✅ `{candidate.name}`"
    # Try rglob in case tests are nested
    for candidate in sorted(tests_dir.rglob(f"test_{snake}*.py")):
        if candidate.stat().st_size > 0:
            return f"✅ `{candidate.name}`"
    return "❌"


def _scenario_check(name: str, registrations_py: Path, scenarios_dir: Path) -> str:
    """Return ✅ / ⚠️ / ❌.

    ✅ iff name is in loop_registrations.py AND a scenario file references it.
    ⚠️ iff in registrations but no scenario file references it.
    ❌ otherwise.
    """
    if not registrations_py.exists():
        return "❌"
    try:
        reg_text = registrations_py.read_text()
    except OSError:
        return "❌"

    # Check registration: the snake-case key appears as a dict key string
    snake = _snake(name)
    # Registrations use keys like "ci_monitor", "stale_issue_gc" — strip _loop suffix
    key_variants = [snake, snake.removesuffix("_loop")]
    in_catalog = any(f'"{k}"' in reg_text for k in key_variants)

    if not in_catalog:
        return "❌"

    # Check scenario files reference the CamelCase name
    found_in_scenario = False
    for scenario_file in sorted(scenarios_dir.rglob("*.py")):
        # Skip the catalog itself
        if scenario_file.name in ("loop_registrations.py", "loop_catalog.py"):
            continue
        try:
            s_text = scenario_file.read_text()
        except OSError:
            continue
        if name in s_text:
            found_in_scenario = True
            break

    if found_in_scenario:
        return "✅ in catalog"
    return "⚠️ in catalog (no scenario file)"


def _sandbox_check(name: str, sandbox_scenarios_dir: Path) -> str:
    """Return ✅ with filename or ❌."""
    for scenario_file in sorted(sandbox_scenarios_dir.rglob("*.py")):
        try:
            text = scenario_file.read_text()
        except OSError:
            continue
        if name in text:
            return f"✅ `{scenario_file.name}`"
    return "❌"


def _port_fake_check(port: PortInfo, fakes_dir: Path) -> str:
    """Return ✅ or ❌ for the Fake<PortStem> adapter."""
    if port.fake is not None:
        return f"✅ `{port.fake.name}`"
    # Also check fakes_dir directly (in case extractor missed it)
    port_stem = port.name.removesuffix("Port")
    for fake_file in sorted(fakes_dir.rglob("*.py")):
        try:
            text = fake_file.read_text()
        except OSError:
            continue
        if re.search(rf"\bFake{re.escape(port_stem)}\b", text):
            return f"✅ `Fake{port_stem}` (fakes/)"
    return "❌"


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _loop_row(
    info: LoopInfo,
    *,
    adr_dir: Path,
    wiki_dir: Path,
    standards_dir: Path,
    fa_path: Path,
    area_map: dict[str, str],
    tests_dir: Path,
    scenarios_dir: Path,
    registrations_py: Path,
    sandbox_scenarios_dir: Path,
    loops_md: Path,
) -> str:
    name = info.name
    aliases = LOOP_ALIASES.get(name, [])
    adr = _adr_check(name, adr_dir, aliases)
    wiki = _wiki_check(name, wiki_dir, aliases)
    generated = _generated_check(name, loops_md)
    standard = _standard_check_with_area(
        name, standards_dir, fa_path, area_map, aliases
    )
    unit = _unit_check(name, tests_dir)
    scenario = _scenario_check(name, registrations_py, scenarios_dir)
    sandbox = _sandbox_check(name, sandbox_scenarios_dir)
    return f"| `{name}` | {adr} | {wiki} | {generated} | {standard} | {unit} | {scenario} | {sandbox} |"


def _port_row(
    info: PortInfo,
    *,
    adr_dir: Path,
    wiki_dir: Path,
    standards_dir: Path,
    fa_path: Path,
    area_map: dict[str, str],
    tests_dir: Path,
    fakes_dir: Path,
    ports_md: Path,
) -> str:
    name = info.name
    aliases = PORT_ALIASES.get(name, [])
    adr = _adr_check(name, adr_dir, aliases)
    wiki = _wiki_check(name, wiki_dir, aliases)
    generated = _ports_generated_check(name, ports_md)
    standard = _standard_check_with_area(
        name, standards_dir, fa_path, area_map, aliases
    )
    fake = _port_fake_check(info, fakes_dir)
    cassette = "N/A (per-adapter, ADR-0047)"
    contract = "N/A (per-adapter, ADR-0047)"
    return f"| `{name}` | {adr} | {wiki} | {generated} | {standard} | {fake} | {cassette} | {contract} |"


# ---------------------------------------------------------------------------
# Top-level render function
# ---------------------------------------------------------------------------

_HEADER = "# Coverage Matrix\n\n"
_PREAMBLE = """\
<!-- generated by arch.generators.coverage_matrix; do not hand-edit -->
<!-- Source of truth for Sections 1 & 2. Section 3 is hand-curated. -->
<!-- See docs/arch/coverage_matrix.md for the Phases table. -->

Regenerated from the live source tree. Cell vocabulary: ✅ covered, ⚠️ partial, ❌ missing, N/A not applicable.

"""

_LOOPS_HEAD = """\
## Section 1: Loops

| Loop | ADR | Wiki | Generated | Standard | Unit | Scenario | Sandbox |
|---|---|---|---|---|---|---|---|
"""

_PORTS_PREAMBLE = """\

## Section 2: Ports

Cassette and Contract columns are N/A for all ports (ADR-0047 contracts are
per-adapter, not per-port).

| Port | ADR | Wiki | Generated | Standard | Fake | Cassette | Contract |
|---|---|---|---|---|---|---|---|
"""

_PHASES_NOTE = """\

## Section 3: Factory phases

Section 3 contains hand-curated prose (Loops driving it / Escalation path /
HITL trigger). It is not regenerable from source and is maintained in
`docs/arch/coverage_matrix.md` (the hand-curated baseline document).

"""

_FOOTER = "\n{{ARCH_FOOTER}}\n"


def render_coverage_matrix(
    loops: list[LoopInfo],
    ports: list[PortInfo],
    *,
    repo_root: Path,
) -> str:
    """Return the full coverage-matrix markdown string.

    Parameters
    ----------
    loops:
        Output of ``arch.extractors.loops.extract_loops``.
    ports:
        Output of ``arch.extractors.ports.extract_ports``.
    repo_root:
        Absolute path to the repository root. Used to locate docs/,
        tests/, and src/ trees.
    """
    repo_root = Path(repo_root).resolve()

    adr_dir = repo_root / "docs/adr"
    wiki_dir = repo_root / "docs/wiki"
    standards_dir = repo_root / "docs/standards"
    fa_path = repo_root / "docs/arch/functional_areas.yml"
    tests_dir = repo_root / "tests"
    registrations_py = repo_root / "tests/scenarios/catalog/loop_registrations.py"
    scenarios_dir = repo_root / "tests/scenarios"
    sandbox_scenarios_dir = repo_root / "tests/sandbox_scenarios/scenarios"
    loops_md = repo_root / "docs/arch/generated/loops.md"
    ports_md = repo_root / "docs/arch/generated/ports.md"
    fakes_dir = repo_root / "src/mockworld/fakes"

    area_map = _build_area_map(fa_path)
    sorted_loops = sorted(loops, key=lambda info: info.name)
    sorted_ports = sorted(ports, key=lambda p: p.name)

    loop_rows = "\n".join(
        _loop_row(
            info,
            adr_dir=adr_dir,
            wiki_dir=wiki_dir,
            standards_dir=standards_dir,
            fa_path=fa_path,
            area_map=area_map,
            tests_dir=tests_dir,
            registrations_py=registrations_py,
            scenarios_dir=scenarios_dir,
            sandbox_scenarios_dir=sandbox_scenarios_dir,
            loops_md=loops_md,
        )
        for info in sorted_loops
    )

    port_rows = "\n".join(
        _port_row(
            info,
            adr_dir=adr_dir,
            wiki_dir=wiki_dir,
            standards_dir=standards_dir,
            fa_path=fa_path,
            area_map=area_map,
            tests_dir=tests_dir,
            fakes_dir=fakes_dir,
            ports_md=ports_md,
        )
        for info in sorted_ports
    )

    body = (
        _HEADER
        + _PREAMBLE
        + _LOOPS_HEAD
        + loop_rows
        + _PORTS_PREAMBLE
        + port_rows
        + _PHASES_NOTE
        + _FOOTER
    )
    return body
