"""Citation extraction + AST verification + fuzzy suggestion for
:mod:`wiki_rot_detector_loop` (spec §4.9).

Three extraction patterns, one AST verifier, one grep fallback, one
fuzzy matcher. Each function is side-effect-free and unit-testable in
isolation — the loop composes them per cite.
"""

from __future__ import annotations

import ast
import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hydraflow.wiki_rot_citations")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Style-A: ``path/to/module.py:symbol`` — the HydraFlow house style.
_STYLE_A_RE = re.compile(r"\b([\w./-]+\.py):(\w+)")

# Style-B: ``src.module.Class`` — dotted Python import path anchored to
# the ``src`` root. Anchoring to ``src`` prevents false positives on
# ordinary dotted prose (``big.bad.wolf``). The final segment is the
# symbol; everything before is the module dotted path.
_STYLE_B_RE = re.compile(r"\b(src(?:\.\w+)+)\b")

# Style-C: bare identifiers within ``` ```python ``` ``` fences that look
# like cites (def / class / call sites). Hints only — ambiguous without
# context.
_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:(]", re.MULTILINE)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True)
class Cite:
    """A single cite candidate extracted from a wiki entry.

    ``module`` is either a slashed file path (Style-A) or a dotted Python
    path (Style-B / C).  ``style`` indicates which extractor produced it.
    ``raw`` is the verbatim substring for display in issue bodies.
    """

    module: str
    symbol: str
    style: str  # "colon" | "dotted" | "fenced_hint"
    raw: str

    def module_as_path(self) -> str:
        """Return ``module`` normalised to a slashed ``.py`` path.

        Style-A is already slashed; Style-B is dotted (``src.foo.bar``
        → ``src/foo/bar.py``); Style-C (fence hint) has no module path
        and returns an empty string — callers must skip AST verification
        for hints.
        """
        if self.style == "colon":
            return self.module
        if self.style == "dotted":
            return self.module.replace(".", "/") + ".py"
        return ""


