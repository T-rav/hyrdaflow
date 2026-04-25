"""CLI entry point for the architecture knowledge runner.

Two modes:
- ``--emit``: regenerate everything to ``docs/arch/generated/`` and update
  ``.meta.json``.
- ``--check``: regenerate to a tmpdir, diff against the committed
  ``docs/arch/generated/``, exit 1 if any artifact is stale.

Both modes share the same ``_compute_artifacts()`` core. The runner replaces
the ``{{ARCH_FOOTER}}`` sentinel with a per-artifact regen footer (commit
SHA + UTC timestamp) so the body of every emitted file is byte-stable up
to the timestamp line.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from arch._models import CommitInfo
from arch.extractors.adr_xref import extract_adr_refs
from arch.extractors.events import extract_event_topology
from arch.extractors.labels import extract_labels
from arch.extractors.loops import extract_loops
from arch.extractors.mockworld import extract_mockworld_map
from arch.extractors.modules import extract_module_graph
from arch.extractors.ports import extract_ports
from arch.generators.adr_cross_reference import render_adr_cross_reference
from arch.generators.changelog import render_changelog
from arch.generators.event_bus import render_event_bus
from arch.generators.label_state import render_label_state
from arch.generators.loop_registry import render_loop_registry
from arch.generators.mockworld_map import render_mockworld_map
from arch.generators.module_graph import render_module_graph
from arch.generators.port_map import render_port_map

_ARTIFACT_FILES = [
    "loops.md",
    "ports.md",
    "labels.md",
    "modules.md",
    "events.md",
    "adr_xref.md",
    "mockworld.md",
    "changelog.md",
]


def _run(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return res.stdout


def _commit_sha(repo_root: Path) -> str:
    sha = _run(["git", "rev-parse", "HEAD"], repo_root).strip()
    return sha or "unknown"


def _git_log_changelog(repo_root: Path) -> list[CommitInfo]:
    pathspecs = ["docs/arch/", "docs/adr/", "docs/wiki/", "src/arch/", "mkdocs.yml"]
    fmt = "%H%x09%cs%x09%s"
    raw = _run(
        [
            "git",
            "log",
            "--since=90.days.ago",
            f"--pretty=format:{fmt}",
            "--",
            *pathspecs,
        ],
        repo_root,
    )
    out: list[CommitInfo] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, iso_date, subject = parts
        pr_num: int | None = None
        if subject.endswith(")") and "(#" in subject:
            try:
                pr_num = int(subject.rsplit("(#", 1)[-1].rstrip(")"))
            except ValueError:
                pr_num = None
        out.append(
            CommitInfo(sha=sha, iso_date=iso_date, subject=subject, pr_number=pr_num)
        )
    return out


def _compute_artifacts(repo_root: Path) -> dict[str, str]:
    """Run all extractors and generators; return {filename: markdown}."""
    src_dir = repo_root / "src"
    fakes_dir = repo_root / "tests/scenarios/fakes"
    scenarios_dir = repo_root / "tests/scenarios"
    adr_dir = repo_root / "docs/adr"

    return {
        "loops.md": render_loop_registry(extract_loops(src_dir)),
        "ports.md": render_port_map(
            extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)
        ),
        "labels.md": render_label_state(extract_labels(src_dir)),
        "modules.md": render_module_graph(extract_module_graph(src_dir)),
        "events.md": render_event_bus(extract_event_topology(src_dir)),
        "adr_xref.md": render_adr_cross_reference(extract_adr_refs(adr_dir)),
        "mockworld.md": render_mockworld_map(
            extract_mockworld_map(fakes_dir=fakes_dir, scenarios_dir=scenarios_dir)
        ),
        "changelog.md": render_changelog(_git_log_changelog(repo_root)),
    }


def _stamp_footer(body: str, sha: str, source_sha: str) -> str:
    """Replace the {{ARCH_FOOTER}} sentinel with a per-page regen footer.

    The footer is rendered visible italic text (not an HTML comment) so MkDocs
    Material surfaces it to readers. Plan C extends it with the freshness badge.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    footer = (
        f"_Regenerated from commit `{sha[:7]}` on {now}. "
        f"Source last changed at `{source_sha[:7]}`._"
    )
    return body.replace("{{ARCH_FOOTER}}", footer)


