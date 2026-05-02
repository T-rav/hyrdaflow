# One-shot cleanup pass over docs/wiki/ to repair LLM-generated content
# bloat that accumulated before the title-derivation fix in this PR.
#
# Operations performed:
#   1. Delete opaque "Review patterns from #N" entries (no semantic title)
#   2. Delete generic catch-all heading entries leaked from runbook ingest
#   3. Delete numbered runbook-step entries (live in deploy/ec2/README.md)
#   4. Retitle 3 vague-but-salvageable entries
#   5. Split architecture.md (170 entries) into 6 sub-topic files
#   6. Rebuild docs/wiki/index.json + docs/wiki/index.md
#
# Idempotent: safe to re-run; missing titles are warnings, not errors.

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("wiki_cleanup")
logging.basicConfig(level=logging.INFO, format="%(message)s")

WIKI_DIR = Path("docs/wiki")

# ---------------------------------------------------------------------------
# Parsed entry representation
# ---------------------------------------------------------------------------


@dataclass
class WikiEntry:
    title: str
    prose: str  # body between heading and json:entry block
    json_block: str  # raw text of the ```json:entry ... ``` block (or "")
    trailing: str = ""  # any content between this entry and the next heading


def _parse_topic_file(path: Path) -> tuple[str, list[WikiEntry]]:
    """Split a topic file into (preamble, [entries...]).

    Each entry is bounded by a top-level ``## `` heading and runs until
    the next ``## `` or end-of-file. The ``json:entry`` block (if any) is
    captured verbatim.
    """
    text = path.read_text()
    chunks = re.split(r"^(## .+)$", text, flags=re.MULTILINE)
    # chunks[0] = preamble (anything before first heading)
    # chunks[1::2] = headings; chunks[2::2] = bodies
    preamble = chunks[0]
    entries: list[WikiEntry] = []
    for heading, body in zip(chunks[1::2], chunks[2::2], strict=True):
        title = heading[3:].strip()
        json_match = re.search(
            r"```json:entry\n(.*?)\n```",
            body,
            flags=re.DOTALL,
        )
        if json_match:
            prose = body[: json_match.start()].rstrip("\n")
            json_block = body[json_match.start() : json_match.end()]
            trailing = body[json_match.end() :]
        else:
            prose = body.rstrip("\n")
            json_block = ""
            trailing = ""
        entries.append(
            WikiEntry(
                title=title,
                prose=prose,
                json_block=json_block,
                trailing=trailing,
            )
        )
    return preamble, entries


def _render_topic_file(preamble: str, entries: list[WikiEntry]) -> str:
    out: list[str] = [preamble.rstrip("\n")]
    for entry in entries:
        out.append("")
        out.append(f"## {entry.title}")
        out.append(entry.prose.rstrip())
        if entry.json_block:
            out.append("")
            out.append(entry.json_block)
        if entry.trailing.strip():
            out.append(entry.trailing.rstrip())
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Cleanup operations
# ---------------------------------------------------------------------------


@dataclass
class CleanupReport:
    deleted: list[tuple[str, str]] = field(default_factory=list)  # (file, title)
    retitled: list[tuple[str, str, str]] = field(default_factory=list)
    moved: list[tuple[str, str, str]] = field(default_factory=list)
    not_found: list[tuple[str, str]] = field(default_factory=list)
    files_written: list[Path] = field(default_factory=list)


def _delete_titles(
    path: Path, titles: set[str], report: CleanupReport
) -> list[WikiEntry]:
    if not path.exists():
        return []
    preamble, entries = _parse_topic_file(path)
    kept: list[WikiEntry] = []
    for entry in entries:
        if entry.title in titles:
            report.deleted.append((path.name, entry.title))
        else:
            kept.append(entry)
    found = {e.title for e in entries}
    for missing in titles - found:
        report.not_found.append((path.name, missing))
    path.write_text(_render_topic_file(preamble, kept))
    report.files_written.append(path)
    return kept


def _retitle_entries(
    path: Path, mapping: dict[str, str], report: CleanupReport
) -> None:
    if not path.exists() or not mapping:
        return
    preamble, entries = _parse_topic_file(path)
    for entry in entries:
        if entry.title in mapping:
            new_title = mapping[entry.title]
            report.retitled.append((path.name, entry.title, new_title))
            entry.title = new_title
    path.write_text(_render_topic_file(preamble, entries))
    report.files_written.append(path)