def extract_cites(text: str) -> list[Cite]:
    """Extract Style-A + Style-B hard cites from arbitrary markdown/prose.

    Deduplicated by ``(module, symbol, style)``.  Fenced-code hints
    (Style-C) are **excluded** — see :func:`extract_fenced_hints`.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Cite] = []

    for m in _STYLE_A_RE.finditer(text):
        key = (m.group(1), m.group(2), "colon")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Cite(module=m.group(1), symbol=m.group(2), style="colon", raw=m.group(0))
        )

    for m in _STYLE_B_RE.finditer(text):
        path = m.group(1)
        parts = path.split(".")
        if len(parts) < 2:
            continue
        module = ".".join(parts[:-1])
        symbol = parts[-1]
        # Only treat the last segment as a symbol if it starts with an
        # identifier char — some prose ends in ``src.foo.`` (trailing dot)
        # which the `\b` anchor does not catch.
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", symbol):
            continue
        key = (module, symbol, "dotted")
        if key in seen:
            continue
        seen.add(key)
        out.append(Cite(module=module, symbol=symbol, style="dotted", raw=path))

    return out


def extract_fenced_hints(text: str) -> list[Cite]:
    """Return Style-C fenced-code hints — bare symbol names inside
    ``` ```python ``` ``` fences.

    Emitted as :class:`Cite` with ``style="fenced_hint"`` and an empty
    ``module`` field.  Callers use these as contextual appendices only;
    they are not verified against the filesystem.
    """
    seen: set[str] = set()
    out: list[Cite] = []

    for fence in _FENCE_RE.finditer(text):
        body = fence.group(1)
        for rx in (_DEF_RE, _CLASS_RE, _CALL_RE):
            for sym_match in rx.finditer(body):
                name = sym_match.group(1)
                if name in seen or name in _BUILTINS_DENY:
                    continue
                seen.add(name)
                out.append(Cite(module="", symbol=name, style="fenced_hint", raw=name))

    return out


# Python builtins and common stdlib names that pollute fenced-hint
# extraction. Suppressed so the issue context doesn't list ``print``,
# ``len`` and friends as "hints".
_BUILTINS_DENY: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "range",
        "enumerate",
        "zip",
        "open",
        "isinstance",
        "type",
        "hasattr",
        "getattr",
        "setattr",
        "repr",
        "id",
        "map",
        "filter",
        "sorted",
        "reversed",
        "sum",
        "min",
        "max",
        "abs",
        "any",
        "all",
        "iter",
        "next",
        "self",
        "cls",
        "True",
        "False",
        "None",
    }
)


# ---------------------------------------------------------------------------
# AST verification
# ---------------------------------------------------------------------------


def verify_cite_ast(
    repo_root: Path, module_path: str, symbol: str
) -> tuple[bool, list[str]]:
    """Verify *symbol* exists in *module_path* via AST walk.

    Returns ``(ok, symbols)`` where ``symbols`` is the sorted list of
    defined `FunctionDef` / `AsyncFunctionDef` / `ClassDef` names
    (useful for fuzzy suggestions).  For ``__init__.py`` re-exports
    (``from .x import y``), the verifier opens the referenced module
    once and rescans — depth-1 only; deeper chains fall back to grep.

    Non-Python paths, missing files, and parse errors all return
    ``(False, [])`` — callers treat them as broken cites or route them
    to :func:`verify_cite_grep`.
    """
    if not module_path.endswith(".py"):
        return False, []

    module_file = repo_root / module_path
    if not module_file.is_file():
        return False, []

    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        logger.debug("AST parse failed for %s", module_file, exc_info=True)
        return False, []

    symbols = _collect_defined_symbols(tree)

    if symbol in symbols:
        return True, sorted(symbols)

    # Depth-1 re-export resolution: scan ``from .foo import bar`` lines.
    reexport_hits = _follow_reexports(tree, module_file, symbol)
    if reexport_hits:
        return True, sorted(symbols | reexport_hits)

    return False, sorted(symbols)


def _collect_defined_symbols(tree: ast.AST) -> set[str]:
    """Walk *tree* for top-level + nested defs and return symbol names."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(node.name)
    return out


def _follow_reexports(tree: ast.AST, module_file: Path, symbol: str) -> set[str]:
    """Resolve ``from .x import *`` / ``from .x import symbol`` one level.

    Returns the set of symbols defined in the *re-exported* module if
    that module defines *symbol*; otherwise an empty set.  Deeper chains
    are intentionally not followed — grep fallback covers those.
    """
    module_dir = module_file.parent
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None or node.level == 0:
            continue
        target_parts = node.module.split(".")
        target_file = module_dir.joinpath(*target_parts).with_suffix(".py")
        if not target_file.is_file():
            target_file = module_dir.joinpath(*target_parts, "__init__.py")
            if not target_file.is_file():
                continue
        try:
            sub_tree = ast.parse(target_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        sub_syms = _collect_defined_symbols(sub_tree)
        imported = {a.name for a in node.names}
        if symbol in sub_syms and (symbol in imported or "*" in imported):
            return sub_syms
    return set()


# ---------------------------------------------------------------------------
# Grep fallback (non-Python cites + managed-repo mirrors)
# ---------------------------------------------------------------------------


def verify_cite_grep(repo_root: Path, file_path: str, needle: str) -> bool:
    """Substring search fallback for ``.md`` / ``.json`` / managed-repo
    targets.  ``True`` iff *needle* appears in the file at
    ``repo_root / file_path``.  Missing file → ``False``.
    """
    target = repo_root / file_path
    if not target.is_file():
        return False
    try:
        return needle in target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Fuzzy suggestion
# ---------------------------------------------------------------------------


def fuzzy_suggest(symbol: str, candidates: list[str]) -> str | None:
    """Return the closest match to *symbol* from *candidates* or ``None``.

    Cutoff `0.6` — the `difflib` default — is loose enough to catch
    plausible typo/rename drift (``foo_bar`` → ``foo_baz``) without
    drowning operators in spurious suggestions.
    """
    matches = difflib.get_close_matches(symbol, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None
