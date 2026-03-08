from __future__ import annotations

import ast
from pathlib import Path


def test_except_blocks_chain_exceptions() -> None:
    """Ensure every raise inside an except block preserves the original cause."""
    offenders: list[str] = []
    for file_path in Path("src").rglob("*.py"):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Raise):
                    continue
                if child.exc is None:
                    # bare ``raise`` keeps original exception context
                    continue
                if child.cause is not None:
                    continue
                offenders.append(f"{file_path}:{child.lineno}")
    assert not offenders, (
        "Exceptions raised inside except blocks must use `raise ... from ...` "
        "(or `from None` when intentional). Missing chaining at:\n"
        + "\n".join(offenders)
    )
