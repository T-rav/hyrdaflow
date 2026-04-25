"""Extract LabelStateMachine from the canonical transition declaration.

Looks for a top-level constant of the form
    TRANSITIONS = [(from_state, to_state, trigger?), ...]
(or `_TRANSITIONS` / `LABEL_TRANSITIONS`). Walks src/*.py until one is found.

For codebases where transitions are scattered across imperative
`swap_pipeline_labels(...)` call-sites (HydraFlow as of v1) this returns an
empty state machine. That's intentional: the matching ADR-0002 drift test
is marked xfail in such cases per Plan A's escape hatch (Task 22 step 4),
and a hydraflow-find issue documents the gap so the cleanup can introduce
a declarative table later.
"""

from __future__ import annotations

import ast
from pathlib import Path

from arch._models import LabelStateMachine, LabelTransition

_RECOGNIZED_NAMES = {"TRANSITIONS", "_TRANSITIONS", "LABEL_TRANSITIONS"}


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
        if node.targets[0].id not in _RECOGNIZED_NAMES:
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for elt in node.value.elts:
            if not isinstance(elt, ast.Tuple):
                continue
            parts: list[str] = []
            for sub in elt.elts:
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    parts.append(sub.value)
                else:
                    break
            if len(parts) >= 2:
                out.append(
                    LabelTransition(
                        from_state=parts[0],
                        to_state=parts[1],
                        trigger=parts[2] if len(parts) > 2 else "",
                    )
                )
    return out


def extract_labels(src_dir: Path) -> LabelStateMachine:
    src_dir = Path(src_dir).resolve()
    transitions: list[LabelTransition] = []
    for py in sorted(src_dir.rglob("*.py")):
        try:
            text = py.read_text()
        except OSError:
            continue
        if not any(name in text for name in _RECOGNIZED_NAMES):
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
