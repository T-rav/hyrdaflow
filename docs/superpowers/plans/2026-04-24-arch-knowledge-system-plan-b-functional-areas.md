# Architecture Knowledge System — Plan B: Functional Areas + Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layer the conceptual "what does this machine do?" view on top of Plan A's mechanical truth. Adds the **9th** generated artifact (Functional Area Map), the curated YAML that drives it, schema + coverage tests, ADR-0001 amendment, deletion of the 12 stale `.likec4` files, the `docs/architecture/` → `docs/arch/` rename, CLAUDE.md update, and a `.gitignore` fix for `.claude/worktrees/`.

**Architecture:** A new pure-function generator (`src/arch/generators/functional_areas.py`) reads `docs/arch/functional_areas.yml` (Pydantic-validated) and joins it with the live extractor outputs from Plan A. Output is one Mermaid `flowchart LR` with `subgraph` clusters per area, plus a per-area detail table. A coverage test (`tests/architecture/test_functional_area_coverage.py`) fails if a loop or port discovered by the AST extractors is unassigned to any area — preventing silent drift as new loops land.

**Tech Stack:** Python 3.11, Pydantic v2 (already in deps), PyYAML (already pinned at `>=6.0` in test extras — promoted to main deps in Task 1). No new third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md` — §3 (curated layer), §4.2 (`functional_areas.py`), §4.3 (Functional Area Map full), §7 (coverage test, schema test), §8 (migration steps 1-8), §11 (malformed YAML defense).

**Spec coverage map:**

| Spec requirement | Tasks |
|---|---|
| Promote PyYAML to main deps | Task 1 |
| Pydantic schema for `functional_areas.yml` | Task 2 |
| `tests/architecture/test_functional_areas_schema.py` (§7) | Task 3 |
| Author `docs/arch/functional_areas.yml` (§4.3, §8 step 4) | Task 4 |
| `functional_areas.py` generator (§4.2, §4.3) | Task 5 |
| `tests/architecture/test_functional_area_coverage.py` (§7) | Task 6 |
| Wire into `src/arch/runner.py` | Task 7 |
| `make arch-validate` target (§11 mitigation) | Task 8 |
| Pre-commit hook for `functional_areas.yml` (§11 mitigation) | Task 9 |
| Move `docs/architecture/` → `docs/arch/` (§8 step 2) | Task 10 |
| Delete 12 stale `.likec4` files (§8 step 1) | Task 11 |
| Amend ADR-0001 (§8 step 5) | Task 12 |
| Remove xfail from `test_loop_count_matches_adr0001` | Task 13 |
| Update CLAUDE.md Knowledge Lookup (§8 steps 6-7) | Task 14 |
| Add `.claude/worktrees/` to `.gitignore` (§8 step 8) | Task 15 |
| Re-emit baseline (now 9 files) and commit | Task 16 |

**Out of scope (delivered by Plan C):**
- DiagramLoop (L24) and its kill-switch
- `arch-regen.yml` GitHub workflow
- `pages-deploy.yml` workflow + MkDocs Material config
- Pages publishing
- The functional area coverage *issue* that DiagramLoop opens when it finds an unassigned loop (Plan B delivers the *test*; Plan C delivers the *autonomous loop reaction*)

**Prerequisites:** Plan A must be merged. The branch this plan executes on assumes `src/arch/` exists, `make arch-regen` works, and `docs/arch/generated/` has the 8-artifact baseline committed.

---

## Task 1: Promote PyYAML to runtime dependency

**Files:**
- Modify: `pyproject.toml`

PyYAML is currently pinned at `>=6.0` only inside the `[project.optional-dependencies].test` block. The `functional_areas.py` generator runs in production (called by the runner, by the DiagramLoop in Plan C, and by the CI guard), so it must be a main runtime dep.

- [ ] **Step 1: Move the pin**

In `pyproject.toml`, remove `pyyaml>=6.0` from the `test` extras list and add it under `[project] dependencies`:

```toml
[project]
# ...existing...
dependencies = [
    "pydantic>=2.0.0",
    "docker>=7.0.0",
    "fastapi>=0.110.0",
    "uvicorn>=0.30.0",
    "websockets>=12.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0",
    "python-ulid>=3.0.0",
    "sentry-sdk[fastapi]>=2.0",
    "pyyaml>=6.0",   # ← added
]
```

- [ ] **Step 2: Verify install resolves**

```bash
pip install -e '.[dev,test]'
python -c "import yaml; print(yaml.__version__)"
```

Expected: prints a version ≥ 6.0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: promote pyyaml to runtime dep for arch.generators.functional_areas"
```

---

## Task 2: Pydantic schema for `functional_areas.yml`

**Files:**
- Create: `src/arch/_functional_areas_schema.py`

Underscore prefix marks it as a private helper inside `src/arch/` (siblings: `_models.py`). The schema is consumed by Tasks 3, 5, 6, and 8.

- [ ] **Step 1: Write the schema**