def _split_topic_into_subfiles(
    source: Path,
    mapping: dict[str, list[str]],
    report: CleanupReport,
) -> None:
    if not source.exists():
        return
    preamble, entries = _parse_topic_file(source)
    by_title = {e.title: e for e in entries}
    for sub_filename, titles in mapping.items():
        sub_path = source.parent / sub_filename
        sub_entries = [by_title[t] for t in titles if t in by_title]
        if not sub_entries:
            continue
        sub_preamble = (
            f"# {sub_filename.replace('.md', '').replace('-', ' ').title()}\n"
        )
        sub_path.write_text(_render_topic_file(sub_preamble, sub_entries))
        report.files_written.append(sub_path)
        for entry in sub_entries:
            report.moved.append((source.name, sub_filename, entry.title))
    placed = {t for ts in mapping.values() for t in ts}
    leftover = [e for e in entries if e.title not in placed]
    source.write_text(_render_topic_file(preamble, leftover))
    report.files_written.append(source)


def _rebuild_index(report: CleanupReport) -> None:
    if not WIKI_DIR.exists():
        return
    topics: dict[str, list[str]] = {}
    total = 0
    for md_file in sorted(WIKI_DIR.glob("*.md")):
        if md_file.stem == "index":
            continue
        _, entries = _parse_topic_file(md_file)
        if entries:
            topics[md_file.stem] = [e.title for e in entries]
            total += len(entries)

    index_data = {
        "repo_slug": "T-rav/hydraflow",
        "topics": topics,
        "total_entries": total,
        "last_updated": datetime.now(UTC).isoformat(),
        "last_lint": None,
    }
    (WIKI_DIR / "index.json").write_text(json.dumps(index_data, indent=2))
    report.files_written.append(WIKI_DIR / "index.json")

    md_lines = [
        "# Wiki Index: T-rav/hydraflow\n",
        f"**{total} entries** | Last updated: {index_data['last_updated']}\n",
    ]
    for topic, titles in sorted(topics.items()):
        md_lines.append(
            f"\n## {topic.replace('-', ' ').replace('_', ' ').title()} ({len(titles)})\n"
        )
        for title in titles:
            md_lines.append(f"- {title}")
    (WIKI_DIR / "index.md").write_text("\n".join(md_lines) + "\n")
    report.files_written.append(WIKI_DIR / "index.md")


# ---------------------------------------------------------------------------
# Cleanup specification — what to delete, retitle, and split
# ---------------------------------------------------------------------------

REVIEW_PATTERN_TITLES = {
    f"Review patterns from #{n}"
    for n in (
        6311,
        6309,
        6310,
        6312,
        6313,
        6315,
        6314,
        6316,
        6318,
        6320,
        6294,
        6322,
        6297,
        6323,
        6328,
        6299,
        6327,
        6330,
        6300,
        6301,
        6331,
        6334,
    )
}

GENERIC_HEADER_TITLES_ARCH = {
    "Architecture",
    "Key Files",
    "Design rationale",
    "Sequence before committing",
    "Related",
    "Layout",
    "Style consistency",
    "Component patterns",
    "Worktrees and Branch Protection",
    "ADR Reference",
    "EC2 Deployment Guide",
}

RUNBOOK_TITLES_ARCH = {
    "1. Prerequisites",
    "2. Bootstrap the runtime",
    "4. Install the systemd unit",
    "6. Updates",
    "7. Troubleshooting checklist",
}

GENERIC_HEADER_TITLES_TESTING = {"Tech stack", "Tests", "Quality"}

GENERIC_HEADER_TITLES_GOTCHAS = {"Key files", "5. Health checks and monitoring"}

GENERIC_HEADER_TITLES_PATTERNS = {"UI", "3. Bind the dashboard to a public interface"}

RETITLE_MAPS: dict[str, dict[str, str]] = {
    "patterns.md": {"Run and dev": "Development and Local Testing Workflow"},
    "testing.md": {
        "Setup and scaffolding": "Test Environment Setup and Scaffolding",
        "Testing Is Mandatory": "Required Testing Coverage and Validation",
    },
}

