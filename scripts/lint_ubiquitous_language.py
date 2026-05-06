"""CLI entry point for UL lint + view regeneration.

Exit code 0 = clean. Exit code 1 = anchor resolution failed (hard).
Paraphrase and reverse-coverage warnings print to stdout but do not fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ubiquitous_language import (  # noqa: E402
    TermStore,
    lint_anchor_resolution,
    lint_paraphrases,
    lint_reverse_coverage,
    render_context_map,
    render_glossary,
)

ROOT = Path(__file__).parent.parent
TERMS = ROOT / "docs" / "wiki" / "terms"
SRC = ROOT / "src"
WIKI = ROOT / "docs" / "wiki"
OUT = ROOT / "docs" / "arch" / "generated"


def main() -> int:
    terms = TermStore(TERMS).list()
    if not terms:
        print("UL: no terms found in docs/wiki/terms/ — skipping")
        return 0

    unresolved = lint_anchor_resolution(terms, SRC)
    paraphrases = lint_paraphrases(terms, WIKI)
    uncovered = lint_reverse_coverage(terms, SRC)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ubiquitous-language.md").write_text(render_glossary(terms))
    (OUT / "ubiquitous-language-context-map.md").write_text(render_context_map(terms))

    print(
        f"UL: {len(terms)} terms, "
        f"{len(unresolved)} unresolved anchors, "
        f"{len(paraphrases)} paraphrase warnings, "
        f"{len(uncovered)} uncovered load-bearing symbols"
    )

    if unresolved:
        print("UNRESOLVED ANCHORS (hard fail):")
        for u in unresolved:
            print(f"  {u}")
        return 1
    if paraphrases:
        print("PARAPHRASE WARNINGS:")
        for p in paraphrases[:10]:
            print(f"  {p}")
        if len(paraphrases) > 10:
            print(f"  ... and {len(paraphrases) - 10} more")
    if uncovered:
        print("UNCOVERED LOAD-BEARING SYMBOLS:")
        for u in uncovered[:10]:
            print(f"  {u}")
        if len(uncovered) > 10:
            print(f"  ... and {len(uncovered) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
