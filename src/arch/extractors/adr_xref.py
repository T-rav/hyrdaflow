"""Parse ADRs for module:symbol and src/ path references.

Scans every numbered ADR file (e.g. `0001-foo.md`) for occurrences of
`src/<path>.py` or `src/<path>.py:<symbol>`, normalizes each to a dotted
module name (`src.<path>`), and emits a forward index `ADR-NNNN -> [modules]`.
The reverse `module -> [ADRs]` index is computed by the generator.
"""

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