# Architecture topic split — taxonomy from the wiki content audit (PR #8459 plan).
ARCHITECTURE_SPLIT: dict[str, list[str]] = {
    "architecture-layers.md": [
        "Layer Architecture: Four-Layer Model with Structural Typing",
        "Functional Design: Pure Functions and Module-Level Utilities",
        "Layer 1 assignment for pure data constants",
        "Layer checker must track newly added data modules",
        "Backward Compatibility and Refactoring via Facades and Re-Exports",
        "Facade Exception: Public Method Limits for Behavioral Classes",
        "Facade + Composition for Large Class Refactoring",
        "Acceptance Criteria: Distinguish Public Facades from Implementation",
        "Template method exception to 50-line logic limit",
        "Coordinator + focused helpers decomposition pattern",
        "Orchestrator pattern composes modules via deferred registration calls",
        "Avoid thin-wrapper abstractions—target concrete duplication",
        "Move generic utilities to module-level functions to keep classes small",
        "Use sibling file patterns as architectural reference for consistency",
        "Module-Level State via Constructor Injection",
        "Preserve organizational comments during dead code removal",
    ],
    "architecture-async-control.md": [
        "Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle",
        "Background Loops and Skill Infrastructure: Audit Patterns and Wiring",
        "Label-Based Async Loop Routing via GitHub Labels",
        "Idempotency Guards Prevent Redundant Side Effects",
        "Clarity Score Routing: Fast Path vs Multi-Stage Maturation",
        "Side Effect Consumption Pattern for Context Threading",
        "Callback Construction Order: State → Snapshot → Router → Tracker",
        "Use callbacks to decouple isolated components from orchestrator state",
        "Return Value Threading in Orchestrator Pattern",
        "Config tuples enable clean parameterized loops",
        "Polling loops must sleep when service disabled",
        "Context manager protocol for async resource pooling",
        "httpx.AsyncClient.aclose() is idempotent and safe",
        "Service composition root needs async cleanup method",
        "Sentry integration: ERROR+ only triggers alerts",
        "Fatal error hierarchy—propagate vs. suppress",
    ],
    "architecture-imports-types.md": [
        "Deferred Imports, Type Checking, and Testing",
        "Optional Dependencies: Graceful Degradation and Safe Handling",
        "TYPE_CHECKING guard pattern for type-only imports",
        "noqa: TCH004 required for TYPE_CHECKING imports",
        "TYPE_CHECKING prevents circular imports on cross-module TypedDicts",
        "Preserve deferred imports for optional dependencies",
        "Deferred Imports Must Remain Inside Helpers",
        "Deferred imports in helper methods avoid circular dependencies",
        "Deferred imports remain at usage sites with lint suppression",
        "Deferred imports preserve test mocking patterns",
        "Preserve lazy imports to avoid module-level coupling",
        "Logger names resolve to full module path from __name__",
        "Environment Override Validation via get_args() for Literal Types",
        "Distinguish similarly-named modules during cleanup",
        "Import-site patch targets must migrate with extracted functions",
        "Strict no-circular-import rule for extracted coordinators",
        "Restrict extracted component imports to prevent circular dependencies",
    ],
    "architecture-state-persistence.md": [
        "State Persistence: Atomic Writes and Backup Recovery",
        "In-Place Mutation Requirement for Shared Dicts",
        "Immutable Scalars in Shared State Pattern",
        "Feature Gates and Configuration-Driven Behavior",
        "Dataclass Design for Schema Evolution and Backward Compatibility",
        "Annotated[str, Validator] pattern for backward-compatible type narrowing",
        "Use Literal types for bounded enum-like fields",
        "Dict-to-Model Conversion Pattern for Type Safety",
        "Empty String Sentinel with Union Type Annotation",
        "StrEnum Fields Serialize Without Migration",
        "Naming conventions are pipeline-layer scoped",
        "f-string output decoupled from parameter naming",
        "FastAPI route registration order affects specificity matching",
        "Convert closure mutable state to class-based encapsulation",
        "Endpoint path preservation enables test reuse across refactors",
        "Pydantic Field() accepts module-level int constants safely",
        "Path prefix pattern for hierarchical object keys",
        "Accept typed enums, call .value internally",
        "Parametrized validation rejection tests follow annotated-type pattern",
    ],
    "architecture-refactoring.md": [
        "Consolidation Patterns for Duplicate Code",
        "Dead Code Removal Verification and Code Cleanup",
        "Dead-code removal: three-phase decomposition pattern",
        "Wire unconnected config parameters to existing consumers",
        "Visual consistency outweighs functional correctness",
        "Define explicit scope for extraction refactors",
        "Plan line numbers become stale; search by pattern instead",
        "Cross-cutting methods as callbacks, not new classes",
        "Regex-based test parsing creates hard constraints on source structure",
        "Grep-based verification validates dead code removal completeness",
        "Dead code removal verification via grep across codebase",
        "Audit __all__ exports when removing public functions",
        "Preserve module-specific guards when extracting duplicated logic",
        "Grep word-boundary verification for constant extraction refactors",
        "Design extracted methods for future integration without implementing it",
        "Backward-compat layers require individual liveness evaluation",
        "Use method names not line numbers for refactoring plans",
        "Document trade-off when removing implicit documentation",
        "Line number shifts in multi-PR merges break implementation plans",
        "Use underscore prefix for local implementation details in functions",
        "Partial migrations of similar components create maintenance burden",
    ],
    "architecture-patterns-practices.md": [
        "Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers",
        "Dynamic Discovery with Convention-Based Naming",
        "Coordinator pattern with call-order sensitivity",
        "NamedTuple for multi-return extracted methods",
        "Parameter threading across extracted methods",
        "Structured transcript parsing: markers, summaries, and item lists",
        "Separate parsing utilities from subprocess and streaming concerns",
        "Thin public wrappers replace private method access",
        "Line/method budgets force better decomposition",
        "Selective EventBus threading by behavioral side effects",
        "Never-raise contract uses broad exception catching",
        "exc_info=True parameter preserves full tracebacks at lower levels",
        "Test class names describe scenarios, not test subjects",
        "Inline implementations preferred over extracted utility classes",
        "Prompt Deduplication and Memory Context Capping",
        "Strategy dispatcher pattern for conditional behavior branches",
        "Export widely-reused constants without underscore prefix",
        "Document variant patterns; resist premature parameterization",
        "Dependency injection + re-export for backward-compatible class splits",
        "Sub-factory coordination via intermediate frozen dataclass",
        "Distinguish local wiring from cross-group wiring at architecture boundary",
        "AST-based regression tests are fragile to refactoring",
    ],
}


