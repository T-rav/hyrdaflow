"""Regression test ensuring the legacy visual_diff module stays removed."""

import importlib.util


def test_visual_diff_module_is_not_importable() -> None:
    """visual_diff module was removed; guard against re-introduction."""

    # find_spec("visual_diff") works because conftest.py adds src/ to sys.path
    spec = importlib.util.find_spec("visual_diff")
    assert spec is None, (
        "visual_diff module still exists; delete src/visual_diff.py and references."
    )