```python
# src/arch/_functional_areas_schema.py
"""Pydantic schema for docs/arch/functional_areas.yml.

The YAML is the only hand-curated input to the architecture knowledge
system. Every load goes through this schema so a typo or missing field
fails fast with a useful error rather than producing a confusing diff
in the generated Markdown.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FunctionalArea(BaseModel):
    label: str = Field(min_length=1, description="Display name shown on the site.")
    description: str = Field(min_length=1, description="One-paragraph summary of what this area does.")
    loops: list[str] = Field(default_factory=list, description="Class names of loops belonging to this area.")
    ports: list[str] = Field(default_factory=list, description="Class names of Ports belonging to this area.")
    modules: list[str] = Field(default_factory=list, description="Path globs (relative to repo root) of modules belonging to this area.")
    related_adrs: list[str] = Field(default_factory=list, description="ADR ids in 'NNNN' or 'ADR-NNNN' form.")

    @field_validator("related_adrs")
    @classmethod
    def _normalize_adr_ids(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for s in v:
            s = s.strip()
            if not s:
                continue
            if not s.startswith("ADR-"):
                s = f"ADR-{s.zfill(4)}"
            out.append(s)
        return out


class FunctionalAreas(BaseModel):
    """Top-level structure: `areas: {key: FunctionalArea}`."""
    areas: dict[str, FunctionalArea]

    @field_validator("areas")
    @classmethod
    def _at_least_one_area(cls, v: dict[str, FunctionalArea]) -> dict[str, FunctionalArea]:
        if not v:
            raise ValueError("functional_areas.yml must declare at least one area")
        return v


def load_functional_areas(yaml_path: "Path") -> FunctionalAreas:  # noqa: F821 — Path forward-ref to avoid circular import
    import yaml
    from pathlib import Path

    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"{yaml_path} does not exist")
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{yaml_path}: top-level must be a mapping")
    return FunctionalAreas.model_validate(raw)
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
python -c "from src.arch._functional_areas_schema import FunctionalAreas, load_functional_areas; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/arch/_functional_areas_schema.py
git commit -m "feat(arch): Pydantic schema for functional_areas.yml"
```

---

## Task 3: Schema validation test

**Files:**
- Create: `tests/architecture/test_functional_areas_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_functional_areas_schema.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.arch._functional_areas_schema import FunctionalAreas, load_functional_areas


def test_schema_accepts_minimum_valid_doc(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text(
        "areas:\n"
        "  orchestration:\n"
        "    label: Orchestration\n"
        "    description: The plan→implement→review pipeline.\n"
    )
    fa = load_functional_areas(p)
    assert "orchestration" in fa.areas
    assert fa.areas["orchestration"].loops == []


def test_schema_rejects_missing_label(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text(
        "areas:\n"
        "  orchestration:\n"
        "    description: Some text.\n"
    )
    with pytest.raises(ValidationError):
        load_functional_areas(p)


def test_schema_rejects_empty_areas(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text("areas: {}\n")
    with pytest.raises(ValidationError):
        load_functional_areas(p)


def test_schema_normalizes_adr_ids(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text(
        "areas:\n"
        "  caretaking:\n"
        "    label: Caretaking\n"
        "    description: x\n"
        "    related_adrs: ['29', '0049', 'ADR-0032']\n"
    )
    fa = load_functional_areas(p)
    assert fa.areas["caretaking"].related_adrs == ["ADR-0029", "ADR-0049", "ADR-0032"]


def test_real_yaml_passes_schema(real_repo_root: Path):
    """Once Task 4 commits docs/arch/functional_areas.yml, this lights up."""
    p = real_repo_root / "docs/arch/functional_areas.yml"
    if not p.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored (Task 4)")
    fa = load_functional_areas(p)
    assert len(fa.areas) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_functional_areas_schema.py -v
```

Expected: 4 pass (the synthetic ones), 1 skip (real yaml absent).

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_functional_areas_schema.py
git commit -m "test(arch): functional_areas.yml schema validation tests"
```

---

## Task 4: Author `docs/arch/functional_areas.yml`

**Files:**
- Create: `docs/arch/functional_areas.yml`

This is the single biggest hand-curation step in the project. Every loop and Port currently in the codebase must be assigned to exactly one area. The shape below is the v1 starter; areas can be added/split later by amending the file.

- [ ] **Step 1: Discover the live loop and port set**

Using Plan A's runner output:

```bash
python -m src.arch.runner --emit
# Read the loop list from the freshly-generated artifact
grep -E "^\| \*\*[A-Z]" docs/arch/generated/loops.md | awk -F'\\*\\*' '{print $2}' | sort -u
```

Save the output to a scratch file. You'll cross-reference it when building the YAML.

Likewise for ports:

```bash
grep -E "^### [A-Z]" docs/arch/generated/ports.md | awk '{print $2}' | sort -u
```

- [ ] **Step 2: Author the YAML**

Create `docs/arch/functional_areas.yml`:

```yaml
# docs/arch/functional_areas.yml
#
# Hand-curated: each loop and Port must appear in exactly one area.
# `tests/architecture/test_functional_area_coverage.py` enforces.
# Schema: src/arch/_functional_areas_schema.py