def main() -> int:
    if not WIKI_DIR.exists():
        logger.error("docs/wiki/ not found — run from repo root")
        return 1

    report = CleanupReport()

    # 1+2+3: delete bad-title entries
    _delete_titles(
        WIKI_DIR / "architecture.md",
        REVIEW_PATTERN_TITLES | GENERIC_HEADER_TITLES_ARCH | RUNBOOK_TITLES_ARCH,
        report,
    )
    _delete_titles(WIKI_DIR / "testing.md", GENERIC_HEADER_TITLES_TESTING, report)
    _delete_titles(WIKI_DIR / "gotchas.md", GENERIC_HEADER_TITLES_GOTCHAS, report)
    _delete_titles(WIKI_DIR / "patterns.md", GENERIC_HEADER_TITLES_PATTERNS, report)

    # 4: retitle
    for filename, mapping in RETITLE_MAPS.items():
        _retitle_entries(WIKI_DIR / filename, mapping, report)

    # 5: split architecture.md
    _split_topic_into_subfiles(WIKI_DIR / "architecture.md", ARCHITECTURE_SPLIT, report)

    # 6: rebuild index
    _rebuild_index(report)

    logger.info("Deleted %d entries", len(report.deleted))
    logger.info("Retitled %d entries", len(report.retitled))
    logger.info("Moved %d entries into sub-topic files", len(report.moved))
    logger.info("Wrote %d files", len(set(report.files_written)))
    if report.not_found:
        logger.warning(
            "Skipped %d titles not found (already cleaned?):",
            len(report.not_found),
        )
        for filename, title in report.not_found[:5]:
            logger.warning("  %s: %r", filename, title)
        if len(report.not_found) > 5:
            logger.warning("  ... and %d more", len(report.not_found) - 5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
