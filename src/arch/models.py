from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class LayerMap:
    mapping: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.mapping:
            return
        types = {type(v) for v in self.mapping.values()}
        if len(types) != 1:
            raise TypeError(
                f"LayerMap values must be uniform type; got {sorted(t.__name__ for t in types)}"
            )
        if not all(t in (int, str) for t in types):
            raise TypeError("LayerMap values must be int or str")

    @property
    def values_set(self) -> set[Any]:
        return set(self.mapping.values())


@dataclass(frozen=True)
class Allowlist:
    mapping: dict[str, set[str]]

    def allowed(self, source: str, target: str) -> bool:
        return target in self.mapping.get(source, set())


FitnessKind = Literal[
    "max_lines", "max_fan_in", "max_fan_out", "forbidden_symbol", "naming_pattern"
]


@dataclass(frozen=True)
class Fitness:
    kind: FitnessKind
    target: str
    value: Any = None
    pattern: str | None = None
    outside_layer: Any = None

    @classmethod
    def max_lines(cls, target: str, value: int) -> Fitness:
        return cls(kind="max_lines", target=target, value=value)

    @classmethod
    def max_fan_in(cls, target: str, value: int) -> Fitness:
        return cls(kind="max_fan_in", target=target, value=value)

    @classmethod
    def max_fan_out(cls, target: str, value: int) -> Fitness:
        return cls(kind="max_fan_out", target=target, value=value)

    @classmethod
    def forbidden_symbol(
        cls, pattern: str, *, outside_layer: Any = None, target: str = "**/*"
    ) -> Fitness:
        return cls(
            kind="forbidden_symbol",
            target=target,
            pattern=pattern,
            outside_layer=outside_layer,
        )

    @classmethod
    def naming_pattern(cls, target: str, pattern: str) -> Fitness:
        return cls(kind="naming_pattern", target=target, pattern=pattern)

    def validate_against(self, layers: LayerMap) -> None:
        if (
            self.outside_layer is not None
            and self.outside_layer not in layers.values_set
        ):
            raise ValueError(
                f"outside_layer={self.outside_layer} not present in LayerMap values "
                f"{sorted(layers.values_set)}"
            )


ModuleUnit = Literal["file", "directory"]


@dataclass
class ImportGraph:
    module_unit: ModuleUnit
    edges: set[tuple[str, str]] = field(default_factory=set)
    nodes: set[str] = field(default_factory=set)

    def add_edge(self, source: str, target: str) -> None:
        self.edges.add((source, target))
        self.nodes.update([source, target])


@dataclass(frozen=True)
class Violation:
    source: str
    target: str
    rule: str
    detail: str


@dataclass(frozen=True)
class AdrSummary:
    slug: str
    number: str
    title: str
    one_line: str


@dataclass
class RuleModule:
    extractor: Callable[[str], ImportGraph]
    layers: LayerMap
    allowlist: Allowlist
    fitness: list[Fitness]