areas:
  orchestration:
    label: Orchestration
    description: >
      The plan → implement → review pipeline driving each issue from
      `hydraflow-ready` through merge. Owns the agent-runner stack and
      the runtime state machine.
    loops:
      - RunLoop
      - HITLLoop
      - GoalDrivenLoop
      - ConversationLoop
      - PRUnstickerLoop
    ports:
      - AgentPort
      - WorkspacePort
    modules:
      - src/orchestrator/**
      - src/agent_runner.py
      - src/planner_runner.py
      - src/review_runner.py
    related_adrs: ['0001', '0004', '0011', '0012', '0029']

  caretaking:
    label: Caretaking
    description: >
      Autonomous background loops (L9–L24) that maintain the system
      without human input — wiki freshness, stale-issue GC, ADR review,
      retrospective digestion, security patching, etc. Per ADR-0029.
    loops:
      - ADRReviewerLoop
      - RetrospectiveLoop
      - EpicSweeperLoop
      - SecurityPatchLoop
      - DiagnosticLoop
      - EpicMonitorLoop
      - GitHubCacheLoop
      - RepoWikiLoop
      - ReportIssueLoop
      - RunsGCLoop
      - SentryLoop
      - StagingPromotionLoop
      - StaleIssueLoop
      - WorkspaceGCLoop
      - DependabotMergeLoop
      - HealthMonitorLoop
      - CodeGroomingLoop
      - SkillPromptEvalLoop
      - WikiRotDetectorLoop
    related_adrs: ['0029', '0049']

  quality_gates:
    label: Quality Gates
    description: >
      Post-implementation skill chain that catches bad diffs before
      they merge — diff sanity, scope check, plan compliance, test
      adequacy, and the LLM-as-judge corpus that hardens them.
    loops:
      - DiffSanityLoop
      - ScopeCheckLoop
      - PlanComplianceLoop
      - TestAdequacyLoop
      - QualityFixLoop
      - PreQualityReviewLoop
      - CIMonitorLoop
    related_adrs: ['0023', '0035', '0044']

  goal_driven_dev:
    label: Goal-Driven Development
    description: >
      The Discover → Shape → Implement track for vague work that the
      orchestrator can't take directly. OpenClaw canvas + product-phase
      adversarial gate.
    loops: []
    related_adrs: ['0031']

  state_persistence:
    label: State & Persistence
    description: >
      State tracking, event bus, session logs, and the on-disk layout.
    loops: []
    ports:
      - StateBackendPort
    related_adrs: ['0021', '0028']

  hexagonal_boundaries:
    label: Hexagonal Boundaries
    description: >
      The Port/Adapter seam between domain runtime and the outside
      world (GitHub, git, Docker, the LLM, the filesystem).
    loops: []
    ports:
      - PRPort
      - IssueStorePort
      - IssueFetcherPort
      - ReviewInsightStorePort
      - ObservabilityPort
      - RouteBackCounterPort
    related_adrs: ['0006', '0010', '0047']

  trust_fleet:
    label: Trust Fleet
    description: >
      The trust-architecture hardening fleet — RC promotion gate,
      staging bisect, contract refresh, principles audit, flake
      tracker, corpus learning, fake coverage auditor, RC budget,
      meta-observability.
    loops:
      - StagingBisectLoop
      - ContractRefreshLoop
      - PrinciplesAuditLoop
      - FlakeTrackerLoop
      - CorpusLearningLoop
      - FakeCoverageAuditorLoop
      - RCBudgetLoop
      - TrustFleetSanityLoop
    related_adrs: ['0042', '0045', '0048']

  test_harness:
    label: Test Harness (MockWorld)
    description: >
      The scenario-ring test harness — `MockWorld` aggregates 13 fakes
      that emulate every external dependency and integration target.
      Per ADR-0022 (MockWorld) and ADR-0047 (fake-adapter contract
      testing).
    loops: []
    modules:
      - tests/scenarios/fakes/**
      - tests/scenarios/builders/**
    related_adrs: ['0022', '0047']

  dashboard:
    label: Dashboard
    description: >
      The operator-facing FastAPI + React dashboard for observing the
      fleet and overriding routing decisions.
    loops: []
    modules:
      - src/ui/**
      - src/dashboard*.py
      - src/routes/**
    related_adrs: ['0007', '0008', '0009', '0030']

  arch_knowledge:
    label: Architecture Knowledge
    description: >
      The self-documenting layer — the runner, extractors, generators,
      DiagramLoop (Plan C), CI guard, and Pages site that publishes
      the live architectural truth alongside ADRs and the wiki.
    loops:
      - DiagramLoop  # Plan C; safe to declare here ahead of time so
                    # coverage doesn't immediately fail when L24 lands.
    modules:
      - src/arch/**
    related_adrs: ['0029', '0032']
```

**Cross-check.** After authoring, run:

```bash
python -c "
from pathlib import Path
from src.arch._functional_areas_schema import load_functional_areas
from src.arch.extractors.loops import extract_loops
from src.arch.extractors.ports import extract_ports

fa = load_functional_areas(Path('docs/arch/functional_areas.yml'))
loops = {l.name for l in extract_loops(Path('src'))}
ports = {p.name for p in extract_ports(src_dir=Path('src'), fakes_dir=Path('tests/scenarios/fakes'))}

assigned_loops = set()
assigned_ports = set()
for a in fa.areas.values():
    assigned_loops.update(a.loops)
    assigned_ports.update(a.ports)

missing_loops = loops - assigned_loops
extra_loops = assigned_loops - loops - {'DiagramLoop'}  # DiagramLoop preassigned for Plan C
missing_ports = ports - assigned_ports
extra_ports = assigned_ports - ports

print('MISSING LOOPS (in code, not in YAML):', sorted(missing_loops))
print('EXTRA LOOPS (in YAML, not in code):', sorted(extra_loops))
print('MISSING PORTS (in code, not in YAML):', sorted(missing_ports))
print('EXTRA PORTS (in YAML, not in code):', sorted(extra_ports))
"
```

Iterate on the YAML until all four lists are empty (except `DiagramLoop` in extras, which is intentional pre-assignment for Plan C).

- [ ] **Step 3: Verify the schema test now picks up the real file**

```bash
pytest tests/architecture/test_functional_areas_schema.py::test_real_yaml_passes_schema -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add docs/arch/functional_areas.yml
git commit -m "feat(arch): initial functional_areas.yml curation"
```

---

## Task 5: `functional_areas` generator

**Files:**
- Create: `src/arch/generators/functional_areas.py`
- Test: `tests/architecture/test_generator_functional_areas.py`

The generator reads the YAML + the loop and port extractor outputs, joins them, and emits one Mermaid diagram with `subgraph` clusters per area + a per-area details section.

**Important:** unlike Plan A's generators (which are pure functions of typed model objects), this generator takes a YAML path AND extractor outputs. Keep the rendering pure: load+validate the YAML in a separate function, pass typed objects to the renderer.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_functional_areas.py
from src.arch._functional_areas_schema import FunctionalArea, FunctionalAreas
from src.arch._models import LoopInfo, PortInfo
from src.arch.generators.functional_areas import render_functional_areas


def test_renders_subgraph_per_area_with_members():
    fa = FunctionalAreas(areas={
        "orchestration": FunctionalArea(
            label="Orchestration",
            description="Plan-implement-review pipeline.",
            loops=["RunLoop"],
            ports=["AgentPort"],
            related_adrs=["ADR-0001"],
        ),
        "caretaking": FunctionalArea(
            label="Caretaking",
            description="Autonomous background work.",
            loops=["RepoWikiLoop"],
            related_adrs=["ADR-0029"],
        ),
    })
    loops = [
        LoopInfo(name="RunLoop", module="src.run_loop", source_path="src/run_loop.py"),
        LoopInfo(name="RepoWikiLoop", module="src.repo_wiki_loop", source_path="src/repo_wiki_loop.py"),
    ]
    ports = [
        PortInfo(name="AgentPort", module="src.ports", source_path="src/ports.py", methods=["start"]),
    ]
    md = render_functional_areas(fa, loops=loops, ports=ports)

    assert "# Functional Area Map" in md
    assert "Orchestration" in md
    assert "Caretaking" in md
    assert "RunLoop" in md
    assert "RepoWikiLoop" in md
    assert "subgraph orchestration" in md
    assert "subgraph caretaking" in md
    # Per-area detail section
    assert "## Orchestration" in md
    assert "## Caretaking" in md
    # ADR refs surface
    assert "ADR-0001" in md
    assert "ADR-0029" in md


def test_byte_stable_under_unsorted_areas():
    """Areas render in YAML insertion order (`dict` preserves order in Python 3.7+).

    Within each area, loops/ports are sorted alphabetically.
    """
    fa = FunctionalAreas(areas={
        "z_area": FunctionalArea(label="Z", description="z", loops=["BLoop", "ALoop"]),
        "a_area": FunctionalArea(label="A", description="a", loops=["DLoop", "CLoop"]),
    })
    loops = [LoopInfo(name=n, module="m", source_path="p") for n in ("ALoop", "BLoop", "CLoop", "DLoop")]
    md = render_functional_areas(fa, loops=loops, ports=[])
    # First mention of "ALoop" (member of z_area) comes after first mention of "DLoop" (member of a_area)?
    # Actually: a_area declared SECOND in the YAML, so z_area renders first.
    z_pos = md.index("subgraph z_area")
    a_pos = md.index("subgraph a_area")
    assert z_pos < a_pos


def test_mentions_unknown_member_in_warning_section():
    """If the YAML names a loop/port the extractor didn't find, surface it.

    The coverage test (Task 6) is the actual gate; the generator just notes it.
    """
    fa = FunctionalAreas(areas={
        "x": FunctionalArea(label="X", description="x", loops=["GhostLoop"]),
    })
    md = render_functional_areas(fa, loops=[], ports=[])
    assert "GhostLoop" in md
    assert "⚠️" in md or "unknown" in md.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_functional_areas.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/functional_areas.py
"""Render the Functional Area Map: Mermaid clusters + per-area detail."""
from __future__ import annotations

from src.arch._functional_areas_schema import FunctionalAreas
from src.arch._models import LoopInfo, PortInfo

_HEADER = "# Functional Area Map\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.functional_areas; do not hand-edit -->\n\n"
    "Top-level conceptual view of HydraFlow. Each cluster is a "
    "**functional area** — a coherent piece of what this machine does, "
    "curated in [`docs/arch/functional_areas.yml`](../functional_areas.yml). "
    "The loops/ports/modules inside each cluster are auto-joined from "
    "the live AST extractors. New loops or ports must be assigned to an "
    "area or `tests/architecture/test_functional_area_coverage.py` fails.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _safe(name: str) -> str:
    """Mermaid identifier: alphanumeric + underscore."""
    return "".join(c if c.isalnum() else "_" for c in name)


def _mermaid(fa: FunctionalAreas, *, known_loops: set[str], known_ports: set[str]) -> str:
    lines = ["```mermaid", "flowchart LR"]
    for key, area in fa.areas.items():
        lines.append(f'    subgraph {key}["{area.label}"]')
        for ln in sorted(area.loops):
            tag = "" if ln in known_loops else ":::unknown"
            lines.append(f"        {_safe(key)}_{_safe(ln)}([{ln}]){tag}")
        for pn in sorted(area.ports):
            tag = "" if pn in known_ports else ":::unknown"
            lines.append(f"        {_safe(key)}_{_safe(pn)}[/{pn}/]{tag}")
        lines.append("    end")
    lines.append("    classDef unknown stroke:#c00,stroke-width:2px,stroke-dasharray:4 2;")
    lines.append("```")
    return "\n".join(lines)


def _detail_section(key: str, area, *, loop_index: dict[str, LoopInfo],
                    port_index: dict[str, PortInfo]) -> str:
    lines = [f"## {area.label}", "", area.description.strip(), ""]
    if area.loops:
        lines.append("**Loops**\n")
        for ln in sorted(area.loops):
            info = loop_index.get(ln)
            if info:
                lines.append(f"- `{ln}` — `{info.module}`")
            else:
                lines.append(f"- ⚠️ `{ln}` — *unknown loop (not found by AST extractor)*")
        lines.append("")
    if area.ports:
        lines.append("**Ports**\n")
        for pn in sorted(area.ports):
            info = port_index.get(pn)
            if info:
                lines.append(f"- `{pn}` — `{info.module}`")
            else:
                lines.append(f"- ⚠️ `{pn}` — *unknown port*")
        lines.append("")
    if area.modules:
        lines.append("**Module globs**\n")
        for g in area.modules:
            lines.append(f"- `{g}`")
        lines.append("")
    if area.related_adrs:
        adrs = ", ".join(f"[{a}](../../adr/{a.removeprefix('ADR-')}-*.md)" for a in area.related_adrs)
        lines.append(f"**Related ADRs:** {adrs}\n")
    return "\n".join(lines)


def render_functional_areas(
    fa: FunctionalAreas,
    *,
    loops: list[LoopInfo],
    ports: list[PortInfo],
) -> str:
    loop_index = {l.name: l for l in loops}
    port_index = {p.name: p for p in ports}
    known_loops = set(loop_index)
    known_ports = set(port_index)

    body = _mermaid(fa, known_loops=known_loops, known_ports=known_ports) + "\n\n"
    body += "\n\n".join(
        _detail_section(k, a, loop_index=loop_index, port_index=port_index)
        for k, a in fa.areas.items()
    )
    return _HEADER + _PREAMBLE + body + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_functional_areas.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/functional_areas.py tests/architecture/test_generator_functional_areas.py
git commit -m "feat(arch): functional areas generator (Mermaid clusters)"
```

---

## Task 6: Coverage test

**Files:**
- Create: `tests/architecture/test_functional_area_coverage.py`

Every loop discovered by the AST extractor must appear in some area's `loops` list. Same for ports. Unassigned items fail with an actionable list. **This is the test that the DiagramLoop in Plan C reacts to** — when it fails, the loop opens an issue rather than a PR.

- [ ] **Step 1: Write the test**

```python
# tests/architecture/test_functional_area_coverage.py
from pathlib import Path

import pytest

from src.arch._functional_areas_schema import load_functional_areas
from src.arch.extractors.loops import extract_loops
from src.arch.extractors.ports import extract_ports


def test_every_loop_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored (Task 4)")

    fa = load_functional_areas(yaml_path)
    assigned = set()
    for area in fa.areas.values():
        assigned.update(area.loops)

    discovered = {l.name for l in extract_loops(real_repo_root / "src")}
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} loops are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml and add each to the appropriate area's `loops:` list."
        )


def test_every_port_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored")

    fa = load_functional_areas(yaml_path)
    assigned = set()
    for area in fa.areas.values():
        assigned.update(area.ports)

    discovered = {p.name for p in extract_ports(
        src_dir=real_repo_root / "src",
        fakes_dir=real_repo_root / "tests/scenarios/fakes",
    )}
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} ports are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml `ports:` lists."
        )


def test_no_phantom_assignments(real_repo_root: Path):
    """Loops/ports listed in the YAML but absent from code → fail.

    Exception: `DiagramLoop` is allowed to be pre-assigned ahead of Plan C.
    Once Plan C lands and DiagramLoop exists in src/, this exception is
    obsolete and can be removed (but leaving it is harmless).
    """
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored")

    fa = load_functional_areas(yaml_path)
    discovered_loops = {l.name for l in extract_loops(real_repo_root / "src")}
    discovered_ports = {p.name for p in extract_ports(
        src_dir=real_repo_root / "src",
        fakes_dir=real_repo_root / "tests/scenarios/fakes",
    )}
    PRE_ASSIGNED = {"DiagramLoop"}

    phantom_loops: list[tuple[str, str]] = []
    phantom_ports: list[tuple[str, str]] = []
    for key, area in fa.areas.items():
        for ln in area.loops:
            if ln not in discovered_loops and ln not in PRE_ASSIGNED:
                phantom_loops.append((key, ln))
        for pn in area.ports:
            if pn not in discovered_ports:
                phantom_ports.append((key, pn))

    if phantom_loops or phantom_ports:
        msg = []
        if phantom_loops:
            msg.append("Phantom loops (in YAML, not in code):")
            msg.extend(f"  {area}.loops: {ln}" for area, ln in phantom_loops)
        if phantom_ports:
            msg.append("Phantom ports:")
            msg.extend(f"  {area}.ports: {pn}" for area, pn in phantom_ports)
        pytest.fail(
            "\n".join(msg)
            + "\n\nFix: rename the YAML entry to match the live class name, or remove it."
        )
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/architecture/test_functional_area_coverage.py -v
```

Expected: 3 pass (your YAML in Task 4 already cross-checked against the live extractors). If any fail, iterate on `docs/arch/functional_areas.yml` until green.

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_functional_area_coverage.py
git commit -m "test(arch): functional area coverage (every loop/port assigned)"
```

---

## Task 7: Wire `functional_areas` into `runner.py`

**Files:**
- Modify: `src/arch/runner.py`
- Modify: `tests/architecture/test_runner.py`

The runner now produces 9 artifacts (was 8 in Plan A). `_compute_artifacts` calls the new generator with the joined inputs.

- [ ] **Step 1: Update the test (extend the expected file set)**

In `tests/architecture/test_runner.py`, change `expected = {...}` in `test_emit_writes_all_eight_artifacts`:

```python
def test_emit_writes_all_nine_artifacts(populated_repo: Path):
    # Add a minimal functional_areas.yml so the new generator has something to read
    fa_path = populated_repo / "docs/arch/functional_areas.yml"
    fa_path.parent.mkdir(parents=True, exist_ok=True)
    fa_path.write_text(
        "areas:\n"
        "  orchestration:\n"
        "    label: Orchestration\n"
        "    description: x\n"
    )
    from src.arch.runner import emit
    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    expected = {"loops.md", "ports.md", "labels.md", "modules.md",
                "events.md", "adr_xref.md", "mockworld.md", "changelog.md",
                "functional_areas.md"}
    assert {p.name for p in out.iterdir() if p.suffix == ".md"} == expected
    assert (out.parent / ".meta.json").exists()
```

Rename the test method (delete the old `test_emit_writes_all_eight_artifacts`).

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_runner.py::test_emit_writes_all_nine_artifacts -v
```

Expected: fail because functional_areas.md isn't being written.

- [ ] **Step 3: Update `_compute_artifacts` and `_ARTIFACT_FILES`**

In `src/arch/runner.py`:

```python
# Add the imports
from src.arch._functional_areas_schema import load_functional_areas
from src.arch.generators.functional_areas import render_functional_areas

# Update the artifact list
_ARTIFACT_FILES = ["loops.md", "ports.md", "labels.md", "modules.md",
                   "events.md", "adr_xref.md", "mockworld.md", "changelog.md",
                   "functional_areas.md"]

# Inside _compute_artifacts, add the new artifact:
def _compute_artifacts(repo_root: Path) -> dict[str, str]:
    src_dir = repo_root / "src"
    fakes_dir = repo_root / "tests/scenarios/fakes"
    scenarios_dir = repo_root / "tests/scenarios"
    adr_dir = repo_root / "docs/adr"
    fa_path = repo_root / "docs/arch/functional_areas.yml"

    loops = extract_loops(src_dir)
    ports = extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)

    artifacts = {
        "loops.md": render_loop_registry(loops),
        "ports.md": render_port_map(ports),
        "labels.md": render_label_state(extract_labels(src_dir)),
        "modules.md": render_module_graph(extract_module_graph(src_dir)),
        "events.md": render_event_bus(extract_event_topology(src_dir)),
        "adr_xref.md": render_adr_cross_reference(extract_adr_refs(adr_dir)),
        "mockworld.md": render_mockworld_map(extract_mockworld_map(
            fakes_dir=fakes_dir, scenarios_dir=scenarios_dir)),
        "changelog.md": render_changelog(_git_log_changelog(repo_root)),
    }
    if fa_path.exists():
        fa = load_functional_areas(fa_path)
        artifacts["functional_areas.md"] = render_functional_areas(fa, loops=loops, ports=ports)
    else:
        # Plan A → Plan B transition state: emit an explicit placeholder so the
        # runner emits 9 artifacts (the count expected by Plan B+) even if the
        # YAML hasn't landed in this branch yet.
        artifacts["functional_areas.md"] = (
            "# Functional Area Map\n\n"
            "_(awaiting docs/arch/functional_areas.yml — Plan B Task 4)_\n"
        )
    return artifacts
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/architecture/test_runner.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
make arch-regen
ls docs/arch/generated/
```

Expected: 9 .md files, including `functional_areas.md`.

```bash
head -40 docs/arch/generated/functional_areas.md
```

Expected: H1 "Functional Area Map", a Mermaid `flowchart LR` block with subgraphs.

- [ ] **Step 6: Commit**

```bash
git add src/arch/runner.py tests/architecture/test_runner.py
git commit -m "feat(arch): wire functional_areas generator into runner (9 artifacts)"
```

---

## Task 8: `make arch-validate` target

**Files:**
- Modify: `Makefile`
- Modify: existing `quality` target (find it and add the new step)

Validates `functional_areas.yml` against the Pydantic schema. Runs as a fast pre-check separate from full regeneration; meant to be invoked by:
- `make quality` (so a malformed YAML fails before push)
- The pre-commit hook (Task 9)
- The CI guard (Plan C — `arch-regen.yml` calls it before `--check`)

- [ ] **Step 1: Add the target**

Append to `Makefile`:

```makefile
.PHONY: arch-validate

## arch-validate — validate docs/arch/functional_areas.yml against schema
arch-validate:
	@python -c "from src.arch._functional_areas_schema import load_functional_areas; from pathlib import Path; load_functional_areas(Path('docs/arch/functional_areas.yml')); print('functional_areas.yml: ✓ schema valid')"
```

- [ ] **Step 2: Hook into `make quality`**

Find the existing `quality` target. It typically chains lint + type + test + format. Add `arch-validate` as the first dependency:

```makefile
quality: arch-validate ruff pyright bandit pytest  # existing list, prepend arch-validate
```

(Adapt to match the actual existing structure.)

- [ ] **Step 3: Verify**

```bash
make arch-validate
```

Expected: `functional_areas.yml: ✓ schema valid`.

```bash
# Negative test: corrupt the YAML, confirm it fails, then revert
echo "broken: [not-valid" >> docs/arch/functional_areas.yml
make arch-validate || echo "FAILED AS EXPECTED"
git checkout docs/arch/functional_areas.yml
make arch-validate  # back to passing
```

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "build(arch): make arch-validate (schema check) wired into make quality"
```

---

## Task 9: Pre-commit hook for `functional_areas.yml`

**Files:**
- Modify: `.pre-commit-config.yaml` if it exists, else create
- (or) Create: `hooks/pre-commit-arch-validate.sh`

Inspect the existing hook setup before authoring:

```bash
ls .pre-commit-config.yaml hooks/ 2>/dev/null
```

If `.pre-commit-config.yaml` is the established mechanism, add a hook there. If the repo uses a custom hooks/ dir, add a script and wire it into the existing hook runner.

- [ ] **Step 1: Add the hook (pre-commit framework variant)**

If `.pre-commit-config.yaml` exists, add to its `repos:` section:

```yaml
  - repo: local
    hooks:
      - id: arch-validate
        name: validate functional_areas.yml schema
        entry: make arch-validate
        language: system
        files: ^docs/arch/functional_areas\.yml$
        pass_filenames: false
```

If a custom `hooks/` script directory is in use, add `hooks/pre-commit-arch-validate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
if git diff --cached --name-only | grep -q '^docs/arch/functional_areas\.yml$'; then
    make arch-validate
fi
```

Mark executable: `chmod +x hooks/pre-commit-arch-validate.sh`.

- [ ] **Step 2: Test the hook fires**

```bash
echo "broken: [stuff" >> docs/arch/functional_areas.yml
git add docs/arch/functional_areas.yml
git commit -m "test" 2>&1 | tail -10
# Expected: hook fires, commit aborted
git restore --staged docs/arch/functional_areas.yml
git checkout docs/arch/functional_areas.yml
```

- [ ] **Step 3: Commit the hook config**

```bash
git add .pre-commit-config.yaml  # or hooks/pre-commit-arch-validate.sh
git commit -m "build(arch): pre-commit hook for functional_areas.yml schema"
```

---

## Task 10: Move `docs/architecture/` → `docs/arch/`

**Files:**
- Rename: `docs/architecture/` → `docs/arch/` (only if `architecture/` exists at this point — it should because Plan A didn't touch it)

The 12 stale `.likec4` files currently live in `docs/architecture/`. Plan A's runner emitted into `docs/arch/generated/`. Both directories now exist. This task consolidates by deleting the old name.

- [ ] **Step 1: Verify state**

```bash
ls docs/architecture/ 2>/dev/null
ls docs/arch/
```

Expected: `architecture/` has 12 `.likec4` files; `arch/` has `functional_areas.yml` and `generated/`.

- [ ] **Step 2: There's nothing to move from `architecture/` (the .likec4s are deleted in Task 11). Skip.**

In practice the rename is just deleting the old directory after Task 11. Mark this task complete and move on.

---

## Task 11: Delete the 12 stale `.likec4` files

**Files:**
- Delete: `docs/architecture/*.likec4` (12 files) and the `docs/architecture/` directory itself

These are agent-generated snapshots from past investigations with no curation value (per spec §3 corollary).

- [ ] **Step 1: Verify the .likec4 inventory**

```bash
ls docs/architecture/*.likec4 | wc -l
ls docs/architecture/*.likec4
```

Expected: 12 files. Confirm none of them have been hand-edited (recent `git log` should show only the original commit):

```bash
git log --oneline -- docs/architecture/*.likec4 | head -10
```

If any has multiple commits with non-trivial content changes, **stop** and ask whether that one should be preserved. Otherwise proceed.

- [ ] **Step 2: Delete**

```bash
git rm docs/architecture/*.likec4
rmdir docs/architecture
```

- [ ] **Step 3: Search for any references to the deleted files**

```bash
grep -rE "\.likec4|docs/architecture" --include='*.md' --include='*.py' --include='*.yml' --include='*.yaml' . 2>/dev/null | grep -v "docs/architecture/$" | head -20
```

Update any references (likely in `CLAUDE.md`, the wiki, or docstrings) to point at `docs/arch/generated/` or remove the reference. Track these so Task 14 (CLAUDE.md update) covers them.

- [ ] **Step 4: Commit**

```bash
git add -A docs/architecture
git commit -m "chore(arch): delete 12 stale agent-generated likec4 diagrams

These are one-shot snapshots from past investigations, never updated, already
drifted from the live topology. Replaced by AST-extracted Markdown+Mermaid
in docs/arch/generated/."
```

---

## Task 12: Amend ADR-0001

**Files:**
- Modify: `docs/adr/0001-five-concurrent-async-loops.md`

Per spec §8 step 5: replace the "five concurrent async loops" framing with a reference to the live registry, while preserving the historical context.

- [ ] **Step 1: Read the ADR**

```bash
cat docs/adr/0001-five-concurrent-async-loops.md
```

Note the existing structure (Status, Date, Enforced by, Context, Decision, Consequences).

- [ ] **Step 2: Edit it**

The amendment shape:

1. Add a `Status` line note: `(amended 2026-04-24)` after the original status.
2. Add a "Background" section near the top (after the original Context) containing the historical "five" claim verbatim, with an introductory line: *"This ADR was originally written when HydraFlow had five concurrent async loops. The decision below is preserved as historical context."*
3. Replace the "Decision" section's count phrasing with: *"HydraFlow runs N concurrent background loops, where N is the live count emitted by [`docs/arch/generated/loops.md`](../arch/generated/loops.md). The five-loop pattern in the original Context section was the v1 shape; the architecture has since evolved to include caretaker loops (ADR-0029) and the trust fleet (ADR-0045)."*
4. Update the `Enforced by:` line to `tests/architecture/test_loop_count_matches_adr0001.py`.

Run the resulting file through `pytest`:

```bash
pytest tests/architecture/test_loop_count_matches_adr0001.py -v
```

If this still XFAILs, the amendment text doesn't match either of the test's pass conditions — re-read the test and adjust the wording until it passes (you may need to literally include `see docs/arch/generated/loops.md` per the test's exact match, or use the word "historical" in a "Background" section).

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0001-five-concurrent-async-loops.md
git commit -m "docs(adr): amend ADR-0001 to reference live loop registry

The 'five concurrent async loops' framing predates the caretaker fleet
(ADR-0029) and trust fleet (ADR-0045). Preserve the original context as
historical Background; point Decision at docs/arch/generated/loops.md
for the live count. Enforced by test_loop_count_matches_adr0001.py."
```

---

## Task 13: Remove the `xfail` from `test_loop_count_matches_adr0001`

**Files:**
- Modify: `tests/architecture/test_loop_count_matches_adr0001.py`

ADR-0001 has been amended (Task 12). The test should pass without xfail.

- [ ] **Step 1: Confirm the test now passes WITHOUT xfail**

Verify by running with the xfail decorator commented out:

```bash
pytest tests/architecture/test_loop_count_matches_adr0001.py -v
```

If it still XPASSes or XFails, return to Task 12 and fix the ADR wording.

- [ ] **Step 2: Remove the decorator**

In `tests/architecture/test_loop_count_matches_adr0001.py`, delete the `@pytest.mark.xfail(...)` line.

- [ ] **Step 3: Run the test (now without xfail)**

```bash
pytest tests/architecture/test_loop_count_matches_adr0001.py -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/architecture/test_loop_count_matches_adr0001.py
git commit -m "test(arch): remove xfail from loop count test (ADR-0001 amended)"
```

---

## Task 14: Update `CLAUDE.md` Knowledge Lookup

**Files:**
- Modify: `CLAUDE.md`

Per spec §8 steps 6-7. Replace the "System topology diagrams" row pointing at `docs/architecture/` with a row pointing at the published Pages site URL (Plan C will deploy it; the URL is fixed at `https://t-rav-hydra-ops.github.io/hydraflow/`) plus `docs/arch/generated/`.

- [ ] **Step 1: Read the current Knowledge Lookup table**

```bash
grep -A 15 "## Knowledge Lookup" CLAUDE.md
```

- [ ] **Step 2: Replace the System topology row**

Replace:

```
| System topology diagrams | [`docs/architecture/`](docs/architecture/) | `.likec4` diagrams: data flow, orchestrator/plan-phase decomposition, supervision, Sentry flow, health monitor |
```

with:

```
| System topology (live) | [`docs/arch/generated/`](docs/arch/generated/) + [Pages site](https://t-rav-hydra-ops.github.io/hydraflow/) | Auto-regenerated Markdown+Mermaid: loop registry, port map, label state machine, module graph, event bus, ADR cross-reference, MockWorld map, functional area map. Refreshed on every PR by `arch-regen.yml` and every 4h by `DiagramLoop` (L24, ADR-0029). Hand-curated narrative lives in ADRs and the wiki. |
```

- [ ] **Step 3: Update the Wiki topic index** (if it references `architecture.md`)

Confirm `docs/wiki/architecture.md` still exists and the link is correct. No content change needed.

- [ ] **Step 4: Add a brief note to "Quick rules"**

Add a row to the Quick rules block:

```
- **Look at the [System Map](https://t-rav-hydra-ops.github.io/hydraflow/system-map/) before exploring code blind.** The Functional Area Map shows what every loop and Port belongs to; click through to ADRs from there.
```

(Place it near the other "Always look up..." rules.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md Knowledge Lookup for arch knowledge system"
```

---

## Task 15: Add `.claude/worktrees/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

Per spec §8 step 8. Plan A established the worktrees convention but the directory itself is untracked-but-not-ignored — every fresh worktree appears as `??` in `git status`. Bundle the fix here.

- [ ] **Step 1: Verify current state**

```bash
git status --short | grep -E "^\?\? \.claude/worktrees" || echo "no untracked worktrees"
grep -nE "claude/worktrees|\.claude" .gitignore
```

- [ ] **Step 2: Add the line**

Append to `.gitignore` (in the section that already lists `.claude/plans/`, `.claude/state/`):

```
.claude/worktrees/
```

- [ ] **Step 3: Verify**

```bash
git check-ignore -v .claude/worktrees/foo
```

Expected: prints the matching `.gitignore:N:.claude/worktrees/` line.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore .claude/worktrees/ directory"
```

---

## Task 16: Re-emit baseline (now 9 artifacts) and final smoke

**Files:**
- Modify: `docs/arch/generated/*.md` (regenerated)
- Create: `docs/arch/generated/functional_areas.md`
- Modify: `docs/arch/.meta.json`

The runner now emits 9 artifacts; the baseline must be updated.

- [ ] **Step 1: Regenerate**

```bash
make arch-regen
git status docs/arch/generated/
```

Expected: `functional_areas.md` is new; the other 8 may have minor updates if the runner emit logic changed (e.g. footer formatting from Plan A's review-fix).

- [ ] **Step 2: Inspect the new artifact**

```bash
head -50 docs/arch/generated/functional_areas.md
```

Sanity:
- H1 "Functional Area Map"
- Mermaid `flowchart LR` block
- One `subgraph` per area declared in YAML
- Per-area details below

- [ ] **Step 3: Run the full architecture test suite**

```bash
pytest tests/architecture/ -v
```

Expected: all pass (no xfails, no skips except the trivial ones).

- [ ] **Step 4: Run `make quality`**

```bash
make quality
```

Expected: green.

- [ ] **Step 5: Commit baseline**

```bash
git add docs/arch/generated/ docs/arch/.meta.json
git commit -m "feat(arch): regenerate baseline with functional_areas.md (9 artifacts)"
```

- [ ] **Step 6: Open the PR**

```bash
git push -u origin arch-knowledge-system
gh pr create --title "feat(arch): Plan B — functional areas + ADR-0001 + migration" \
    --body "$(cat <<'EOF'
## Summary

Plan B of the Architecture Knowledge System
(`docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md`,
plan: `docs/superpowers/plans/2026-04-24-arch-knowledge-system-plan-b-functional-areas.md`).

Adds:
- `docs/arch/functional_areas.yml` — hand-curated area assignments
- `src/arch/_functional_areas_schema.py` — Pydantic schema
- `src/arch/generators/functional_areas.py` — 9th generator (Mermaid clusters)
- `tests/architecture/test_functional_areas_schema.py`
- `tests/architecture/test_functional_area_coverage.py`
- `make arch-validate` target wired into `make quality`
- Pre-commit hook for the YAML
- `docs/arch/generated/functional_areas.md` baseline

Migrations:
- Deleted 12 stale `.likec4` files from `docs/architecture/` (and the dir)
- Amended ADR-0001 to reference the live loop registry
- Removed xfail from `test_loop_count_matches_adr0001`
- Updated `CLAUDE.md` Knowledge Lookup
- Added `.claude/worktrees/` to `.gitignore`

Out of scope (Plan C):
- `DiagramLoop` (L24) autonomous loop
- `arch-regen.yml` CI guard workflow
- MkDocs Material site config + `pages-deploy.yml`
- Pages publishing

## Test plan

- [x] `pytest tests/architecture/` all pass (no xfails)
- [x] `make arch-validate` passes
- [x] `make arch-regen` produces 9 .md files
- [x] `make quality` is green
- [x] Coverage test fails when a phantom loop is added to YAML (verified manually)
- [x] Coverage test fails when a real loop is added to src/ but not assigned (verified manually)
- [x] Schema test fails on malformed YAML (verified manually)
- [x] Pre-commit hook aborts a commit with broken YAML (verified manually)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

- [ ] Every task in the spec coverage map is done.
- [ ] `docs/arch/functional_areas.yml` covers every loop and port the AST extractor finds (and pre-assigns `DiagramLoop` for Plan C).
- [ ] No remaining `xfail` decorators on architecture tests.
- [ ] No `TODO`/`FIXME` in any new file.
- [ ] `docs/architecture/` directory is gone.
- [ ] CLAUDE.md, ADR-0001, and `.gitignore` updates are committed.
- [ ] `make quality` is green.
- [ ] PR description references the spec section and the plan.