def emit(*, repo_root: Path, out_dir: Path) -> None:
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = _commit_sha(repo_root)
    artifacts = _compute_artifacts(repo_root)
    for name, body in artifacts.items():
        # Per-artifact source SHA equals overall HEAD in v1; refined per-artifact
        # in Plan C if needed.
        stamped = _stamp_footer(body, sha=sha, source_sha=sha)
        (out_dir / name).write_text(stamped)

    meta = {
        "regenerated_at": datetime.now(UTC).isoformat(),
        "commit_sha": sha,
        "artifacts": {n: {"source_sha": sha} for n in artifacts},
    }
    (out_dir.parent / ".meta.json").write_text(json.dumps(meta, indent=2))


def _strip_footer(text: str) -> str:
    """Remove the trailing `_Regenerated from commit..._` line for diff purposes.

    The line is italicized markdown — `_Regenerated from commit ..._` — and may
    be preceded by leading whitespace from the `_FOOTER` joining. Match
    anywhere on the line, not just the start, so any future leading-character
    tweak doesn't silently break the strip.
    """
    lines = text.splitlines()
    out = [line for line in lines if "_Regenerated from commit" not in line]
    return "\n".join(out)


# Artifacts inherently dependent on git history; not subject to drift checks
# (they regenerate freshly every CI/site build by design).
_DRIFT_EXEMPT = {"changelog.md"}


def check(*, repo_root: Path, generated_dir: Path) -> int:
    """Regenerate to a tmpdir, diff against `generated_dir`, return rc 0/1.

    `changelog.md` is exempt from drift detection: it derives from
    `git log` and changes with every commit, so structural drift detection
    is meaningless for it.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "generated"
        emit(repo_root=repo_root, out_dir=tmp)
        for name in _ARTIFACT_FILES:
            if name in _DRIFT_EXEMPT:
                continue
            actual = generated_dir / name
            expected = tmp / name
            if not actual.exists():
                print(f"[arch-check] missing: {name}")
                return 1
            # Compare body sans footer (footer has timestamps that change every run)
            a = _strip_footer(actual.read_text())
            b = _strip_footer(expected.read_text())
            if a != b:
                print(f"[arch-check] drift in {name}")
                # Show a unified-diff snippet so CI logs reveal exactly what differs
                import difflib

                diff_lines = list(
                    difflib.unified_diff(
                        a.splitlines(keepends=False),
                        b.splitlines(keepends=False),
                        fromfile=f"committed/{name}",
                        tofile=f"regenerated/{name}",
                        lineterm="",
                        n=3,
                    )
                )
                # Cap to first 80 diff lines to avoid log floods
                for line in diff_lines[:80]:
                    print(line)
                if len(diff_lines) > 80:
                    print(f"... ({len(diff_lines) - 80} more diff lines truncated)")
                return 1
    return 0


def _main() -> int:
    p = argparse.ArgumentParser(
        prog="arch.runner",
        description="Regenerate architecture knowledge artifacts.",
    )
    p.add_argument("--emit", action="store_true", help="Write to docs/arch/generated/.")
    p.add_argument(
        "--check",
        action="store_true",
        help="Dry-run; exit 1 if generated/ is stale relative to source.",
    )
    p.add_argument("--repo-root", default=".", type=Path)
    args = p.parse_args()

    repo_root = args.repo_root.resolve()
    generated = repo_root / "docs/arch/generated"
    if args.emit:
        emit(repo_root=repo_root, out_dir=generated)
        return 0
    if args.check:
        return check(repo_root=repo_root, generated_dir=generated)
    p.error("specify --emit or --check")
    return 2


if __name__ == "__main__":
    sys.exit(_main())
