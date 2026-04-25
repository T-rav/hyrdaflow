# Architecture Knowledge System — Plan A: Runner Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the foundation for the Architecture Knowledge System v1: a CLI runner (`python -m src.arch.runner`) that walks `src/`, `tests/scenarios/fakes/`, `docs/adr/`, and git history, and emits 8 deterministic Markdown artifacts under `docs/arch/generated/` with embedded Mermaid diagrams and a `.meta.json` sidecar. No DiagramLoop, no CI workflows, no MkDocs site, no `functional_areas.yml` — those land in Plans B and C respectively.

**Architecture:** Pure-function pipeline. `src/arch/extractors/` parses source (AST and file-walk only — no class introspection, no imports) and produces typed dataclass models. `src/arch/generators/` consumes models and emits byte-stable Markdown. `src/arch/runner.py` orchestrates: discover sources → extract → generate → write. `src/arch/freshness.py` computes per-artifact badge state from `.meta.json`. Every artifact is reproducible: same `src/` SHA → same Markdown bytes.

**Tech Stack:** Python 3.11, stdlib `ast` / `pathlib` / `subprocess` (for `git log`), Pydantic v2 for typed models (already in deps), pytest for tests. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md` — §3, §4.1, §4.2 (excluding `functional_areas.py`), §5 (runner only), §6 (freshness logic only), §7 (extractor + generator + drift + label-match + loop-count tests).

**Spec coverage map:**

| Spec requirement | Tasks |
|---|---|
| §3 layered model — Generated layer scaffold | Task 0 |
| §4.1 `loops.py` extractor (AST) | Task 1 |
| §4.1 `ports.py` extractor | Task 2 |
| §4.1 `labels.py` extractor | Task 3 |
| §4.1 `modules.py` extractor | Task 4 |
| §4.1 `events.py` extractor | Task 5 |
| §4.1 `adr_xref.py` extractor | Task 6 |
| §4.1 `mockworld.py` extractor | Task 7 |
| §4.2 `loop_registry.py` generator | Task 8 |
| §4.2 `port_map.py` generator | Task 9 |
| §4.2 `label_state.py` generator | Task 10 |
| §4.2 `module_graph.py` generator | Task 11 |
| §4.2 `event_bus.py` generator | Task 12 |
| §4.2 `adr_cross_reference.py` generator | Task 13 |
| §4.2 `mockworld_map.py` generator | Task 14 |
| §4.2 `changelog.py` generator | Task 15 |
| Runner CLI | Task 16 |
| §6 freshness module + bootstrap state | Task 17 |
| §7 ADR-0002 label-match test | Task 18 |
| §7 ADR-0001 loop-count test (xfail-pending Plan B) | Task 19 |
| §7 curated-drift test (CI guard's local twin) | Task 20 |
| `make arch-regen` + `make arch-serve` placeholder targets | Task 21 |
| Initial emit + commit `docs/arch/generated/` baseline | Task 22 |

**Out of scope (delivered by later plans):**
- `functional_areas.py` generator + YAML + coverage test → **Plan B**
- ADR-0001 amendment + `.likec4` deletion + CLAUDE.md update → **Plan B**
- **Removing the `@pytest.mark.xfail` decorator from `test_loop_count_matches_adr0001`** → **Plan B** (after the ADR-0001 amendment lands the test should pass; the xfail mark must be removed at that point or it becomes a silently-suppressed real test)
- DiagramLoop (L24) → **Plan C**
- `arch-regen.yml` CI workflow → **Plan C**
- `pages-deploy.yml` + MkDocs Material config → **Plan C**
- Kill-switch test for the loop → **Plan C**
- Mermaid `--strict` build test → **Plan C**

---

## Task 0: Scaffold `src/arch/` and `tests/architecture/` packages

**Files:**
- Create: `src/arch/__init__.py` (empty)
- Create: `src/arch/extractors/__init__.py` (empty)
- Create: `src/arch/generators/__init__.py` (empty)
- Create: `src/arch/_models.py` (shared dataclasses — see below)
- Create: `tests/architecture/__init__.py` (empty)
- Create: `tests/architecture/conftest.py` (shared fixtures — see below)

- [ ] **Step 1: Create the directory tree**

```bash
mkdir -p src/arch/extractors src/arch/generators tests/architecture
touch src/arch/__init__.py src/arch/extractors/__init__.py \
      src/arch/generators/__init__.py tests/architecture/__init__.py
```

- [ ] **Step 2: Add the shared model file**

Create `src/arch/_models.py`:

```python
"""Typed model objects shared by extractors and generators.

All fields use plain Python types (str, list, dict, dataclass, Pydantic
BaseModel) — no runtime introspection, no class objects. This guarantees
extractors are pure functions of source text and that pickling/JSON
round-trips work.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoopInfo(BaseModel):
    """One row in the loop registry."""
    name: str  # class name, e.g. "DiagramLoop"
    module: str  # python module dotted path, e.g. "src.diagram_loop"
    source_path: str  # repo-relative path, e.g. "src/diagram_loop.py"
    tick_interval_seconds: int | None = None
    event_subscriptions: list[str] = Field(default_factory=list)
    kill_switch_var: str | None = None  # e.g. "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"
    adr_refs: list[str] = Field(default_factory=list)  # e.g. ["ADR-0029", "ADR-0049"]


class PortAdapterInfo(BaseModel):
    name: str
    module: str
    source_path: str
    is_fake: bool = False


class PortInfo(BaseModel):
    name: str
    module: str
    source_path: str
    methods: list[str] = Field(default_factory=list)
    adapters: list[PortAdapterInfo] = Field(default_factory=list)
    fake: PortAdapterInfo | None = None


class LabelTransition(BaseModel):
    from_state: str
    to_state: str
    trigger: str = ""  # human-readable description if extractable


class LabelStateMachine(BaseModel):
    states: list[str] = Field(default_factory=list)
    transitions: list[LabelTransition] = Field(default_factory=list)


class ModuleNode(BaseModel):
    name: str  # package-level, e.g. "src.adapters"


class ModuleEdge(BaseModel):
    from_module: str
    to_module: str
    weight: int = 1  # number of import statements aggregated


class ModuleGraph(BaseModel):
    nodes: list[ModuleNode] = Field(default_factory=list)
    edges: list[ModuleEdge] = Field(default_factory=list)


class EventEdge(BaseModel):
    event: str  # EventType member name, e.g. "PR_OPENED"
    publishers: list[str] = Field(default_factory=list)  # qualified module:func
    subscribers: list[str] = Field(default_factory=list)


class EventBusTopology(BaseModel):
    events: list[EventEdge] = Field(default_factory=list)


class ADRRef(BaseModel):
    adr_id: str  # e.g. "ADR-0029"
    cited_modules: list[str] = Field(default_factory=list)  # e.g. ["src.diagram_loop"]


class ADRRefIndex(BaseModel):
    adr_to_modules: list[ADRRef] = Field(default_factory=list)
    # module_to_adrs is computed in the generator; extractor only emits forward index.


class FakeInfo(BaseModel):
    name: str  # e.g. "FakeGitHub"
    module: str  # e.g. "tests.scenarios.fakes.fake_github"
    source_path: str
    implements_port: str | None = None  # if discoverable
    used_in_scenarios: list[str] = Field(default_factory=list)


class MockWorldMap(BaseModel):
    fakes: list[FakeInfo] = Field(default_factory=list)
```

- [ ] **Step 3: Add the test conftest**

Create `tests/architecture/conftest.py`:

```python
"""Shared fixtures for architecture tests.

The `fixture_src_tree` factory writes a tiny synthetic source tree to
tmp_path so extractor tests run in isolation from the live repo. The
`real_repo_root` fixture points at the actual repo (for tests that
intentionally exercise the live tree, like the drift test).
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import pytest


@pytest.fixture
def fixture_src_tree(tmp_path: Path):
    """Returns a callable: write_files(spec: dict[str, str]) -> Path.

    Usage:
        root = fixture_src_tree({
            "src/foo.py": "class Foo: ...",
            "src/bar.py": "from foo import Foo",
        })
    """
    def _write(spec: dict[str, str]) -> Path:
        for rel, body in spec.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(dedent(body).lstrip("\n"))
        return tmp_path

    return _write


@pytest.fixture
def real_repo_root() -> Path:
    """Path to the repo root (parents[2] from this conftest)."""
    return Path(__file__).resolve().parents[2]
