"""Regression: one malformed mirror entry must not crash MemoryBacklogLoop.

Observed in production (server.log 2026-05-13): a backtick-leading frontmatter
value in ``docs/wiki/memory-feedback/feedback-make-quality-pipe-exit-code.md``
raised ``yaml.scanner.ScannerError`` from ``yaml.safe_load`` inside
``load_mirror_entry``. ``pending_entries`` only caught ``ValueError``, so the
YAMLError escaped and ``MemoryBacklogLoop._do_work`` failed every cycle —
the loop logged "iteration failed — will retry next cycle" and processed
zero entries until restart.

The contract: a single bad on-disk entry is data corruption, not a loop bug.
``pending_entries`` must skip the bad file and process the rest.
"""

from __future__ import annotations

from pathlib import Path

from memory_backlog_mirror import load_mirror_entry, pending_entries


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def test_pending_entries_skips_yaml_scanner_error(tmp_path: Path) -> None:
    """A backtick-leading value (YAML 1.1 reserved indicator) must not crash."""
    bad = tmp_path / "bad.md"
    _write(
        bad,
        "---\n"
        "source: x.md\n"
        "name: bad\n"
        "description: `backtick-leading` is a reserved YAML indicator\n"
        "status: pending\n"
        "---\n\nbody\n",
    )
    good = tmp_path / "good.md"
    _write(
        good,
        "---\n"
        "source: y.md\n"
        "name: good\n"
        "description: plain text\n"
        "status: pending\n"
        "---\n\nbody\n",
    )

    entries = pending_entries(tmp_path)

    slugs = {e.slug for e in entries}
    assert "good" in slugs, "the well-formed entry must still be returned"
    assert "bad" not in slugs, "the malformed entry must be skipped, not raised"


def test_load_mirror_entry_raises_value_error_on_yaml_error(tmp_path: Path) -> None:
    """load_mirror_entry must surface YAML parse failures as ValueError so
    callers can use a single exception type for "this file is unparseable"."""
    bad = tmp_path / "bad.md"
    _write(
        bad,
        "---\ndescription: `reserved indicator`\nstatus: pending\n---\n\nbody\n",
    )
    try:
        load_mirror_entry(bad)
    except ValueError:
        return  # expected
    except Exception as exc:  # noqa: BLE001 — test asserts only ValueError reaches caller
        msg = f"expected ValueError, got {type(exc).__name__}: {exc}"
        raise AssertionError(msg) from exc
    msg = "expected ValueError for malformed YAML, got no exception"
    raise AssertionError(msg)
