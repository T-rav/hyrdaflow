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
    module: str  # e.g. "mockworld.fakes.fake_github"
    source_path: str
    implements_port: str | None = None  # if discoverable
    used_in_scenarios: list[str] = Field(default_factory=list)


class MockWorldMap(BaseModel):
    fakes: list[FakeInfo] = Field(default_factory=list)


class CommitInfo(BaseModel):
    """One row in the architecture changelog."""

    sha: str
    iso_date: str  # YYYY-MM-DD
    subject: str
    pr_number: int | None = None  # parsed from "(#NNNN)" suffix if present