```

- [ ] **Step 4: Verify the package imports**

```bash
python -c "import arch; import arch.extractors; import arch.generators; from arch._models import LoopInfo; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/arch/ tests/architecture/
git commit -m "feat(arch): scaffold src/arch and tests/architecture packages"
```

---

## Task 1: Loops extractor (AST-based)

**Files:**
- Create: `src/arch/extractors/loops.py`
- Test: `tests/architecture/test_extractor_loops.py`

The extractor walks `src/*.py`, parses each file with `ast.parse`, and finds
`class X(BaseBackgroundLoop):` declarations. For each, it extracts:
- The class name
- The module path
- Default `tick_interval_seconds` from a class attribute or `__init__` default
- Event subscriptions from class attributes / register calls (best-effort)
- Kill-switch env-var name from comparisons against `os.environ.get("HYDRAFLOW_DISABLE_*")`
- ADR references from class docstring (regex `ADR-\d{4}`)

**Side-effect-free.** No imports, no instantiation.

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_extractor_loops.py`:

```python
from arch.extractors.loops import extract_loops


def test_extracts_basebackgroundloop_subclass(fixture_src_tree):
    root = fixture_src_tree({
        "src/widget_loop.py": '''
            """A widget loop.

            Per ADR-0029, ADR-0049.
            """
            import os
            from base_background_loop import BaseBackgroundLoop
            from events import EventType

            class WidgetLoop(BaseBackgroundLoop):
                tick_interval_seconds = 3600

                def __init__(self, bus):
                    self._kill = os.environ.get("HYDRAFLOW_DISABLE_WIDGET_LOOP")
                    bus.subscribe(EventType.PR_OPENED, self._on_pr)
                    bus.subscribe(EventType.RC_RED, self._on_red)
        ''',
    })

    loops = extract_loops(root / "src")

    assert len(loops) == 1
    info = loops[0]
    assert info.name == "WidgetLoop"
    assert info.module == "src.widget_loop"
    assert info.source_path == "src/widget_loop.py"
    assert info.tick_interval_seconds == 3600
    assert info.kill_switch_var == "HYDRAFLOW_DISABLE_WIDGET_LOOP"
    assert info.adr_refs == ["ADR-0029", "ADR-0049"]
    # Event subscriptions are sorted; both are captured.
    assert info.event_subscriptions == ["PR_OPENED", "RC_RED"]


def test_skips_non_loop_classes(fixture_src_tree):
    root = fixture_src_tree({
        "src/foo.py": "class NotALoop: pass",
    })
    assert extract_loops(root / "src") == []


def test_skips_basebackgroundloop_itself(fixture_src_tree):
    root = fixture_src_tree({
        "src/base_background_loop.py": '''
            class BaseBackgroundLoop: pass
        ''',
    })
    assert extract_loops(root / "src") == []


def test_output_is_sorted_by_name(fixture_src_tree):
    root = fixture_src_tree({
        "src/zebra_loop.py": "from base_background_loop import BaseBackgroundLoop\nclass ZebraLoop(BaseBackgroundLoop): pass",
        "src/alpha_loop.py": "from base_background_loop import BaseBackgroundLoop\nclass AlphaLoop(BaseBackgroundLoop): pass",
    })
    names = [loop.name for loop in extract_loops(root / "src")]
    assert names == ["AlphaLoop", "ZebraLoop"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_loops.py -v
```

Expected: `ImportError: cannot import name 'extract_loops'`

- [ ] **Step 3: Implement the extractor**

Create `src/arch/extractors/loops.py`:

```python
"""Extract LoopInfo records from src/*.py via AST static analysis.

Why AST and not class introspection: each loop module has deferred imports
with side effects (config wiring, network probes). Importing every module
to enumerate `BaseBackgroundLoop.__subclasses__()` would fire those side
effects and is not viable in a documentation pipeline. AST parses the
source text only; nothing executes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from arch._models import LoopInfo

_ADR_RE = re.compile(r"ADR-(\d{4})")
_KILL_RE = re.compile(r'HYDRAFLOW_DISABLE_[A-Z0-9_]+')


def _module_for(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)  # repo-root-relative
    return ".".join(rel.with_suffix("").parts)


def _is_basebackgroundloop_subclass(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseBackgroundLoop":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseBackgroundLoop":
            return True
    return False


def _tick_interval(cls: ast.ClassDef) -> int | None:
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "tick_interval_seconds":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                        return node.value.value
    return None


def _kill_switch(cls: ast.ClassDef) -> str | None:
    src = ast.unparse(cls)
    m = _KILL_RE.search(src)
    return m.group(0) if m else None


def _adr_refs(cls: ast.ClassDef) -> list[str]:
    doc = ast.get_docstring(cls) or ""
    return sorted({f"ADR-{m}" for m in _ADR_RE.findall(doc)})


def _event_subs(cls: ast.ClassDef) -> list[str]:
    """Best-effort: pull EventType.X references from the class body."""
    src = ast.unparse(cls)
    return sorted(set(re.findall(r"EventType\.([A-Z_]+)", src)))


def extract_loops(src_dir: Path) -> list[LoopInfo]:
    """Walk *.py under src_dir and return one LoopInfo per BaseBackgroundLoop subclass.

    Result is sorted by class name for deterministic output. The
    `BaseBackgroundLoop` base class itself is skipped.
    """
    src_dir = Path(src_dir).resolve()
    out: list[LoopInfo] = []
    for py in sorted(src_dir.rglob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name == "BaseBackgroundLoop":
                continue
            if not _is_basebackgroundloop_subclass(node):
                continue
            out.append(LoopInfo(
                name=node.name,
                module=_module_for(py, src_dir),
                source_path=str(py.relative_to(src_dir.parent)),
                tick_interval_seconds=_tick_interval(node),
                event_subscriptions=_event_subs(node),
                kill_switch_var=_kill_switch(node),
                adr_refs=_adr_refs(node),
            ))
    out.sort(key=lambda loop: loop.name)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_loops.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from arch.extractors.loops import extract_loops; from pathlib import Path; loops = extract_loops(Path('src')); print(f'{len(loops)} loops:'); [print(f'  {l.name} ({l.source_path})') for l in loops]"
```

Expected: ~25-30 loops listed, including `DiagnosticLoop`, `EpicMonitorLoop`, `RepoWikiLoop`, `StagingPromotionLoop`, etc. **No** `BaseBackgroundLoop` itself in the output.

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/loops.py tests/architecture/test_extractor_loops.py
git commit -m "feat(arch): loops extractor (AST-based, no class introspection)"
```

---

## Task 2: Ports extractor

**Files:**
- Create: `src/arch/extractors/ports.py`
- Test: `tests/architecture/test_extractor_ports.py`

Walks `src/*.py` for `class X(Protocol):` and `class X(...Protocol):` (covers `typing.Protocol` and `typing_extensions.Protocol`). Emits `PortInfo` for each whose name ends in `Port`. For each Port, finds adapter classes elsewhere in `src/` whose declared methods are a superset of the Port's methods (best-effort; final accuracy is the user's problem if they name things weirdly). Fake adapters live under `tests/scenarios/fakes/` and are matched by name pattern (`Fake<PortStem>` or via class attribute `_implements: type[Port] = ...`).

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_extractor_ports.py`:

```python
from arch.extractors.ports import extract_ports


def test_finds_protocol_port_with_adapter_and_fake(fixture_src_tree):
    root = fixture_src_tree({
        "src/ports.py": '''
            from typing import Protocol

            class WidgetPort(Protocol):
                def make(self) -> str: ...
                def break_(self) -> None: ...

            class NotAPort(Protocol):
                def thing(self) -> None: ...
        ''',
        "src/widget_adapter.py": '''
            class WidgetAdapter:
                def make(self) -> str: return ""
                def break_(self) -> None: pass
        ''',
        "tests/scenarios/fakes/fake_widget.py": '''
            class FakeWidget:
                def make(self) -> str: return "fake"
                def break_(self) -> None: pass
        ''',
    })

    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "tests/scenarios/fakes")

    assert len(ports) == 1
    p = ports[0]
    assert p.name == "WidgetPort"
    assert sorted(p.methods) == ["break_", "make"]
    assert len(p.adapters) == 1
    assert p.adapters[0].name == "WidgetAdapter"
    assert p.fake is not None
    assert p.fake.name == "FakeWidget"


def test_port_without_fake_marks_fake_none(fixture_src_tree):
    root = fixture_src_tree({
        "src/ports.py": '''
            from typing import Protocol
            class LonelyPort(Protocol):
                def thing(self) -> None: ...
        ''',
    })
    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "nonexistent")
    assert len(ports) == 1
    assert ports[0].fake is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_ports.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the extractor**

Create `src/arch/extractors/ports.py`:

```python
"""Extract PortInfo records from src/*.py and tests/scenarios/fakes/*.py."""
from __future__ import annotations

import ast
from pathlib import Path

from arch._models import PortAdapterInfo, PortInfo


def _is_protocol_subclass(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _public_methods(cls: ast.ClassDef) -> list[str]:
    out = []
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("__"):
                out.append(node.name)
    return sorted(out)


def _module_dotted(path: Path, root: Path) -> str:
    rel = path.relative_to(root.parent)
    return ".".join(rel.with_suffix("").parts)


def _collect_classes(scan_dir: Path) -> list[tuple[Path, ast.ClassDef]]:
    out: list[tuple[Path, ast.ClassDef]] = []
    if not scan_dir.exists():
        return out
    for py in sorted(scan_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                out.append((py, node))
    return out


def extract_ports(*, src_dir: Path, fakes_dir: Path) -> list[PortInfo]:
    src_dir = Path(src_dir).resolve()
    fakes_dir = Path(fakes_dir).resolve()

    src_classes = _collect_classes(src_dir)
    fake_classes = _collect_classes(fakes_dir) if fakes_dir.exists() else []

    ports: list[PortInfo] = []
    for path, cls in src_classes:
        if not cls.name.endswith("Port"):
            continue
        if not _is_protocol_subclass(cls):
            continue

        methods = _public_methods(cls)
        port_methods = set(methods)

        # Find adapters: src classes (non-Protocol) whose public method set
        # is a superset of the Port's. Skip the Port class itself.
        adapters: list[PortAdapterInfo] = []
        for apath, acls in src_classes:
            if acls is cls:
                continue
            if _is_protocol_subclass(acls):
                continue
            if not port_methods.issubset(set(_public_methods(acls))):
                continue
            adapters.append(PortAdapterInfo(
                name=acls.name,
                module=_module_dotted(apath, src_dir),
                source_path=str(apath.relative_to(src_dir.parent)),
            ))

        # Find fake: pattern Fake<PortStem> first; then any Fake* with
        # superset methods.
        port_stem = cls.name[:-len("Port")]
        fake: PortAdapterInfo | None = None
        for fpath, fcls in fake_classes:
            if fcls.name == f"Fake{port_stem}":
                fake = PortAdapterInfo(
                    name=fcls.name,
                    module=_module_dotted(fpath, fakes_dir.parents[2]),
                    source_path=str(fpath.relative_to(fakes_dir.parents[2])),
                    is_fake=True,
                )
                break
        if fake is None:
            for fpath, fcls in fake_classes:
                if not fcls.name.startswith("Fake"):
                    continue
                if not port_methods.issubset(set(_public_methods(fcls))):
                    continue
                fake = PortAdapterInfo(
                    name=fcls.name,
                    module=_module_dotted(fpath, fakes_dir.parents[2]),
                    source_path=str(fpath.relative_to(fakes_dir.parents[2])),
                    is_fake=True,
                )
                break

        ports.append(PortInfo(
            name=cls.name,
            module=_module_dotted(path, src_dir),
            source_path=str(path.relative_to(src_dir.parent)),
            methods=methods,
            adapters=sorted(adapters, key=lambda a: a.name),
            fake=fake,
        ))

    ports.sort(key=lambda p: p.name)
    return ports
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_ports.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.ports import extract_ports; ports = extract_ports(src_dir=Path('src'), fakes_dir=Path('tests/scenarios/fakes')); print(f'{len(ports)} ports:'); [print(f'  {p.name}: {len(p.adapters)} adapters, fake={p.fake.name if p.fake else None}') for p in ports]"
```

Expected: at least `PRPort`, `WorkspacePort`, `IssueStorePort`, `IssueFetcherPort`, `AgentPort`, `ReviewInsightStorePort`, `ObservabilityPort`, plus `RouteBackCounterPort` if discoverable.

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/ports.py tests/architecture/test_extractor_ports.py
git commit -m "feat(arch): ports extractor with adapter and fake matching"
```

---

## Task 3: Labels extractor

**Files:**
- Create: `src/arch/extractors/labels.py`
- Test: `tests/architecture/test_extractor_labels.py`

The label state machine lives in `src/labels.py` (or wherever the canonical transition table is — verify before implementing). Approach: parse for top-level dict / list constants whose values are tuples like `(from_state, to_state, trigger?)`. Acceptable forms: a `TRANSITIONS: list[tuple]`, an enum with `from_label`/`to_label` fields, or a function with a hard-coded match/case. The extractor handles the first form (constants) and falls back to a regex scan if the constant isn't found.

- [ ] **Step 1: Locate the canonical transition source**

```bash
grep -rE "transition|TRANSITION|relabel" src/labels*.py src/state*.py 2>/dev/null | head -20
grep -rE "hydraflow-(ready|implement|review|hitl|merged)" src/*.py | head -10
```

Inspect the result and pick the ONE file most likely to be the canonical declaration. Document the chosen file in the implementation as a module-level constant `_TRANSITION_SOURCE_HINT`. If no canonical file exists, the extractor falls back to scanning all of `src/`.

- [ ] **Step 2: Write the failing test**

Create `tests/architecture/test_extractor_labels.py`:

```python
from arch.extractors.labels import extract_labels


def test_extracts_explicit_transitions_constant(fixture_src_tree):
    root = fixture_src_tree({
        "src/labels.py": '''
            TRANSITIONS = [
                ("hydraflow-ready", "hydraflow-implementing", "agent_started"),
                ("hydraflow-implementing", "hydraflow-reviewing", "pr_opened"),
                ("hydraflow-reviewing", "hydraflow-merged", "pr_merged"),
            ]
        ''',
    })
    sm = extract_labels(root / "src")
    assert sorted(sm.states) == ["hydraflow-implementing", "hydraflow-merged", "hydraflow-ready", "hydraflow-reviewing"]
    assert len(sm.transitions) == 3
    edge = next(t for t in sm.transitions if t.from_state == "hydraflow-ready")
    assert edge.to_state == "hydraflow-implementing"
    assert edge.trigger == "agent_started"


def test_returns_empty_when_no_transitions_found(fixture_src_tree):
    root = fixture_src_tree({"src/foo.py": "x = 1"})
    sm = extract_labels(root / "src")
    assert sm.states == []
    assert sm.transitions == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_labels.py -v
```

Expected: `ImportError`.

- [ ] **Step 4: Implement the extractor**

Create `src/arch/extractors/labels.py`:

```python
"""Extract LabelStateMachine from the canonical transition declaration."""
from __future__ import annotations

import ast
from pathlib import Path

from arch._models import LabelStateMachine, LabelTransition


def _literal_transitions(src_text: str) -> list[LabelTransition]:
    """Find a top-level TRANSITIONS = [...] of tuples and parse them."""
    try:
        tree = ast.parse(src_text)
    except SyntaxError:
        return []
    out: list[LabelTransition] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        if node.targets[0].id not in {"TRANSITIONS", "_TRANSITIONS", "LABEL_TRANSITIONS"}:
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for elt in node.value.elts:
            if not isinstance(elt, ast.Tuple):
                continue
            parts = []
            for sub in elt.elts:
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    parts.append(sub.value)
                else:
                    break
            if len(parts) >= 2:
                out.append(LabelTransition(
                    from_state=parts[0],
                    to_state=parts[1],
                    trigger=parts[2] if len(parts) > 2 else "",
                ))
    return out


def extract_labels(src_dir: Path) -> LabelStateMachine:
    src_dir = Path(src_dir).resolve()
    transitions: list[LabelTransition] = []
    for py in sorted(src_dir.rglob("*.py")):
        try:
            text = py.read_text()
        except OSError:
            continue
        if "TRANSITIONS" not in text and "_TRANSITIONS" not in text and "LABEL_TRANSITIONS" not in text:
            continue
        transitions.extend(_literal_transitions(text))
        if transitions:
            break  # first hit wins; canonical source.

    states: set[str] = set()
    for t in transitions:
        states.add(t.from_state)
        states.add(t.to_state)
    transitions.sort(key=lambda t: (t.from_state, t.to_state, t.trigger))
    return LabelStateMachine(
        states=sorted(states),
        transitions=transitions,
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_labels.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.labels import extract_labels; sm = extract_labels(Path('src')); print(f'{len(sm.states)} states, {len(sm.transitions)} transitions'); [print(f'  {t.from_state} -> {t.to_state} ({t.trigger})') for t in sm.transitions[:5]]"
```

If the real repo's transition declaration form is different from what the extractor handles, this will print 0 states / 0 transitions. **That is acceptable for Plan A** — Plan A's drift test will record whatever the extractor produces, and ADR-0002 match test (Task 18) will then fail loudly and the implementer can iterate. The fallback is part of Task 18's body.

- [ ] **Step 7: Commit**

```bash
git add src/arch/extractors/labels.py tests/architecture/test_extractor_labels.py
git commit -m "feat(arch): labels extractor (literal TRANSITIONS form)"
```

---

## Task 4: Modules extractor (import graph)

**Files:**
- Create: `src/arch/extractors/modules.py`
- Test: `tests/architecture/test_extractor_modules.py`

Builds a package-level (not file-level) import graph for `src/`. Two `src.foo` files importing two different things from `src.bar` produce one edge with `weight=2`.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_extractor_modules.py
from arch.extractors.modules import extract_module_graph


def test_collapses_to_package_level_with_weights(fixture_src_tree):
    root = fixture_src_tree({
        "src/foo/__init__.py": "",
        "src/foo/a.py": "from bar.thing import X\nfrom bar.thing import Y",
        "src/foo/b.py": "from bar.other import Z",
        "src/bar/__init__.py": "",
        "src/bar/thing.py": "X = 1\nY = 2",
        "src/bar/other.py": "Z = 3",
    })
    g = extract_module_graph(root / "src")
    edges = {(e.from_module, e.to_module): e.weight for e in g.edges}
    # foo -> bar should aggregate three import statements
    assert edges.get(("src.foo", "src.bar")) == 3


def test_excludes_stdlib_and_third_party(fixture_src_tree):
    root = fixture_src_tree({
        "src/foo.py": "import os\nimport pydantic\nfrom bar import X",
        "src/bar.py": "X = 1",
    })
    g = extract_module_graph(root / "src")
    targets = {e.to_module for e in g.edges}
    assert "src.bar" in targets
    assert "os" not in targets
    assert "pydantic" not in targets
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_modules.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/arch/extractors/modules.py
"""Build a package-level import graph for src/."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from arch._models import ModuleEdge, ModuleGraph, ModuleNode


def _package_of(path: Path, src_root: Path) -> str:
    """Return the dotted package name for `path` relative to `src_root`'s parent.

    A file at src/foo/a.py belongs to package src.foo.
    A file at src/foo.py belongs to package src.
    """
    rel = path.relative_to(src_root.parent)
    parts = rel.with_suffix("").parts
    return ".".join(parts[:-1]) if len(parts) > 1 else parts[0]


def _module_targets(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append(alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            out.append(node.module.split(".")[0])
    return out


def extract_module_graph(src_dir: Path) -> ModuleGraph:
    src_dir = Path(src_dir).resolve()
    nodes: set[str] = set()
    raw_edges: Counter[tuple[str, str]] = Counter()

    # First pass: collect all package names that exist under src/.
    local_packages: set[str] = set()
    for py in src_dir.rglob("*.py"):
        local_packages.add(_package_of(py, src_dir))

    for py in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        from_pkg = _package_of(py, src_dir)
        nodes.add(from_pkg)
        for stmt in ast.walk(tree):
            for tgt in _module_targets(stmt):
                # Resolve "bar" → "src.bar" if src.bar exists
                resolved = f"src.{tgt}" if f"src.{tgt}" in local_packages else tgt
                if resolved not in local_packages:
                    continue  # external dep, skip
                if resolved == from_pkg:
                    continue  # self-import
                raw_edges[(from_pkg, resolved)] += 1
                nodes.add(resolved)

    edges = [
        ModuleEdge(from_module=a, to_module=b, weight=w)
        for (a, b), w in sorted(raw_edges.items())
    ]
    return ModuleGraph(
        nodes=[ModuleNode(name=n) for n in sorted(nodes)],
        edges=edges,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_modules.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.modules import extract_module_graph; g = extract_module_graph(Path('src')); print(f'{len(g.nodes)} packages, {len(g.edges)} edges')"
```

Expected: roughly 5-15 packages and dozens of edges (varies with how the codebase is split).

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/modules.py tests/architecture/test_extractor_modules.py
git commit -m "feat(arch): module graph extractor (package-level, weighted)"
```

---

## Task 5: Events extractor

**Files:**
- Create: `src/arch/extractors/events.py`
- Test: `tests/architecture/test_extractor_events.py`

Walks `src/*.py`, tracks `EventBus.publish(EventType.X, ...)` and `event_bus.subscribe(EventType.X, ...)` (and the same with `bus.publish` / `self.event_bus.publish` / etc.). Pattern: any `<expr>.publish(EventType.<NAME>, ...)` is a publisher; same for subscribe. Records `module:function` of the enclosing function.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_extractor_events.py
from arch.extractors.events import extract_event_topology


def test_finds_publishers_and_subscribers(fixture_src_tree):
    root = fixture_src_tree({
        "src/widget_loop.py": '''
            from events import EventType
            class WidgetLoop:
                def __init__(self, bus):
                    bus.subscribe(EventType.PR_OPENED, self.on_open)
                def fire(self, bus):
                    bus.publish(EventType.WIDGET_DONE, payload={})
        ''',
    })
    topo = extract_event_topology(root / "src")
    events = {e.event: e for e in topo.events}
    assert "PR_OPENED" in events
    assert "WIDGET_DONE" in events
    assert any("widget_loop" in s for s in events["PR_OPENED"].subscribers)
    assert any("widget_loop" in p for p in events["WIDGET_DONE"].publishers)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_events.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/arch/extractors/events.py
"""Extract EventBus publish/subscribe topology from src/."""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from arch._models import EventBusTopology, EventEdge


def _module_dotted(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)
    return ".".join(rel.with_suffix("").parts)


def _event_name(args: list[ast.expr]) -> str | None:
    if not args:
        return None
    first = args[0]
    if isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name):
        if first.value.id == "EventType":
            return first.attr
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str):
        self.module = module
        self.publishers: dict[str, list[str]] = defaultdict(list)
        self.subscribers: dict[str, list[str]] = defaultdict(list)
        self._fn_stack: list[str] = []

    def _qualified(self) -> str:
        if not self._fn_stack:
            return self.module
        return f"{self.module}:{'.'.join(self._fn_stack)}"

    def visit_FunctionDef(self, node):
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"publish", "subscribe"}:
            ev = _event_name(node.args)
            if ev:
                target = self.publishers if node.func.attr == "publish" else self.subscribers
                target[ev].append(self._qualified())
        self.generic_visit(node)


def extract_event_topology(src_dir: Path) -> EventBusTopology:
    src_dir = Path(src_dir).resolve()
    pubs: dict[str, set[str]] = defaultdict(set)
    subs: dict[str, set[str]] = defaultdict(set)
    for py in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        v = _Visitor(_module_dotted(py, src_dir))
        v.visit(tree)
        for ev, lst in v.publishers.items():
            pubs[ev].update(lst)
        for ev, lst in v.subscribers.items():
            subs[ev].update(lst)

    events = sorted(set(pubs) | set(subs))
    return EventBusTopology(events=[
        EventEdge(
            event=e,
            publishers=sorted(pubs[e]),
            subscribers=sorted(subs[e]),
        )
        for e in events
    ])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_events.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.events import extract_event_topology; t = extract_event_topology(Path('src')); print(f'{len(t.events)} events'); [print(f'  {e.event}: {len(e.publishers)} pubs, {len(e.subscribers)} subs') for e in t.events[:10]]"
```

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/events.py tests/architecture/test_extractor_events.py
git commit -m "feat(arch): events extractor (publish/subscribe topology)"
```

---

## Task 6: ADR cross-reference extractor

**Files:**
- Create: `src/arch/extractors/adr_xref.py`
- Test: `tests/architecture/test_extractor_adr_xref.py`

For each ADR file, scan its body for `module:symbol` references (the convention CLAUDE.md enforces) and bare `src/path/to/file.py` references. Emit a forward index. The reverse index is computed by the generator at write time.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_extractor_adr_xref.py
from arch.extractors.adr_xref import extract_adr_refs


def test_extracts_module_symbol_and_path_refs(fixture_src_tree):
    root = fixture_src_tree({
        "docs/adr/0001-thing.md": '''
            # ADR-0001: Thing

            Reference src/foo.py and another at src/bar.py:Bar.
            See also `src/baz.py:baz_function`.
        ''',
        "docs/adr/0002-other.md": "# ADR-0002: Other\n\nNo refs here.\n",
    })
    idx = extract_adr_refs(root / "docs/adr")
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    assert "ADR-0001" in by_id
    assert "ADR-0002" in by_id
    refs = by_id["ADR-0001"].cited_modules
    assert "src.foo" in refs
    assert "src.bar" in refs
    assert "src.baz" in refs
    assert by_id["ADR-0002"].cited_modules == []


def test_skips_readme_and_template(fixture_src_tree):
    root = fixture_src_tree({
        "docs/adr/README.md": "# Index\n",
        "docs/adr/0001-thing.md": "# ADR-0001\n",
    })
    idx = extract_adr_refs(root / "docs/adr")
    assert [r.adr_id for r in idx.adr_to_modules] == ["ADR-0001"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_adr_xref.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/arch/extractors/adr_xref.py
"""Parse ADRs for module:symbol and src/ path references."""
from __future__ import annotations

import re
from pathlib import Path

from arch._models import ADRRef, ADRRefIndex

_ADR_FILE_RE = re.compile(r"^(\d{4})-.+\.md$")
# Match "src/foo/bar.py", "src/foo/bar.py:Class", "src/foo/bar.py:func_name"
_PATH_REF_RE = re.compile(r"\bsrc/[\w/]+\.py(?::[\w_]+)?")


def _module_from_path_ref(s: str) -> str:
    """`src/foo/bar.py:Class` -> `src.foo.bar`."""
    path_part = s.split(":", 1)[0]
    return path_part.removesuffix(".py").replace("/", ".")


def extract_adr_refs(adr_dir: Path) -> ADRRefIndex:
    adr_dir = Path(adr_dir).resolve()
    refs: list[ADRRef] = []
    for md in sorted(adr_dir.glob("*.md")):
        m = _ADR_FILE_RE.match(md.name)
        if not m:
            continue
        adr_id = f"ADR-{m.group(1)}"
        text = md.read_text()
        modules = sorted({_module_from_path_ref(s) for s in _PATH_REF_RE.findall(text)})
        refs.append(ADRRef(adr_id=adr_id, cited_modules=modules))
    refs.sort(key=lambda r: r.adr_id)
    return ADRRefIndex(adr_to_modules=refs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_adr_xref.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.adr_xref import extract_adr_refs; idx = extract_adr_refs(Path('docs/adr')); print(f'{len(idx.adr_to_modules)} ADRs indexed'); [print(f'  {r.adr_id}: {len(r.cited_modules)} module refs') for r in idx.adr_to_modules[:5]]"
```

Expected: 49 ADRs indexed.

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/adr_xref.py tests/architecture/test_extractor_adr_xref.py
git commit -m "feat(arch): ADR cross-reference extractor (forward index)"
```

---

## Task 7: MockWorld extractor

**Files:**
- Create: `src/arch/extractors/mockworld.py`
- Test: `tests/architecture/test_extractor_mockworld.py`

Walks `tests/scenarios/fakes/`, for each `Fake*` class records its name, module, source path. For each fake, scans `tests/scenarios/test_*.py` for imports of that fake — that file is recorded as a scenario user. Best-effort port matching reuses the same heuristic as the ports extractor (Fake<PortStem>).

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_extractor_mockworld.py
from arch.extractors.mockworld import extract_mockworld_map


def test_indexes_fakes_and_scenario_uses(fixture_src_tree):
    root = fixture_src_tree({
        "tests/scenarios/fakes/__init__.py": "",
        "tests/scenarios/fakes/fake_widget.py": "class FakeWidget:\n    def make(self): ...",
        "tests/scenarios/test_widget_scenario.py": '''
            from tests.scenarios.fakes.fake_widget import FakeWidget
            def test_thing(): pass
        ''',
        "tests/scenarios/test_unrelated.py": "def test_other(): pass",
    })
    m = extract_mockworld_map(
        fakes_dir=root / "tests/scenarios/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert len(m.fakes) == 1
    f = m.fakes[0]
    assert f.name == "FakeWidget"
    assert "test_widget_scenario" in str(f.used_in_scenarios)
    assert not any("test_unrelated" in s for s in f.used_in_scenarios)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_extractor_mockworld.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/arch/extractors/mockworld.py
"""Extract MockWorldMap from tests/scenarios/fakes/ and scenario users."""
from __future__ import annotations

import ast
from pathlib import Path

from arch._models import FakeInfo, MockWorldMap


def _module_dotted(path: Path) -> str:
    parts = path.with_suffix("").parts
    # Trim leading components until we hit "tests"
    if "tests" in parts:
        idx = parts.index("tests")
        return ".".join(parts[idx:])
    return ".".join(parts)


def _fake_classes(fakes_dir: Path, repo_root: Path) -> list[FakeInfo]:
    """Walk fakes_dir for `class Fake*:` declarations.

    `source_path` is recorded as repo-root-relative (so generated Markdown is
    portable and diffable; absolute paths would leak the developer's home dir
    into committed `docs/arch/generated/mockworld.md`).
    """
    out: list[FakeInfo] = []
    if not fakes_dir.exists():
        return out
    for py in sorted(fakes_dir.glob("*.py")):
        if py.name.startswith("__") or py.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Fake"):
                out.append(FakeInfo(
                    name=node.name,
                    module=_module_dotted(py),
                    source_path=str(py.relative_to(repo_root)),
                ))
    return out


def _scenario_uses(scenarios_dir: Path, fake_module: str, fake_name: str) -> list[str]:
    """Return the list of test files that import the fake."""
    out: list[str] = []
    if not scenarios_dir.exists():
        return out
    for py in sorted(scenarios_dir.rglob("test_*.py")):
        text = py.read_text()
        # Cheap textual match — false positives are rare and harmless here.
        if fake_module in text and fake_name in text:
            out.append(str(py))
    return out


def extract_mockworld_map(*, fakes_dir: Path, scenarios_dir: Path) -> MockWorldMap:
    fakes_dir = Path(fakes_dir).resolve()
    scenarios_dir = Path(scenarios_dir).resolve()
    # Repo root: assumes fakes_dir == <repo_root>/tests/scenarios/fakes
    repo_root = fakes_dir.parents[2]

    fakes = _fake_classes(fakes_dir, repo_root)
    enriched: list[FakeInfo] = []
    for f in fakes:
        # Compute candidate Port name: FakeWidget -> WidgetPort
        stem = f.name.removeprefix("Fake")
        candidate_port = f"{stem}Port" if stem else None
        scenarios = _scenario_uses(scenarios_dir, f.module, f.name)
        # Trim each scenario path to repo-root-relative
        rel_scenarios = []
        for s in scenarios:
            try:
                rel_scenarios.append(str(Path(s).relative_to(repo_root)))
            except ValueError:
                rel_scenarios.append(s)
        enriched.append(f.model_copy(update={
            "implements_port": candidate_port,
            "used_in_scenarios": sorted(rel_scenarios),
        }))
    enriched.sort(key=lambda f: f.name)
    return MockWorldMap(fakes=enriched)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_extractor_mockworld.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -c "from pathlib import Path; from arch.extractors.mockworld import extract_mockworld_map; m = extract_mockworld_map(fakes_dir=Path('tests/scenarios/fakes'), scenarios_dir=Path('tests/scenarios')); print(f'{len(m.fakes)} fakes'); [print(f'  {f.name} -> {f.implements_port}, used in {len(f.used_in_scenarios)} scenarios') for f in m.fakes]"
```

Expected: ~13 fakes, each candidate-mapped to a `XxxPort` and listed with their scenario users.

- [ ] **Step 6: Commit**

```bash
git add src/arch/extractors/mockworld.py tests/architecture/test_extractor_mockworld.py
git commit -m "feat(arch): MockWorld extractor (fakes + scenario uses)"
```

---

## Tasks 8-15: Generators

Each generator is a pure function `(model: SpecificModel) -> str` that emits Markdown with embedded Mermaid. Follows a uniform pattern; only the body content varies. **Common discipline for every generator:**

- No timestamps in the body (those live in `.meta.json`).
- Sort everything alphabetically (or topologically, where that's natural).
- Use Mermaid fenced blocks (` ```mermaid `) so MkDocs Material renders them.
- Begin every page with a one-line `<!-- generated by src.arch.generators.<NAME>; do not hand-edit -->` comment.
- End with a "Last regeneration source" footer (filled by the runner, not the generator — the generator emits a sentinel `<!-- {{ARCH_FOOTER}} -->` that the runner replaces).

### Task 8: `loop_registry` generator

**Files:**
- Create: `src/arch/generators/loop_registry.py`
- Test: `tests/architecture/test_generator_loop_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_loop_registry.py
from arch._models import LoopInfo
from arch.generators.loop_registry import render_loop_registry


def test_renders_table_with_one_row_per_loop():
    loops = [
        LoopInfo(name="AlphaLoop", module="src.alpha_loop",
                 source_path="src/alpha_loop.py", tick_interval_seconds=300,
                 event_subscriptions=["PR_OPENED"], kill_switch_var="HYDRAFLOW_DISABLE_ALPHA_LOOP",
                 adr_refs=["ADR-0029"]),
        LoopInfo(name="BetaLoop", module="src.beta_loop",
                 source_path="src/beta_loop.py"),
    ]
    md = render_loop_registry(loops)
    assert "# Loop Registry" in md
    assert "AlphaLoop" in md
    assert "BetaLoop" in md
    assert "300" in md  # tick interval
    assert "HYDRAFLOW_DISABLE_ALPHA_LOOP" in md
    assert "ADR-0029" in md
    assert md.count("\n| ") >= 3  # header + separator + 2 rows
    assert "{{ARCH_FOOTER}}" in md


def test_byte_stable_under_unsorted_input():
    a = [LoopInfo(name="B", module="m", source_path="p"),
         LoopInfo(name="A", module="m", source_path="p")]
    b = [LoopInfo(name="A", module="m", source_path="p"),
         LoopInfo(name="B", module="m", source_path="p")]
    assert render_loop_registry(a) == render_loop_registry(b)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_loop_registry.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/loop_registry.py
"""Render the loop registry markdown table."""
from __future__ import annotations

from arch._models import LoopInfo

_HEADER = "# Loop Registry\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.loop_registry; do not hand-edit -->\n\n"
    "All `BaseBackgroundLoop` subclasses discovered in `src/`. Generated "
    "from AST (no class introspection — see ADR-0049 for kill-switch convention).\n\n"
)
_TABLE_HEAD = (
    "| Loop | Module | Tick (s) | Kill Switch | Events | ADRs |\n"
    "|---|---|---|---|---|---|\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _row(l: LoopInfo) -> str:
    tick = str(l.tick_interval_seconds) if l.tick_interval_seconds else "—"
    kill = f"`{l.kill_switch_var}`" if l.kill_switch_var else "—"
    events = ", ".join(l.event_subscriptions) or "—"
    adrs = ", ".join(l.adr_refs) or "—"
    module = f"[`{l.module}`]({{{{REPO_URL}}}}/blob/main/{l.source_path})"
    return f"| **{l.name}** | {module} | {tick} | {kill} | {events} | {adrs} |"


def render_loop_registry(loops: list[LoopInfo]) -> str:
    sorted_loops = sorted(loops, key=lambda loop: loop.name)
    rows = "\n".join(_row(l) for l in sorted_loops)
    return _HEADER + _PREAMBLE + _TABLE_HEAD + rows + "\n" + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_loop_registry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/loop_registry.py tests/architecture/test_generator_loop_registry.py
git commit -m "feat(arch): loop registry generator"
```

### Task 9: `port_map` generator

**Files:**
- Create: `src/arch/generators/port_map.py`
- Test: `tests/architecture/test_generator_port_map.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_port_map.py
from arch._models import PortInfo, PortAdapterInfo
from arch.generators.port_map import render_port_map


def test_renders_port_with_adapter_and_fake():
    ports = [PortInfo(
        name="WidgetPort",
        module="src.ports",
        source_path="src/ports.py",
        methods=["make", "break_"],
        adapters=[PortAdapterInfo(name="WidgetAdapter", module="src.widget_adapter", source_path="src/widget_adapter.py")],
        fake=PortAdapterInfo(name="FakeWidget", module="tests.scenarios.fakes.fake_widget", source_path="tests/scenarios/fakes/fake_widget.py", is_fake=True),
    )]
    md = render_port_map(ports)
    assert "WidgetPort" in md
    assert "WidgetAdapter" in md
    assert "FakeWidget" in md
    assert "```mermaid" in md
    assert "WidgetPort --> WidgetAdapter" in md
    assert "WidgetPort -.-> FakeWidget" in md  # fakes drawn dashed


def test_flags_port_without_fake():
    ports = [PortInfo(name="LonelyPort", module="src.ports", source_path="src/ports.py", methods=["x"], fake=None)]
    md = render_port_map(ports)
    assert "⚠️" in md or "no fake" in md.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_port_map.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/port_map.py
"""Render the port map: Mermaid graph + per-port detail table."""
from __future__ import annotations

from arch._models import PortInfo

_HEADER = "# Port Map\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.port_map; do not hand-edit -->\n\n"
    "Hexagonal boundaries. Each `*Port` Protocol with its concrete "
    "adapter(s) and fake (per ADR-0047). Ports without a fake are "
    "flagged ⚠️ — fakes are required for scenario testing.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _mermaid(ports: list[PortInfo]) -> str:
    lines = ["```mermaid", "graph LR"]
    for p in ports:
        for a in p.adapters:
            lines.append(f"    {p.name} --> {a.name}")
        if p.fake:
            lines.append(f"    {p.name} -.-> {p.fake.name}")
    lines.append("```")
    return "\n".join(lines)


def _detail_section(p: PortInfo) -> str:
    lines = [f"### {p.name}", "", f"- Module: `{p.module}`",
             f"- Methods: {', '.join(f'`{m}`' for m in p.methods) or '—'}"]
    if p.adapters:
        lines.append("- Adapters:")
        for a in p.adapters:
            lines.append(f"  - `{a.name}` (`{a.module}`)")
    else:
        lines.append("- Adapters: —")
    if p.fake:
        lines.append(f"- Fake: `{p.fake.name}` (`{p.fake.module}`)")
    else:
        lines.append("- Fake: ⚠️ no fake (every Port needs a fake per ADR-0047)")
    return "\n".join(lines)


def render_port_map(ports: list[PortInfo]) -> str:
    sorted_ports = sorted(ports, key=lambda p: p.name)
    body = _mermaid(sorted_ports) + "\n\n## Details\n\n"
    body += "\n\n".join(_detail_section(p) for p in sorted_ports)
    return _HEADER + _PREAMBLE + body + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_port_map.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/port_map.py tests/architecture/test_generator_port_map.py
git commit -m "feat(arch): port map generator with Mermaid graph"
```

### Task 10: `label_state` generator

**Files:**
- Create: `src/arch/generators/label_state.py`
- Test: `tests/architecture/test_generator_label_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_label_state.py
from arch._models import LabelStateMachine, LabelTransition
from arch.generators.label_state import render_label_state


def test_renders_state_diagram_v2_block():
    sm = LabelStateMachine(
        states=["a", "b", "c"],
        transitions=[
            LabelTransition(from_state="a", to_state="b", trigger="trig1"),
            LabelTransition(from_state="b", to_state="c", trigger="trig2"),
        ],
    )
    md = render_label_state(sm)
    assert "stateDiagram-v2" in md
    assert "a --> b" in md
    assert "b --> c" in md
    assert "trig1" in md


def test_handles_empty_state_machine():
    md = render_label_state(LabelStateMachine())
    assert "no transitions" in md.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_label_state.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/label_state.py
from __future__ import annotations

from arch._models import LabelStateMachine

_HEADER = "# Label State Machine\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.label_state; do not hand-edit -->\n\n"
    "Live transitions extracted from source. Compared against the "
    "Mermaid block in ADR-0002 by `tests/architecture/test_label_state_matches_adr0002.py`.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def render_label_state(sm: LabelStateMachine) -> str:
    if not sm.transitions:
        return _HEADER + _PREAMBLE + "_(no transitions discovered)_\n" + _FOOTER
    lines = ["```mermaid", "stateDiagram-v2"]
    for t in sm.transitions:
        # Mermaid sanitization: replace hyphens (mermaid doesn't tolerate them as identifiers)
        a = t.from_state.replace("-", "_")
        b = t.to_state.replace("-", "_")
        label = f": {t.trigger}" if t.trigger else ""
        lines.append(f"    {a} --> {b}{label}")
    lines.append("```")
    return _HEADER + _PREAMBLE + "\n".join(lines) + "\n" + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_label_state.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/label_state.py tests/architecture/test_generator_label_state.py
git commit -m "feat(arch): label state machine generator"
```

### Task 11: `module_graph` generator

**Files:**
- Create: `src/arch/generators/module_graph.py`
- Test: `tests/architecture/test_generator_module_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_module_graph.py
from arch._models import ModuleEdge, ModuleGraph, ModuleNode
from arch.generators.module_graph import render_module_graph


def test_renders_mermaid_with_weighted_edges():
    g = ModuleGraph(
        nodes=[ModuleNode(name="src.foo"), ModuleNode(name="src.bar")],
        edges=[ModuleEdge(from_module="src.foo", to_module="src.bar", weight=3)],
    )
    md = render_module_graph(g)
    assert "graph LR" in md
    # Node IDs are sanitized via _safe_id (`.` → `_`); weights are quoted.
    assert 'src_foo -- "3" --> src_bar' in md
    assert 'src_foo["src.foo"]' in md  # node label preserves the dotted name
    assert 'src_bar["src.bar"]' in md
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_module_graph.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/module_graph.py
from __future__ import annotations

from arch._models import ModuleGraph

_HEADER = "# Module Graph\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.module_graph; do not hand-edit -->\n\n"
    "Package-level import graph for `src/`. Edge weight = number of "
    "import statements aggregated across files.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _safe_id(name: str) -> str:
    return name.replace(".", "_")


def render_module_graph(g: ModuleGraph) -> str:
    if not g.nodes:
        return _HEADER + _PREAMBLE + "_(no modules discovered)_\n" + _FOOTER
    lines = ["```mermaid", "graph LR"]
    for n in g.nodes:
        lines.append(f"    {_safe_id(n.name)}[\"{n.name}\"]")
    for e in g.edges:
        lines.append(f"    {_safe_id(e.from_module)} -- \"{e.weight}\" --> {_safe_id(e.to_module)}")
    lines.append("```")
    return _HEADER + _PREAMBLE + "\n".join(lines) + "\n" + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_module_graph.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/module_graph.py tests/architecture/test_generator_module_graph.py
git commit -m "feat(arch): module graph generator"
```

### Task 12: `event_bus` generator

**Files:**
- Create: `src/arch/generators/event_bus.py`
- Test: `tests/architecture/test_generator_event_bus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_event_bus.py
from arch._models import EventBusTopology, EventEdge
from arch.generators.event_bus import render_event_bus


def test_renders_publishers_subscribers_table():
    topo = EventBusTopology(events=[
        EventEdge(event="PR_OPENED",
                  publishers=["src.runner:notify"],
                  subscribers=["src.widget_loop:on_open", "src.audit:hook"]),
        EventEdge(event="ORPHAN", publishers=["src.foo:f"], subscribers=[]),
    ])
    md = render_event_bus(topo)
    assert "PR_OPENED" in md
    assert "src.widget_loop" in md
    assert "ORPHAN" in md
    assert "no subscribers" in md.lower() or "⚠️" in md
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_event_bus.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/event_bus.py
from __future__ import annotations

from arch._models import EventBusTopology

_HEADER = "# Event Bus Topology\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.event_bus; do not hand-edit -->\n\n"
    "Every `EventType` published or subscribed in `src/`. Events with "
    "no subscribers are flagged ⚠️ (likely dead).\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def render_event_bus(topo: EventBusTopology) -> str:
    if not topo.events:
        return _HEADER + _PREAMBLE + "_(no events discovered)_\n" + _FOOTER
    rows = []
    for e in topo.events:
        flag = " ⚠️" if not e.subscribers else ""
        pubs = "<br>".join(f"`{p}`" for p in e.publishers) or "—"
        subs = "<br>".join(f"`{s}`" for s in e.subscribers) or "—"
        rows.append(f"| **{e.event}**{flag} | {pubs} | {subs} |")
    table = (
        "| Event | Publishers | Subscribers |\n"
        "|---|---|---|\n" + "\n".join(rows)
    )
    return _HEADER + _PREAMBLE + table + "\n" + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_event_bus.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/event_bus.py tests/architecture/test_generator_event_bus.py
git commit -m "feat(arch): event bus topology generator"
```

### Task 13: `adr_cross_reference` generator

**Files:**
- Create: `src/arch/generators/adr_cross_reference.py`
- Test: `tests/architecture/test_generator_adr_cross_reference.py`

Note: file is `adr_cross_reference.py` (per spec §4.2 disambiguation note); the extractor is `adr_xref.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_adr_cross_reference.py
from arch._models import ADRRef, ADRRefIndex
from arch.generators.adr_cross_reference import render_adr_cross_reference


def test_emits_forward_and_reverse_tables():
    idx = ADRRefIndex(adr_to_modules=[
        ADRRef(adr_id="ADR-0001", cited_modules=["src.foo", "src.bar"]),
        ADRRef(adr_id="ADR-0002", cited_modules=["src.foo"]),
    ])
    md = render_adr_cross_reference(idx)
    assert "## ADR → Modules" in md
    assert "## Module → ADRs" in md
    assert "src.foo" in md
    assert "ADR-0001" in md
    # src.foo is cited by both ADRs
    assert "ADR-0001, ADR-0002" in md or ("ADR-0001" in md and "ADR-0002" in md)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_adr_cross_reference.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/adr_cross_reference.py
from __future__ import annotations

from collections import defaultdict

from arch._models import ADRRefIndex

_HEADER = "# ADR Cross-Reference\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.adr_cross_reference; do not hand-edit -->\n\n"
    "Bidirectional index between ADRs and the source modules they cite. "
    "Powers \"Why this exists\" backlinks across the site.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def render_adr_cross_reference(idx: ADRRefIndex) -> str:
    forward = sorted(idx.adr_to_modules, key=lambda r: r.adr_id)
    reverse: dict[str, list[str]] = defaultdict(list)
    for r in forward:
        for m in r.cited_modules:
            reverse[m].append(r.adr_id)

    fwd = "## ADR → Modules\n\n| ADR | Modules cited |\n|---|---|\n"
    fwd += "\n".join(
        f"| {r.adr_id} | {', '.join(f'`{m}`' for m in r.cited_modules) or '—'} |"
        for r in forward
    )

    rev = "\n\n## Module → ADRs\n\n| Module | Cited by |\n|---|---|\n"
    rev += "\n".join(
        f"| `{m}` | {', '.join(sorted(set(adrs)))} |"
        for m, adrs in sorted(reverse.items())
    )

    return _HEADER + _PREAMBLE + fwd + rev + "\n" + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_adr_cross_reference.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/adr_cross_reference.py tests/architecture/test_generator_adr_cross_reference.py
git commit -m "feat(arch): ADR cross-reference generator (forward + reverse)"
```

### Task 14: `mockworld_map` generator

**Files:**
- Create: `src/arch/generators/mockworld_map.py`
- Test: `tests/architecture/test_generator_mockworld_map.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_generator_mockworld_map.py
from arch._models import FakeInfo, MockWorldMap
from arch.generators.mockworld_map import render_mockworld_map


def test_emits_table_and_mermaid():
    m = MockWorldMap(fakes=[
        FakeInfo(name="FakeWidget", module="tests.scenarios.fakes.fake_widget",
                 source_path="tests/scenarios/fakes/fake_widget.py",
                 implements_port="WidgetPort",
                 used_in_scenarios=["tests/scenarios/test_widget.py"]),
    ])
    md = render_mockworld_map(m)
    assert "FakeWidget" in md
    assert "WidgetPort" in md
    assert "test_widget" in md
    assert "```mermaid" in md
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_mockworld_map.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/generators/mockworld_map.py
from __future__ import annotations

from arch._models import MockWorldMap

_HEADER = "# MockWorld Map\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.mockworld_map; do not hand-edit -->\n\n"
    "All fakes under `tests/scenarios/fakes/`, the `*Port` each implements "
    "(by name match), and the scenarios that wire them. Per ADR-0022 "
    "(MockWorld) and ADR-0047 (fake-adapter contract testing).\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def render_mockworld_map(m: MockWorldMap) -> str:
    if not m.fakes:
        return _HEADER + _PREAMBLE + "_(no fakes discovered)_\n" + _FOOTER
    rows = []
    for f in m.fakes:
        port = f.implements_port or "—"
        scenarios = "<br>".join(f"`{s}`" for s in f.used_in_scenarios) or "—"
        rows.append(f"| **{f.name}** | `{port}` | {scenarios} |")
    table = (
        "## Fakes\n\n"
        "| Fake | Implements | Used in scenarios |\n"
        "|---|---|---|\n" + "\n".join(rows)
    )
    mermaid_lines = ["", "## Wiring", "", "```mermaid", "graph LR"]
    for f in m.fakes:
        port = f.implements_port or f.name
        mermaid_lines.append(f"    {f.name} -.-> {port}")
        for s in f.used_in_scenarios[:3]:  # cap to keep diagram readable
            scen_id = s.replace("/", "_").replace(".", "_")
            mermaid_lines.append(f"    {scen_id}([{s}]) --> {f.name}")
    mermaid_lines.append("```")
    return _HEADER + _PREAMBLE + table + "\n" + "\n".join(mermaid_lines) + _FOOTER
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_mockworld_map.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/generators/mockworld_map.py tests/architecture/test_generator_mockworld_map.py
git commit -m "feat(arch): MockWorld map generator (table + Mermaid wiring)"
```

### Task 15: `changelog` generator

**Files:**
- Create: `src/arch/generators/changelog.py`
- Test: `tests/architecture/test_generator_changelog.py`

Reads the last 90 days of commits via `git log --since=90.days.ago -- <pathspecs>`. Emits a chronological list grouped by week. Pure function over the parsed `git log` output (the runner runs `git log` and feeds the generator a list of `CommitInfo` records — keeping the generator pure).

- [ ] **Step 1: Add CommitInfo model**

Add to `src/arch/_models.py`:

```python
class CommitInfo(BaseModel):
    sha: str
    iso_date: str  # YYYY-MM-DD
    subject: str
    pr_number: int | None = None  # parsed from "(#NNNN)" suffix if present
```

- [ ] **Step 2: Write the failing test**

```python
# tests/architecture/test_generator_changelog.py
from arch._models import CommitInfo
from arch.generators.changelog import render_changelog


def test_groups_by_iso_week_descending():
    commits = [
        CommitInfo(sha="aaa1111", iso_date="2026-04-01", subject="early thing"),
        CommitInfo(sha="bbb2222", iso_date="2026-04-20", subject="recent thing", pr_number=42),
    ]
    md = render_changelog(commits)
    pos_late = md.index("recent thing")
    pos_early = md.index("early thing")
    assert pos_late < pos_early  # newest first
    assert "(#42)" in md or "PR #42" in md


def test_handles_empty_input():
    md = render_changelog([])
    assert "no recent" in md.lower() or "_(empty" in md
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/architecture/test_generator_changelog.py -v
```

- [ ] **Step 4: Implement**

```python
# src/arch/generators/changelog.py
from __future__ import annotations

from collections import defaultdict
from datetime import date

from arch._models import CommitInfo

_HEADER = "# Architecture Changelog (last 90 days)\n\n"
_PREAMBLE = (
    "<!-- generated by src.arch.generators.changelog; do not hand-edit -->\n\n"
    "Commits touching `docs/arch/`, `docs/adr/`, `docs/wiki/`, "
    "`src/arch/`, or `mkdocs.yml`. Grouped by ISO week.\n\n"
)
_FOOTER = "\n\n{{ARCH_FOOTER}}\n"


def _iso_week(iso_date: str) -> str:
    y, m, d = (int(x) for x in iso_date.split("-"))
    yr, wk, _ = date(y, m, d).isocalendar()
    return f"{yr}-W{wk:02d}"


def render_changelog(commits: list[CommitInfo]) -> str:
    if not commits:
        return _HEADER + _PREAMBLE + "_(empty — no recent architecture-touching commits)_\n" + _FOOTER

    by_week: dict[str, list[CommitInfo]] = defaultdict(list)
    for c in commits:
        by_week[_iso_week(c.iso_date)].append(c)

    chunks = []
    for wk in sorted(by_week, reverse=True):
        chunks.append(f"## {wk}\n")
        for c in sorted(by_week[wk], key=lambda c: c.iso_date, reverse=True):
            pr = f" (#{c.pr_number})" if c.pr_number else ""
            chunks.append(f"- `{c.sha[:7]}` — {c.subject}{pr} *({c.iso_date})*")
        chunks.append("")
    return _HEADER + _PREAMBLE + "\n".join(chunks) + _FOOTER
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/architecture/test_generator_changelog.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/arch/_models.py src/arch/generators/changelog.py tests/architecture/test_generator_changelog.py
git commit -m "feat(arch): changelog generator (90-day rolling, by ISO week)"
```

---

## Task 16: Runner CLI

**Files:**
- Create: `src/arch/runner.py`
- Test: `tests/architecture/test_runner.py`

The runner is the orchestration entry point. Two modes:
- `--emit`: regenerate everything to `docs/arch/generated/`, update `.meta.json`.
- `--check`: regenerate to a tmpdir, diff against committed `docs/arch/generated/`, exit 1 on diff.

Both modes share the `_compute_artifacts()` core. The runner replaces the `{{ARCH_FOOTER}}` sentinel with a per-artifact regen footer (commit SHA + date) sourced from `git rev-parse HEAD` and `date -u +%F`.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_runner.py
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def populated_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src/widget_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class WidgetLoop(BaseBackgroundLoop):\n"
        "    pass\n"
    )
    (repo / "tests/scenarios/fakes").mkdir(parents=True)
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "docs/adr/0001-thing.md").write_text("# ADR-0001\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_emit_writes_all_eight_artifacts(populated_repo: Path, monkeypatch):
    from arch.runner import emit
    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    expected = {"loops.md", "ports.md", "labels.md", "modules.md",
                "events.md", "adr_xref.md", "mockworld.md", "changelog.md"}
    assert {p.name for p in out.iterdir() if p.suffix == ".md"} == expected
    assert (out.parent / ".meta.json").exists()


def test_check_returns_zero_when_in_sync(populated_repo: Path):
    from arch.runner import emit, check
    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 0


def test_check_returns_one_when_drifted(populated_repo: Path):
    from arch.runner import emit, check
    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    # Add a new loop AFTER baseline emit
    (populated_repo / "src/widget2_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class Widget2Loop(BaseBackgroundLoop):\n    pass\n"
    )
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_runner.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/runner.py
"""CLI entry point for the architecture knowledge runner."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from arch._models import CommitInfo
from arch.extractors.adr_xref import extract_adr_refs
from arch.extractors.events import extract_event_topology
from arch.extractors.labels import extract_labels
from arch.extractors.loops import extract_loops
from arch.extractors.mockworld import extract_mockworld_map
from arch.extractors.modules import extract_module_graph
from arch.extractors.ports import extract_ports
from arch.generators.adr_cross_reference import render_adr_cross_reference
from arch.generators.changelog import render_changelog
from arch.generators.event_bus import render_event_bus
from arch.generators.label_state import render_label_state
from arch.generators.loop_registry import render_loop_registry
from arch.generators.mockworld_map import render_mockworld_map
from arch.generators.module_graph import render_module_graph
from arch.generators.port_map import render_port_map

_ARTIFACT_FILES = ["loops.md", "ports.md", "labels.md", "modules.md",
                   "events.md", "adr_xref.md", "mockworld.md", "changelog.md"]


def _run(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return res.stdout


def _commit_sha(repo_root: Path) -> str:
    sha = _run(["git", "rev-parse", "HEAD"], repo_root).strip()
    return sha or "unknown"


def _git_log_changelog(repo_root: Path) -> list[CommitInfo]:
    pathspecs = ["docs/arch/", "docs/adr/", "docs/wiki/", "src/arch/", "mkdocs.yml"]
    fmt = "%H%x09%cs%x09%s"
    raw = _run(["git", "log", "--since=90.days.ago", f"--pretty=format:{fmt}",
                "--", *pathspecs], repo_root)
    out: list[CommitInfo] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, iso_date, subject = parts
        pr_num: int | None = None
        if subject.endswith(")") and "(#" in subject:
            try:
                pr_num = int(subject.rsplit("(#", 1)[-1].rstrip(")"))
            except ValueError:
                pr_num = None
        out.append(CommitInfo(sha=sha, iso_date=iso_date, subject=subject, pr_number=pr_num))
    return out


def _compute_artifacts(repo_root: Path) -> dict[str, str]:
    """Run all extractors and generators; return {filename: markdown}."""
    src_dir = repo_root / "src"
    fakes_dir = repo_root / "tests/scenarios/fakes"
    scenarios_dir = repo_root / "tests/scenarios"
    adr_dir = repo_root / "docs/adr"

    return {
        "loops.md": render_loop_registry(extract_loops(src_dir)),
        "ports.md": render_port_map(extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)),
        "labels.md": render_label_state(extract_labels(src_dir)),
        "modules.md": render_module_graph(extract_module_graph(src_dir)),
        "events.md": render_event_bus(extract_event_topology(src_dir)),
        "adr_xref.md": render_adr_cross_reference(extract_adr_refs(adr_dir)),
        "mockworld.md": render_mockworld_map(extract_mockworld_map(
            fakes_dir=fakes_dir, scenarios_dir=scenarios_dir)),
        "changelog.md": render_changelog(_git_log_changelog(repo_root)),
    }


def _stamp_footer(body: str, sha: str, source_sha: str) -> str:
    """Replace the {{ARCH_FOOTER}} sentinel with a per-page regen footer.

    The footer is rendered visible italic text (not an HTML comment) so MkDocs
    Material surfaces it to readers. Plan C extends it with the freshness badge.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = (
        f"_Regenerated from commit `{sha[:7]}` on {now}. "
        f"Source last changed at `{source_sha[:7]}`._"
    )
    return body.replace("{{ARCH_FOOTER}}", footer)


def emit(*, repo_root: Path, out_dir: Path) -> None:
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = _commit_sha(repo_root)
    artifacts = _compute_artifacts(repo_root)
    for name, body in artifacts.items():
        # Per-artifact source SHA is the latest commit touching its source surface.
        # For simplicity in v1: same as overall HEAD; refined per-artifact in Plan C if needed.
        stamped = _stamp_footer(body, sha=sha, source_sha=sha)
        (out_dir / name).write_text(stamped)

    meta = {
        "regenerated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": sha,
        "artifacts": {n: {"source_sha": sha} for n in artifacts},
    }
    (out_dir.parent / ".meta.json").write_text(json.dumps(meta, indent=2))


def check(*, repo_root: Path, generated_dir: Path) -> int:
    """Regenerate to a tmpdir, diff against `generated_dir`, return rc 0/1."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "generated"
        emit(repo_root=repo_root, out_dir=tmp)
        for name in _ARTIFACT_FILES:
            actual = (generated_dir / name)
            expected = tmp / name
            if not actual.exists():
                print(f"[arch-check] missing: {name}")
                return 1
            # Compare body sans footer (footer has timestamps that change every run)
            a = _strip_footer(actual.read_text())
            b = _strip_footer(expected.read_text())
            if a != b:
                print(f"[arch-check] drift in {name}")
                return 1
    return 0


def _strip_footer(text: str) -> str:
    """Remove the trailing `_Regenerated from..._` line for diff purposes.

    The line is italicized markdown — `_Regenerated from commit ..._` — and may
    be preceded by leading whitespace from the `_FOOTER` joining. Match
    anywhere on the line, not just the start, so any future leading-character
    tweak doesn't silently break the strip.
    """
    lines = text.splitlines()
    out = [l for l in lines if "_Regenerated from commit" not in l]
    return "\n".join(out)


def _main() -> int:
    p = argparse.ArgumentParser(prog="src.arch.runner",
                                description="Regenerate architecture knowledge artifacts.")
    p.add_argument("--emit", action="store_true", help="Write to docs/arch/generated/.")
    p.add_argument("--check", action="store_true",
                   help="Dry-run; exit 1 if generated/ is stale relative to source.")
    p.add_argument("--repo-root", default=".", type=Path)
    args = p.parse_args()

    repo_root = args.repo_root.resolve()
    generated = repo_root / "docs/arch/generated"
    if args.emit:
        emit(repo_root=repo_root, out_dir=generated)
        return 0
    if args.check:
        return check(repo_root=repo_root, generated_dir=generated)
    p.error("specify --emit or --check")
    return 2


if __name__ == "__main__":
    sys.exit(_main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_runner.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Smoke-test against the real repo**

```bash
python -m src.arch.runner --emit --repo-root .
ls docs/arch/generated/
cat docs/arch/.meta.json
```

Expected: 8 `.md` files exist, `.meta.json` present.

- [ ] **Step 6: Commit**

```bash
git add src/arch/runner.py tests/architecture/test_runner.py
git commit -m "feat(arch): runner CLI (--emit, --check) with .meta.json"
```

---

## Task 17: Freshness module

**Files:**
- Create: `src/arch/freshness.py`
- Test: `tests/architecture/test_arch_freshness.py`

Pure function: given `.meta.json` content + a per-artifact source SHA + clock + a "git log" callable returning the latest source-SHA, returns a `FreshnessBadge` enum (`FRESH`, `SOURCE_MOVED`, `STALE`, `NOT_GENERATED`).

The runner emits the badge state into the page header in Plan C; Plan A delivers the pure logic + test.

- [ ] **Step 1: Write the failing test**

```python
# tests/architecture/test_arch_freshness.py
from datetime import datetime, timedelta, timezone

from arch.freshness import FreshnessBadge, compute_badge


def test_fresh_when_recent_and_source_unchanged():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    regen = (now - timedelta(hours=1)).isoformat()
    meta = {"artifacts": {"loops.md": {"source_sha": "aaa"}},
            "regenerated_at": regen}
    badge = compute_badge("loops.md", meta=meta, current_source_sha="aaa", now=now)
    assert badge == FreshnessBadge.FRESH


def test_source_moved_when_sha_changed_recently():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    regen = (now - timedelta(hours=1)).isoformat()
    meta = {"artifacts": {"loops.md": {"source_sha": "aaa"}},
            "regenerated_at": regen}
    badge = compute_badge("loops.md", meta=meta, current_source_sha="bbb", now=now)
    assert badge == FreshnessBadge.SOURCE_MOVED


def test_stale_when_older_than_seven_days():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    regen = (now - timedelta(days=10)).isoformat()
    meta = {"artifacts": {"loops.md": {"source_sha": "aaa"}},
            "regenerated_at": regen}
    badge = compute_badge("loops.md", meta=meta, current_source_sha="aaa", now=now)
    assert badge == FreshnessBadge.STALE


def test_not_generated_when_meta_absent_or_missing_artifact():
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    assert compute_badge("loops.md", meta=None, current_source_sha="x", now=now) == FreshnessBadge.NOT_GENERATED
    assert compute_badge("loops.md", meta={"artifacts": {}, "regenerated_at": now.isoformat()},
                         current_source_sha="x", now=now) == FreshnessBadge.NOT_GENERATED
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/architecture/test_arch_freshness.py -v
```

- [ ] **Step 3: Implement**

```python
# src/arch/freshness.py
"""Compute the freshness badge state for a generated artifact."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum


class FreshnessBadge(StrEnum):
    FRESH = "fresh"
    SOURCE_MOVED = "source-moved"
    STALE = "stale"
    NOT_GENERATED = "not-generated"


def compute_badge(
    artifact_name: str,
    *,
    meta: dict | None,
    current_source_sha: str,
    now: datetime | None = None,
) -> FreshnessBadge:
    if meta is None:
        return FreshnessBadge.NOT_GENERATED
    artifacts = meta.get("artifacts", {})
    entry = artifacts.get(artifact_name)
    if entry is None:
        return FreshnessBadge.NOT_GENERATED

    regen_iso = meta.get("regenerated_at")
    if not regen_iso:
        return FreshnessBadge.NOT_GENERATED
    regen_at = datetime.fromisoformat(regen_iso)
    if regen_at.tzinfo is None:
        regen_at = regen_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age = now - regen_at

    if age > timedelta(days=7):
        return FreshnessBadge.STALE
    if entry.get("source_sha") != current_source_sha:
        return FreshnessBadge.SOURCE_MOVED
    return FreshnessBadge.FRESH
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/architecture/test_arch_freshness.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/arch/freshness.py tests/architecture/test_arch_freshness.py
git commit -m "feat(arch): freshness badge logic with bootstrap state"
```

---

## Task 18: ADR-0002 label-match test

**Files:**
- Create: `tests/architecture/test_label_state_matches_adr0002.py`

Parses the Mermaid `stateDiagram-v2` block in `docs/adr/0002-labels-as-state-machine.md`, parses the same in the freshly-generated `labels.md`, asserts edge-set equality.

**Important:** if the labels extractor (Task 3) returns an empty state machine because the canonical transition declaration form differs from what the extractor handles, this test fails loudly with an actionable error. **That is the intended behavior** — the failing test is the signal that the extractor needs to learn a new form. Plan A delivers the test even if it's red on first run; the implementer then iterates on Task 3 until it passes.

- [ ] **Step 1: Write the test**

```python
# tests/architecture/test_label_state_matches_adr0002.py
import re
from pathlib import Path

import pytest


_MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_EDGE_RE = re.compile(r"^\s*([\w-]+)\s*-->\s*([\w-]+)(?:\s*:\s*(.+))?$", re.MULTILINE)


def _edges(mermaid_text: str) -> set[tuple[str, str]]:
    return {(m.group(1).replace("_", "-"), m.group(2).replace("_", "-"))
            for m in _EDGE_RE.finditer(mermaid_text)}


def _first_mermaid_block(md_text: str) -> str:
    m = _MERMAID_BLOCK.search(md_text)
    if not m:
        return ""
    return m.group(1)


def test_label_state_matches_adr0002(real_repo_root: Path):
    adr_path = real_repo_root / "docs/adr/0002-labels-as-state-machine.md"
    gen_path = real_repo_root / "docs/arch/generated/labels.md"
    if not gen_path.exists():
        pytest.skip("docs/arch/generated/labels.md not yet emitted; run `make arch-regen`")

    adr_block = _first_mermaid_block(adr_path.read_text())
    gen_block = _first_mermaid_block(gen_path.read_text())
    if not gen_block:
        pytest.fail(
            "labels extractor returned no transitions. "
            "Either the canonical transition declaration in src/ has a form the "
            "extractor doesn't handle (extend src/arch/extractors/labels.py), "
            "or the labels page is genuinely empty. "
            "Run `python -m src.arch.runner --emit` and inspect docs/arch/generated/labels.md."
        )
    if not adr_block:
        pytest.fail("ADR-0002 has no Mermaid block — add one.")

    adr_edges = _edges(adr_block)
    gen_edges = _edges(gen_block)
    missing = adr_edges - gen_edges
    extra = gen_edges - adr_edges
    if missing or extra:
        msg = []
        if missing:
            msg.append(f"In ADR-0002 but not in code: {sorted(missing)}")
        if extra:
            msg.append(f"In code but not in ADR-0002: {sorted(extra)}")
        pytest.fail(
            "Label state machine drift between code and ADR-0002:\n  "
            + "\n  ".join(msg)
            + "\n\nFix: update either the source transition table or ADR-0002."
        )
```

- [ ] **Step 2: Run the test (will fail or skip until generated/ exists)**

```bash
pytest tests/architecture/test_label_state_matches_adr0002.py -v
```

Expected: skips because `generated/` doesn't exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_label_state_matches_adr0002.py
git commit -m "test(arch): ADR-0002 label state machine drift guard"
```

---

## Task 19: ADR-0001 loop-count test (xfail-pending Plan B)

**Files:**
- Create: `tests/architecture/test_loop_count_matches_adr0001.py`

Parses ADR-0001 for the literal phrase "five concurrent" or a loop count, compares against the live count from the loops extractor. **Marked `xfail` in Plan A** — Plan B amends ADR-0001 to either reference the live registry or properly historicize the "five" claim, at which point the xfail mark is removed.

- [ ] **Step 1: Write the test (with xfail)**

```python
# tests/architecture/test_loop_count_matches_adr0001.py
import re
from pathlib import Path

import pytest

from arch.extractors.loops import extract_loops


@pytest.mark.xfail(reason="ADR-0001 is amended in Plan B; remove this xfail once the amendment lands.",
                   strict=False)
def test_loop_count_matches_adr0001(real_repo_root: Path):
    adr = (real_repo_root / "docs/adr/0001-five-concurrent-async-loops.md").read_text()
    if "see `docs/arch/generated/loops.md`" in adr:
        return  # ADR has been updated to reference the live registry
    if "Background" in adr and "historical" in adr:
        return  # ADR has been historicized
    live_loops = extract_loops(real_repo_root / "src")
    pytest.fail(
        f"ADR-0001 still references its original framing but {len(live_loops)} loops exist. "
        "Plan B should amend ADR-0001 to either reference docs/arch/generated/loops.md "
        "or historicize the original claim with a 'Background' section."
    )
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/architecture/test_loop_count_matches_adr0001.py -v
```

Expected: `XFAIL` (or `XPASS` if ADR-0001 already happens to satisfy one of the conditions; either is acceptable).

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_loop_count_matches_adr0001.py
git commit -m "test(arch): ADR-0001 loop count drift guard (xfail until Plan B)"
```

---

## Task 20: Curated-drift test (CI guard's local twin)

**Files:**
- Create: `tests/architecture/test_curated_drift.py`

Runs `runner.check()` against the live repo and asserts rc=0. **This is the test that `arch-regen.yml` (Plan C) will invoke via `python -m src.arch.runner --check`** — Plan A delivers it locally so `make quality` can catch drift on a developer machine before push.

- [ ] **Step 1: Write the test**

```python
# tests/architecture/test_curated_drift.py
from pathlib import Path

import pytest

from arch.runner import check


def test_curated_generated_is_in_sync_with_source(real_repo_root: Path):
    generated = real_repo_root / "docs/arch/generated"
    if not generated.exists():
        pytest.skip("docs/arch/generated/ not yet committed (run `make arch-regen` and commit)")
    rc = check(repo_root=real_repo_root, generated_dir=generated)
    if rc != 0:
        pytest.fail(
            "docs/arch/generated/ is stale relative to source. "
            "Run `make arch-regen` and recommit the changes."
        )
```

- [ ] **Step 2: Run the test (will skip until baseline is committed)**

```bash
pytest tests/architecture/test_curated_drift.py -v
```

Expected: skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_curated_drift.py
git commit -m "test(arch): curated-drift guard (skips until baseline committed)"
```

---

## Task 21: Makefile targets

**Files:**
- Modify: `Makefile` (existing)

Add `arch-regen` and `arch-serve` targets. `arch-serve` is a placeholder for Plan C (it will invoke `mkdocs serve` once MkDocs is configured); for Plan A it just prints an explanatory message.

- [ ] **Step 1: Inspect existing Makefile structure**

```bash
head -50 Makefile
```

Note the indentation style (tabs vs spaces) and any `.PHONY` declarations.

- [ ] **Step 2: Add the targets**

Append (or insert in the appropriate section) to `Makefile`:

```makefile
.PHONY: arch-regen arch-serve arch-check

## arch-regen — regenerate docs/arch/generated/ from source
arch-regen:
	python -m src.arch.runner --emit --repo-root .

## arch-check — dry-run regen; fail if generated/ is stale
arch-check:
	python -m src.arch.runner --check --repo-root .

## arch-serve — serve the docs site locally (requires mkdocs; lands in Plan C)
arch-serve:
	@if command -v mkdocs >/dev/null 2>&1 && [ -f mkdocs.yml ]; then \
	    mkdocs serve --strict; \
	else \
	    echo "mkdocs not configured yet — Plan C wires this up. For now, run 'make arch-regen' and read docs/arch/generated/*.md directly."; \
	fi
```

- [ ] **Step 3: Verify the targets**

```bash
make arch-regen
make arch-check
make arch-serve
```

Expected: `arch-regen` writes 8 files; `arch-check` exits 0; `arch-serve` prints the placeholder message.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "build(arch): make arch-regen / arch-check / arch-serve targets"
```

---

## Task 22: Initial emit + commit baseline

**Files:**
- Create (via emit): `docs/arch/generated/*.md` (8 files), `docs/arch/.meta.json`
- Modify: `.gitignore` (if needed — `docs/arch/` should NOT be ignored)

The runner now exists and tests pass. Run it once, inspect the output, commit the baseline so the curated-drift test passes from now on.

- [ ] **Step 1: Verify `docs/arch/` is not gitignored**

```bash
git check-ignore -v docs/arch/generated/loops.md 2>&1 || echo "not ignored — good"
```

If `docs/arch/` is ignored, add a positive override to `.gitignore`:

```
# .gitignore additions if needed
!docs/arch/
```

- [ ] **Step 2: Run the runner**

```bash
make arch-regen
```

- [ ] **Step 3: Inspect each generated file**

```bash
for f in docs/arch/generated/*.md; do echo "=== $f ==="; head -30 "$f"; echo; done
```

Sanity-check that:
- Each file has the `<!-- generated by ... -->` comment
- Each file ends with the `_Regenerated from commit..._` footer
- `loops.md` lists ~25-30 loops (not 5; not zero)
- `ports.md` lists at least 7 ports
- `labels.md` either has a Mermaid `stateDiagram-v2` block OR is empty (in which case Task 3's extractor needs another iteration — see Task 18)
- `mockworld.md` lists ~13 fakes

- [ ] **Step 4: If `labels.md` is empty, iterate on Task 3's extractor (bounded)**

Inspect the actual transition declaration in `src/`:

```bash
grep -rn "TRANSITION\|relabel\|hydraflow-implementing" src/ | head -20
```

Extend `src/arch/extractors/labels.py` to handle the form found (literal list, dict, dataclass enum, `match`/`case` over labels, etc.). Re-run `make arch-regen` until `labels.md` has content. Re-run the test:

```bash
pytest tests/architecture/test_label_state_matches_adr0002.py -v
```

Iterate until either:

- **(a)** the test passes (extractor works and ADR-0002 matches code), or
- **(b)** the only remaining failure is "missing/extra transitions" (real architectural drift, not an extractor bug — file an issue and amend ADR-0002 in a follow-up; do not block Plan A on it).

**Escape hatch.** If after **two iteration attempts** the canonical transition form turns out to be something the AST cannot statically analyze (e.g., transitions computed at runtime from external config, dispatch through a state-machine library), do this and move on — Plan A is not blocked:

1. Leave `labels.md` with the empty-state output (`_(no transitions discovered)_`).
2. Mark `tests/architecture/test_label_state_matches_adr0002.py` with `@pytest.mark.xfail(strict=False, reason="canonical transition form is not statically analyzable; see Task 3 notes and hydraflow-find issue #N")`.
3. Open a `hydraflow-find` issue describing the form encountered, the failed approaches, and a proposal (e.g., "introduce a declarative transition table at `src/labels_machine.py`").
4. Note the xfail in Plan B's out-of-scope section so it's revisited (the same way Task 19 is).

- [ ] **Step 5: Run the full test suite to confirm green**

```bash
pytest tests/architecture/ -v
```

Expected: all `test_extractor_*` and `test_generator_*` and `test_runner` tests pass; `test_arch_freshness` passes; `test_curated_drift` passes (now that baseline is on disk); `test_label_state_matches_adr0002` passes (after Task 22 step 4 iteration); `test_loop_count_matches_adr0001` shows XFAIL.

- [ ] **Step 6: Run `make quality`**

```bash
make quality
```

Expected: green. If it fails, fix the underlying issue (per CLAUDE.md: never `--no-verify`).

- [ ] **Step 7: Commit the baseline**

```bash
git add docs/arch/generated/ docs/arch/.meta.json
git commit -m "feat(arch): initial baseline emit of docs/arch/generated/"
```

- [ ] **Step 8: Open the PR**

```bash
git push -u origin arch-knowledge-system
gh pr create --title "feat(arch): Plan A — runner foundation for architecture knowledge system" \
    --body "$(cat <<'EOF'
## Summary

Implements Plan A of the Architecture Knowledge System v1 spec
(`docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md`).

Ships:
- `src/arch/extractors/` — 7 pure AST/file-walk extractors (loops, ports, labels, modules, events, ADR-xref, MockWorld)
- `src/arch/generators/` — 8 pure markdown+Mermaid generators
- `src/arch/runner.py` — CLI with `--emit` and `--check` modes
- `src/arch/freshness.py` — badge-state computation
- 14 unit tests + drift test + ADR-0002 match test + ADR-0001 xfail-pending guard
- `make arch-regen` / `make arch-check` / `make arch-serve` targets
- Initial baseline of `docs/arch/generated/` committed

Out of scope (later plans):
- `functional_areas.py` generator + YAML — Plan B
- ADR-0001 amendment + .likec4 deletion — Plan B
- DiagramLoop (L24) + CI workflow + MkDocs Pages — Plan C

## Test plan

- [x] All `tests/architecture/test_extractor_*.py` pass
- [x] All `tests/architecture/test_generator_*.py` pass
- [x] `tests/architecture/test_runner.py` passes
- [x] `tests/architecture/test_arch_freshness.py` passes
- [x] `tests/architecture/test_curated_drift.py` passes (after baseline commit)
- [x] `tests/architecture/test_label_state_matches_adr0002.py` passes
- [x] `tests/architecture/test_loop_count_matches_adr0001.py` shows XFAIL
- [x] `make quality` is green
- [x] `python -m src.arch.runner --emit` writes 8 files + `.meta.json`
- [x] `python -m src.arch.runner --check` exits 0 immediately after `--emit`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist (run before declaring Plan A complete)

- [ ] Every task in the table at the top of this plan is checked off.
- [ ] No `TODO`, `FIXME`, or `# placeholder` comments in any new file.
- [ ] All extractor outputs are sorted (deterministic byte-stable Markdown).
- [ ] All generators emit the `<!-- generated by ... -->` header and `{{ARCH_FOOTER}}` sentinel.
- [ ] No new runtime dependencies (only stdlib + Pydantic which is already in deps).
- [ ] No imports of `BaseBackgroundLoop` (or any application module) anywhere in `src/arch/` — only AST parsing.
- [ ] `docs/arch/generated/` is committed and matches `make arch-check` output exactly.
- [ ] PR description references the spec section being implemented.
