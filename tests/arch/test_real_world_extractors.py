"""Integration tests: tree_sitter_extractor against vendored real-world snapshots.

Each test case runs the extractor for one language against a small (~20 file,
<50 KB) vendored fixture and checks:

  1. No crash — extractor returns without raising.
  2. Non-zero graph — at least ``min_nodes`` nodes are produced.
  3. Expected edges — every edge in ``expected_edges`` appears in the graph.
  4. No forbidden edges — edges pointing at LICENSE/README/non-source files are
     absent.

See ``tests/arch/fixtures/real_world/ATTRIBUTION.md`` for repo provenance,
commit SHAs, and per-language extractor findings/limitations.

Known limitations surfaced by these tests (do NOT fix here; follow-up issues):
- Python: relative imports produce zero edges (extractor captures full statement
  text; ``_resolve_relative`` never fires on ``"from .foo import bar"``).
- Go: single-package repos map all files to one directory node; stdlib-only
  imports leave zero edges.
- Java: scoped-identifier resolution extracts first package segment (``"com"``)
  rather than class name; zero edges result.
- Rust: ``mod foo;`` is a ``mod_item`` not a ``use_declaration``; the module-
  declaration relationship is invisible to the current query.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arch.tree_sitter import tree_sitter_extractor

REAL_WORLD = Path(__file__).parent / "fixtures" / "real_world"

# ---------------------------------------------------------------------------
# Per-language test data
# ---------------------------------------------------------------------------
# (language, fixture_subdir, min_nodes, expected_edges, forbidden_edges)
#
# expected_edges: edges we KNOW must appear from reading the vendored source.
# forbidden_edges: edges that would indicate false positives (e.g., a source
#   file "importing" a LICENSE or README).
#
# Languages where the extractor produces zero edges (Python, Go, Java, Rust)
# use expected_edges=set() because asserting absent edges would make the test
# always fail. The limitations are documented in ATTRIBUTION.md.

CASES: list[tuple[str, str, int, set[tuple[str, str]], set[tuple[str, str]]]] = [
    # --- Python: python-dotenv ---
    # Extractor limitation: full `from .main import foo` text never resolves.
    # Zero edges are expected; we only assert node count and absence of noise.
    (
        "python",
        "python",
        4,
        set(),  # see module docstring for known limitation
        {
            ("src/dotenv/__init__.py", "LICENSE"),
            ("src/dotenv/main.py", "LICENSE"),
        },
    ),
    # --- TypeScript: neverthrow ---
    # Relative imports like `import { ... } from './result'` resolve correctly.
    (
        "typescript",
        "typescript",
        5,
        {
            ("src/result.ts", "src/_internals/error.ts"),
            ("src/result-async.ts", "src/result.ts"),
        },
        {
            ("src/index.ts", "LICENSE"),
            ("src/result.ts", "LICENSE"),
        },
    ),
    # --- JavaScript: execa lib/arguments subset ---
    # ESM `import` statements with relative paths resolve correctly.
    (
        "javascript",
        "javascript",
        9,
        {
            ("lib/arguments/options.js", "lib/arguments/cwd.js"),
            ("lib/arguments/command.js", "lib/arguments/escape.js"),
        },
        {
            ("lib/arguments/options.js", "LICENSE"),
            ("lib/arguments/command.js", "LICENSE"),
        },
    ),
    # --- Go: go-multierror ---
    # Single-package repo; all files collapse to directory node ".".
    # All imports are stdlib; zero internal edges are expected.
    (
        "go",
        "go",
        1,
        set(),  # see module docstring for known limitation
        {
            (".", "LICENSE"),
            (".", "go.mod"),
        },
    ),
    # --- Java: synthesized 3-class example ---
    # Extractor limitation: scoped identifier resolves to first package segment.
    # Zero edges are expected.
    (
        "java",
        "java",
        3,
        set(),  # see module docstring for known limitation
        {
            (
                "src/main/java/com/example/result/Result.java",
                "LICENSE",
            ),
        },
    ),
    # --- Rust: itoa ---
    # `mod u128_ext;` is a mod_item, not a use_declaration; zero edges expected.
    (
        "rust",
        "rust",
        2,
        set(),  # see module docstring for known limitation
        {
            ("src/lib.rs", "LICENSE"),
            ("src/lib.rs", "Cargo.toml"),
        },
    ),
    # --- Ruby: rake lib subset ---
    # `require_relative` calls resolve via stem lookup.
    (
        "ruby",
        "ruby",
        6,
        {
            ("lib/rake/task.rb", "lib/rake/invocation_exception_mixin.rb"),
            ("lib/rake.rb", "lib/rake/version.rb"),
        },
        {
            ("lib/rake.rb", "LICENSE"),
            ("lib/rake/version.rb", "LICENSE"),
        },
    ),
]


@pytest.mark.parametrize(
    "lang,subdir,min_nodes,expected,forbidden",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_real_world_extractor_smoke(
    lang: str,
    subdir: str,
    min_nodes: int,
    expected: set[tuple[str, str]],
    forbidden: set[tuple[str, str]],
) -> None:
    """Extractor returns a plausible graph for a vendored real-world snapshot."""
    fixture_dir = REAL_WORLD / subdir
    assert fixture_dir.is_dir(), f"fixture dir missing: {fixture_dir}"

    extract = tree_sitter_extractor(lang)
    graph = extract(str(fixture_dir))

    # 1. Non-zero graph
    assert len(graph.nodes) >= min_nodes, (
        f"{lang}: expected >= {min_nodes} nodes, got {len(graph.nodes)}: {sorted(graph.nodes)}"
    )

    # 2. At least the expected edges are present
    missing = expected - graph.edges
    assert not missing, (
        f"{lang}: missing expected edges: {missing}\n"
        f"  actual edges: {sorted(graph.edges)}"
    )

    # 3. No forbidden edges
    bad = forbidden & graph.edges
    assert not bad, (
        f"{lang}: forbidden edges present: {bad}\n"
        f"  full edge set: {sorted(graph.edges)}"
    )
