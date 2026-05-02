#!/usr/bin/env python3
# Strip LLM-generated ceremony from test files.
#
# Three patterns are removed:
#   1. Standalone AAA ceremony comments — lines whose entire content is
#      "# Arrange", "# Act", "# Assert", "# Arrange / Act", "# Setup", etc.
#      Inline trailing comments are preserved.
#   2. Single-line "Should ..." docstrings on test functions. These
#      paraphrase the test name and carry no information.
#   3. Single-line "Tests for ..." / "Tests that ..." class docstrings on
#      Test* classes. The class name already says it.
#
# Multi-line docstrings are never touched (they likely explain WHY).
# Functions whose body would become empty are never modified.
#
# Usage:
#     python scripts/strip_test_sludge.py --dry-run    # report only
#     python scripts/strip_test_sludge.py --apply      # rewrite files
#     python scripts/strip_test_sludge.py --apply path/to/file.py ...

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

AAA_COMMENT_RE = re.compile(
    r"""^\s*\#\s*(
        arrange\s*/\s*act
        | arrange\s*and\s*act
        | arrange\s*&\s*act
        | act\s*/\s*assert
        | arrange
        | act
        | assert
        | set\s*up
        | setup
        | given
        | when
        | then
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

SHOULD_DOC_RE = re.compile(r"^\s*Should\b")
TESTS_FOR_DOC_RE = re.compile(r"^\s*(Tests?\s+(for|that|the)\b|Test(?:s)?\s+for\b)")


def _docstring_constant(stmt: ast.stmt) -> ast.Constant | None:
    if (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    ):
        return stmt.value
    return None


def _add_docstring_lines(const: ast.Constant, target: set[int]) -> None:
    end = const.end_lineno if const.end_lineno is not None else const.lineno
    for ln in range(const.lineno, end + 1):
        target.add(ln)


def _find_strip_lines(source: str, path: Path) -> tuple[set[int], dict[str, int]]:
    tree = ast.parse(source, str(path))
    lines_to_strip: set[int] = set()
    counts = {"should_doc": 0, "tests_for_doc": 0}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("test_") or len(node.body) <= 1:
                continue
            const = _docstring_constant(node.body[0])
            if const is None or const.lineno != const.end_lineno:
                continue
            text = const.value
            if isinstance(text, str) and SHOULD_DOC_RE.match(text):
                _add_docstring_lines(const, lines_to_strip)
                counts["should_doc"] += 1

        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("Test") or len(node.body) <= 1:
                continue
            const = _docstring_constant(node.body[0])
            if const is None or const.lineno != const.end_lineno:
                continue
            text = const.value
            if isinstance(text, str) and TESTS_FOR_DOC_RE.match(text):
                _add_docstring_lines(const, lines_to_strip)
                counts["tests_for_doc"] += 1

    return lines_to_strip, counts


def _strip_aaa_comments(lines: list[str]) -> int:
    count = 0
    for i, line in enumerate(lines):
        if AAA_COMMENT_RE.match(line):
            lines[i] = ""
            count += 1
    return count


def _collapse_blanks(lines: list[str]) -> None:
    """Collapse runs of 2+ blank lines down to a single blank line.

    Only touches blanks that resulted from our removals — runs that were
    already two-blanks-deep in the source pass through unchanged because
    the second blank still leaves a single blank between non-blank lines.
    """
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    lines[:] = out


def process_file(path: Path, *, apply: bool) -> dict[str, int]:
    source = path.read_text()
    try:
        strip_lines, counts = _find_strip_lines(source, path)
    except SyntaxError as exc:
        print(f"SYNTAX ERROR in {path}: {exc}", file=sys.stderr)
        return {"error": 1}

    lines = source.splitlines(keepends=True)
    for ln in strip_lines:
        lines[ln - 1] = ""

    aaa = _strip_aaa_comments(lines)
    counts["aaa_comment"] = aaa

    new_source = "".join(lines)
    if new_source == source:
        return counts

    new_lines = new_source.splitlines(keepends=True)
    _collapse_blanks(new_lines)
    final = "".join(new_lines)

    if apply and final != source:
        path.write_text(final)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite files in place")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any sludge is found (for pre-commit)",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files to process")
    args = parser.parse_args()

    modes = sum(bool(x) for x in (args.apply, args.dry_run, args.check))
    if modes != 1:
        parser.error("must pass exactly one of --apply, --dry-run, --check")

    files = list(args.paths) if args.paths else sorted(Path("tests").glob("test_*.py"))

    totals = {"should_doc": 0, "tests_for_doc": 0, "aaa_comment": 0, "files_changed": 0}
    for path in files:
        counts = process_file(path, apply=args.apply)
        if any(
            counts.get(k, 0) for k in ("should_doc", "tests_for_doc", "aaa_comment")
        ):
            totals["files_changed"] += 1
            for k in ("should_doc", "tests_for_doc", "aaa_comment"):
                totals[k] += counts.get(k, 0)
            print(
                f"{path}: should={counts.get('should_doc', 0)} "
                f"tests_for={counts.get('tests_for_doc', 0)} "
                f"aaa={counts.get('aaa_comment', 0)}"
            )

    if args.check and totals["files_changed"]:
        print(
            f"\nBLOCKED — found test sludge in {totals['files_changed']} file(s).\n"
            f"  {totals['should_doc']} narrating 'Should ...' docstrings\n"
            f"  {totals['tests_for_doc']} redundant 'Tests for ...' class docstrings\n"
            f"  {totals['aaa_comment']} ceremonial '# Arrange/Act/Assert' comments\n"
            f"\nFix with: python scripts/strip_test_sludge.py --apply <files>",
            file=sys.stderr,
        )
        return 1

    mode = {"apply": "changed", "dry_run": "would change", "check": "found sludge in"}[
        "apply" if args.apply else "dry_run" if args.dry_run else "check"
    ]
    print(
        f"\n{mode}: {totals['files_changed']} files | "
        f"{totals['should_doc']} 'Should' docstrings, "
        f"{totals['tests_for_doc']} 'Tests for' class docstrings, "
        f"{totals['aaa_comment']} AAA comments"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
