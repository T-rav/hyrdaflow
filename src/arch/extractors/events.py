"""Extract EventBus publish/subscribe topology from src/.

Walks src/*.py looking for any `<expr>.publish(EventType.X, ...)` or
`<expr>.subscribe(EventType.X, ...)` call. The enclosing function (or
class.function) becomes the qualified publisher/subscriber id, like
`src.widget_loop:WidgetLoop.on_open`.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from arch._models import EventBusTopology, EventEdge


def _module_dotted(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)
    return ".".join(rel.with_suffix("").parts)


def _event_names_in(args: list[ast.expr]) -> list[str]:
    """Walk each arg subtree for any `EventType.X` attribute access.

    Handles both direct (`bus.publish(EventType.X, ...)`) and wrapped
    (`bus.publish(HydraFlowEvent(type=EventType.X, ...))`) call shapes.
    """
    names: list[str] = []
    for arg in args:
        for sub in ast.walk(arg):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "EventType"
            ):
                names.append(sub.attr)
    return names


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.publishers: dict[str, list[str]] = defaultdict(list)
        self.subscribers: dict[str, list[str]] = defaultdict(list)
        self._fn_stack: list[str] = []

    def _qualified(self) -> str:
        if not self._fn_stack:
            return self.module
        return f"{self.module}:{'.'.join(self._fn_stack)}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "publish",
            "subscribe",
        }:
            bucket = (
                self.publishers if node.func.attr == "publish" else self.subscribers
            )
            for ev in _event_names_in(node.args):
                bucket[ev].append(self._qualified())
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
    return EventBusTopology(
        events=[
            EventEdge(
                event=e,
                publishers=sorted(pubs[e]),
                subscribers=sorted(subs[e]),
            )
            for e in events
        ]
    )
