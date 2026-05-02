"""Prompt audit script — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Allow direct invocation (`python scripts/audit_prompts.py`) from the repo root:
# render() imports `tests.fixtures.prompts.fakes`, which requires the project
# root on sys.path. Under pytest this is automatic; under bare invocation it's not.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Also add the `src/` directory so builder imports like `import triage` resolve.
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


@dataclass(frozen=True)
class AuditTarget:
    name: str
    builder_qualname: str
    fixture_path: str
    category: str
    call_site: str
    unrenderable: bool = False
    unrenderable_reason: str = ""


PROMPT_REGISTRY: list[AuditTarget] = [
    # Triage
    AuditTarget(
        "triage_build_prompt",
        "triage.TriageRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/triage_build_prompt.json",
        "Triage",
        "src/triage.py:194",
    ),
    AuditTarget(
        "triage_decomposition",
        "triage.TriageRunner._build_decomposition_prompt",
        "tests/fixtures/prompts/triage_decomposition.json",
        "Triage",
        "src/triage.py:511",
    ),
    # Plan
    AuditTarget(
        "planner_build_prompt_first_attempt",
        "planner.PlannerRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/planner_build_prompt_first_attempt.json",
        "Plan",
        "src/planner.py:297",
    ),
    AuditTarget(
        "planner_retry",
        "planner.PlannerRunner._build_retry_prompt",
        "tests/fixtures/prompts/planner_retry.json",
        "Plan",
        "src/planner.py:857",
    ),
    AuditTarget(
        "plan_reviewer",
        "plan_reviewer.PlanReviewer._build_prompt",
        "tests/fixtures/prompts/plan_reviewer.json",
        "Plan",
        "src/plan_reviewer.py:233",
    ),
    # Implement
    AuditTarget(
        "agent_build_prompt_first_attempt",
        "agent.AgentRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/agent_build_prompt_first_attempt.json",
        "Implement",
        "src/agent.py:572",
    ),
    AuditTarget(
        "agent_build_prompt_with_review_feedback",
        "agent.AgentRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/agent_build_prompt_with_review_feedback.json",
        "Implement",
        "src/agent.py:572",
    ),
    AuditTarget(
        "agent_build_prompt_with_prior_failure",
        "agent.AgentRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/agent_build_prompt_with_prior_failure.json",
        "Implement",
        "src/agent.py:572",
    ),
    AuditTarget(
        "agent_quality_fix",
        "agent.AgentRunner._build_quality_fix_prompt",
        "tests/fixtures/prompts/agent_quality_fix.json",
        "Implement",
        "src/agent.py:877",
    ),
    AuditTarget(
        "agent_pre_quality_review",
        "agent.AgentRunner._build_pre_quality_review_prompt",
        "tests/fixtures/prompts/agent_pre_quality_review.json",
        "Implement",
        "src/agent.py:903",
    ),
    AuditTarget(
        "agent_pre_quality_run_tool",
        "agent.AgentRunner._build_pre_quality_run_tool_prompt",
        "tests/fixtures/prompts/agent_pre_quality_run_tool.json",
        "Implement",
        "src/agent.py:956",
    ),
    # Review
    AuditTarget(
        "reviewer_build_review",
        "reviewer.ReviewRunner._build_review_prompt_with_stats",
        "tests/fixtures/prompts/reviewer_build_review.json",
        "Review",
        "src/reviewer.py:676",
    ),
    AuditTarget(
        "reviewer_ci_fix",
        "reviewer.ReviewRunner._build_ci_fix_prompt",
        "tests/fixtures/prompts/reviewer_ci_fix.json",
        "Review",
        "src/reviewer.py:473",
    ),
    AuditTarget(
        "reviewer_review_fix",
        "reviewer.ReviewRunner._build_review_fix_prompt",
        "tests/fixtures/prompts/reviewer_review_fix.json",
        "Review",
        "src/reviewer.py:441",
    ),
    AuditTarget(
        "pr_unsticker_ci_fix",
        "pr_unsticker.PRUnsticker._build_ci_fix_prompt",
        "tests/fixtures/prompts/pr_unsticker_ci_fix.json",
        "Review",
        "src/pr_unsticker.py:498",
    ),
    AuditTarget(
        "pr_unsticker_ci_timeout",
        "pr_unsticker.PRUnsticker._build_ci_timeout_fix_prompt",
        "tests/fixtures/prompts/pr_unsticker_ci_timeout.json",
        "Review",
        "src/pr_unsticker.py:846",
    ),
    # HITL
    AuditTarget(
        "hitl_build_prompt",
        "hitl_runner.HITLRunner._build_prompt_with_stats",
        "tests/fixtures/prompts/hitl_build_prompt.json",
        "HITL",
        "src/hitl_runner.py:175",
    ),
    # Adjacent
    AuditTarget(
        "diff_sanity",
        "diff_sanity.build_diff_sanity_prompt",
        "tests/fixtures/prompts/diff_sanity.json",
        "Adjacent",
        "src/diff_sanity.py:13",
    ),
    AuditTarget(
        "test_adequacy",
        "test_adequacy.build_test_adequacy_prompt",
        "tests/fixtures/prompts/test_adequacy.json",
        "Adjacent",
        "src/test_adequacy.py:13",
    ),
    AuditTarget(
        "spec_match_requirements_gap",
        "spec_match.build_requirements_gap_prompt",
        "tests/fixtures/prompts/spec_match_requirements_gap.json",
        "Adjacent",
        "src/spec_match.py:108",
    ),
    AuditTarget(
        "conflict_build",
        "conflict_prompt.build_conflict_prompt",
        "tests/fixtures/prompts/conflict_build.json",
        "Adjacent",
        "src/conflict_prompt.py:19",
    ),
    AuditTarget(
        "conflict_rebuild",
        "conflict_prompt.build_rebuild_prompt",
        "tests/fixtures/prompts/conflict_rebuild.json",
        "Adjacent",
        "src/conflict_prompt.py:71",
    ),
    AuditTarget(
        "expert_council_vote",
        "expert_council.ExpertCouncil._build_vote_prompt",
        "tests/fixtures/prompts/expert_council_vote.json",
        "Adjacent",
        "src/expert_council.py:278",
    ),
    AuditTarget(
        "diagnostic_runner",
        "diagnostic_runner._build_diagnosis_prompt",
        "tests/fixtures/prompts/diagnostic_runner.json",
        "Adjacent",
        "src/diagnostic_runner.py:32",
    ),
    AuditTarget(
        "adr_reviewer",
        "adr_reviewer.ADRCouncilReviewer._build_orchestrator_prompt",
        "tests/fixtures/prompts/adr_reviewer.json",
        "Adjacent",
        "src/adr_reviewer.py:273",
    ),
]

# ---------------------------------------------------------------------------
# Rubric #1 — leads with the request
# ---------------------------------------------------------------------------

IMPERATIVE_VERBS = frozenset(
    {
        "produce",
        "return",
        "generate",
        "classify",
        "review",
        "decide",
        "output",
        "propose",
        "write",
        "summarize",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split on `.`, `?`, `!`, `:` — any of which can end a directive sentence."""
    return [s.strip() for s in re.split(r"(?<=[.!?:])\s+", text) if s.strip()]


def score_leads_with_request(rendered: str) -> str:
    stripped = re.sub(r"<\w+>.*?</\w+>", "", rendered, flags=re.DOTALL).strip()
    sentences = _split_sentences(stripped)
    for idx, sentence in enumerate(sentences):
        words = set(re.findall(r"[A-Za-z]+", sentence.lower()))
        if words & IMPERATIVE_VERBS:
            if idx == 0:
                return "Pass"
            if idx <= 2:
                return "Partial"
            return "Fail"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #2 — specific
# ---------------------------------------------------------------------------

OUTPUT_ARTIFACT_NOUNS = (
    r"\bJSON\b",
    r"\bobject\b",
    r"\blist\b",
    r"\bclassification\b",
    r"\blabel\b",
    r"\bplan\b",
    r"\breview\b",
    r"\bpatch\b",
    r"\bdiff\b",
    r"\bsummary\b",
)
SCHEMA_CUES = (r"fields:", r"keys:", r"schema", r"`[a-z_][a-z0-9_]*`")
SUCCESS_CRITERIA_CUES = (
    r"\bmust\b",
    r"\bshould\b",
    r"requirements",
    r"the output must",
)


def _any_hit(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def score_specific(rendered: str) -> str:
    hits = sum(
        [
            _any_hit(OUTPUT_ARTIFACT_NOUNS, rendered),
            _any_hit(SCHEMA_CUES, rendered),
            _any_hit(SUCCESS_CRITERIA_CUES, rendered),
        ]
    )
    if hits == 3:
        return "Pass"
    if hits == 2:
        return "Partial"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #3 — XML tag structure
# ---------------------------------------------------------------------------

_TAG_PAIR = re.compile(r"<(\w+)>.*?</\1>", re.DOTALL)
_EXCLUDED_TAGS = frozenset({"thinking", "scratchpad"})


def score_xml_tags(rendered: str) -> str:
    tags = {m.group(1).lower() for m in _TAG_PAIR.finditer(rendered)}
    content_tags = tags - _EXCLUDED_TAGS
    if len(content_tags) >= 3:
        return "Pass"
    if len(content_tags) >= 1:
        return "Partial"
    return "Fail"


# ---------------------------------------------------------------------------
# Rubric #4 — examples where applicable
# ---------------------------------------------------------------------------

_STRUCTURED_CUES = (
    r"\bJSON\b",
    r"\bschema\b",
    r"format:",
    r"fields:",
    r"`[a-z_][a-z0-9_]*`",
)
_EXAMPLE_PRESENT = (r"<example>", r"\bExample:", r"<example ")


def score_examples(rendered: str) -> str:
    applicable = _any_hit(_STRUCTURED_CUES, rendered)
    if not applicable:
        return "N/A"
    return "Pass" if _any_hit(_EXAMPLE_PRESENT, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Rubric #5 — output contract explicit
# ---------------------------------------------------------------------------

_OUTPUT_CONTRACT_CUES = (
    r"respond with",
    r"do not",
    r"no prose",
    r"no markdown",
    r"no apolog",
    r"output format",
    r"return only",
    r"the output must",
)


def score_output_contract(rendered: str) -> str:
    return "Pass" if _any_hit(_OUTPUT_CONTRACT_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Rubric #6 — placement of long context
# ---------------------------------------------------------------------------

LONG_CONTEXT_THRESHOLD = 10_000


def _largest_tagged_block_end(rendered: str) -> int:
    best_end = -1
    best_len = -1
    for match in _TAG_PAIR.finditer(rendered):
        if match.group(1).lower() in _EXCLUDED_TAGS:
            continue
        length = match.end() - match.start()
        if length > best_len:
            best_len = length
            best_end = match.end()
    return best_end


def _last_imperative_offset(rendered: str) -> int:
    verbs = "|".join(sorted(IMPERATIVE_VERBS))
    last = -1
    for match in re.finditer(rf"\b({verbs})\b", rendered, re.IGNORECASE):
        last = match.start()
    return last


def score_long_context_placement(rendered: str) -> str:
    if len(rendered) < LONG_CONTEXT_THRESHOLD:
        return "N/A"
    block_end = _largest_tagged_block_end(rendered)
    last_imp = _last_imperative_offset(rendered)
    if block_end == -1 or last_imp == -1:
        return "Fail"
    return "Pass" if block_end < last_imp else "Fail"


# ---------------------------------------------------------------------------
# Rubric #7 — chain-of-thought scaffolded where decisions are made
# ---------------------------------------------------------------------------

_DECISION_VERBS = frozenset(
    {
        "classify",
        "decide",
        "verdict",
        "approve",
        "reject",
        "score",
        "rank",
        "choose",
        "determine",
        "evaluate",
    }
)
_COT_CUES = (r"<thinking>", r"<scratchpad>", r"think step by step", r"reason first")


def score_cot(rendered: str) -> str:
    words = set(re.findall(r"[A-Za-z]+", rendered.lower()))
    applicable = bool(words & _DECISION_VERBS)
    if not applicable:
        return "N/A"
    return "Pass" if _any_hit(_COT_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Rubric #8 — edge cases named
# ---------------------------------------------------------------------------

_EDGE_CASE_CUES = (
    r"if (empty|missing|truncated|unclear|no \w+)",
    r"when the \w+ (is not|cannot|fails)",
    r"\botherwise,",
    r"in case of",
    r"\bfallback\b",
    r"do not assume",
)


def score_edge_cases(rendered: str) -> str:
    return "Pass" if _any_hit(_EDGE_CASE_CUES, rendered) else "Fail"


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------


@dataclass
class Scorecard:
    scores: dict[int, str] = field(default_factory=dict)


def severity_for(card: Scorecard) -> str:
    fails = [k for k, v in card.scores.items() if v == "Fail"]
    partials = [k for k, v in card.scores.items() if v == "Partial"]
    if len(fails) >= 2 or 1 in fails or 6 in fails:
        return "High"
    if len(fails) == 1 or len(partials) >= 3:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Combined score() — applies all eight rubric rules
# ---------------------------------------------------------------------------


def score(rendered: str) -> Scorecard:
    return Scorecard(
        scores={
            1: score_leads_with_request(rendered),
            2: score_specific(rendered),
            3: score_xml_tags(rendered),
            4: score_examples(rendered),
            5: score_output_contract(rendered),
            6: score_long_context_placement(rendered),
            7: score_cot(rendered),
            8: score_edge_cases(rendered),
        }
    )


# ---------------------------------------------------------------------------
# Fixture loader + render helper
# ---------------------------------------------------------------------------


@dataclass
class LoadedFixture:
    builder: str
    args: dict
    faked_deps: dict


def _coerce_task_dicts(args: dict) -> dict:
    """Convert dict values that look like Tasks/PRInfo/GitHubIssue/EscalationContext.

    Builders that accept ``issue: Task`` expect a Pydantic model, not a raw dict.
    We detect fixture patterns and coerce automatically:

    - dict with ``id`` + ``title`` → ``Task``
    - dict with ``number`` + ``branch`` → ``PRInfo``
    - dict with ``number`` + ``title`` (no ``id``) → ``GitHubIssue``
    - dict with ``cause`` + ``origin_phase`` → ``EscalationContext``
    """
    from models import EscalationContext, GitHubIssue, PRInfo, Task  # noqa: PLC0415

    coerced = {}
    for key, value in args.items():
        if isinstance(value, dict):
            if "id" in value and "title" in value:
                coerced[key] = Task(**value)
            elif "number" in value and "branch" in value:
                coerced[key] = PRInfo(**value)
            elif "number" in value and "title" in value and "id" not in value:
                coerced[key] = GitHubIssue(**value)
            elif "cause" in value and "origin_phase" in value:
                coerced[key] = EscalationContext(**value)
            else:
                coerced[key] = value
        else:
            coerced[key] = value
    return coerced


def load_fixture(path: str) -> LoadedFixture:
    data = json.loads(Path(path).read_text())
    raw_args = data.get("args", {})
    coerced_args = _coerce_task_dicts(raw_args)
    return LoadedFixture(
        builder=data["builder"],
        args=coerced_args,
        faked_deps=data.get("faked_deps", {}),
    )


def render(builder_callable, *, args: dict, faked_deps: dict) -> str:
    """Call the builder with args + resolved fakes; return the rendered string.

    Builders that return a tuple (e.g. ``_build_prompt_with_stats`` returns
    ``(prompt, stats)``) are unwrapped to the first element. Multi-turn builders
    returning a list of ``{role, content}`` messages are serialized with a
    sentinel separator (``===SYSTEM===`` / ``===USER===``).
    """
    # Lazy import so the helper is usable even if the fakes module is not installed.
    from tests.fixtures.prompts.fakes import get_fake  # noqa: PLC0415

    resolved = dict(args)
    for dep_name, shape in faked_deps.items():
        resolved[dep_name] = get_fake(dep_name, shape)

    result = builder_callable(**resolved)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        parts_out = []
        for msg in result:
            role = msg.get("role", "user").upper()
            parts_out.append(f"==={role}===")
            parts_out.append(msg.get("content", ""))
        return "\n".join(parts_out)
    return str(result)


# ---------------------------------------------------------------------------
# Target resolution + rendering
# ---------------------------------------------------------------------------


class _MinimalConfig:
    """Minimal stand-in for HydraFlowConfig — builders typically read only a
    handful of ``max_*_chars`` fields and booleans. Extend as needed."""

    def __init__(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        self.dry_run = False
        self.max_impl_plan_chars = 50_000
        self.max_review_feedback_chars = 50_000
        self.error_output_max_chars = 50_000
        self.max_common_feedback_chars = 50_000
        # Planner-specific fields
        self.max_planner_comment_chars = 1_000
        self.max_planner_line_chars = 500
        self.max_planner_failed_plan_chars = 4_000
        self.max_issue_body_chars = 10_000
        self.find_label = ["hydraflow-find"]
        self.required_plugins: list[str] = []
        self.phase_skills: dict[str, list[str]] = {}
        # Agent / reviewer fields
        self.test_command = "make test"
        self.repo_root = _Path(".")
        self.data_root = _Path(tempfile.mkdtemp())
        self.plans_dir = self.data_root / "plans"
        self.memory_dir = self.data_root / "memory"
        self.min_review_findings = 3
        self.max_ci_fix_attempts = 3
        self.repo = "owner/repo"
        self.review_insight_window = 50
        self.review_pattern_threshold = 3
        # ADR reviewer fields
        self.adr_review_approval_threshold = 2
        self.adr_review_max_rounds = 3

    def data_path(self, *parts: object) -> object:
        return self.data_root.joinpath(*[str(p) for p in parts])

    def __getattr__(self, name: str) -> object:
        # Fallback: any unrecognized config attr resolves to a large int.
        # Prevents AttributeError when builders reach for new max_* fields.
        if name.startswith("max_") and name.endswith("_chars"):
            return 50_000
        raise AttributeError(name)


class _NullContextCache:
    """Stub for ContextSectionCache — always returns empty string (cache miss).

    ``_get_review_feedback_section`` and ``_get_escalation_data`` call
    ``get_or_load`` and treat errors as transient, but ``AttributeError`` on
    ``None`` is classified as a bug by ``is_likely_bug`` and re-raised.  This
    stub avoids that by returning a safe empty result without raising.
    """

    def get_or_load(self, **_kwargs: object) -> tuple[str, bool]:
        return "", False


def render_target(target: AuditTarget) -> str:
    """Resolve qualname, load fixture, call the builder, return rendered text."""
    fixture = load_fixture(target.fixture_path)
    parts = target.builder_qualname.split(".")
    module = importlib.import_module(parts[0])
    if len(parts) == 2:
        callable_obj = getattr(module, parts[1])
    elif len(parts) == 3:
        cls = getattr(module, parts[1])
        descriptor = inspect.getattr_static(cls, parts[2])
        if isinstance(descriptor, staticmethod | classmethod):
            callable_obj = getattr(cls, parts[2])
        else:
            instance = cls.__new__(cls)
            instance._config = _MinimalConfig()
            instance._hindsight = None
            instance._wiki_store = None
            instance._last_context_stats = {}
            # _insights: used by _get_escalation_data / _get_review_feedback_section.
            # Those methods wrap everything in try/except and return [] / "" on error,
            # so None is safe (AttributeError is caught as a transient failure there).
            # _context_cache: must be a real stub — AttributeError on None is
            # classified as a bug by is_likely_bug and re-raised.
            instance._insights = None
            instance._context_cache = _NullContextCache()
            # _adr_index: required since #8460 dropped the getattr defensiveness
            # in BaseRunner. None is a valid runtime value (loaded lazily).
            instance._adr_index = None
            instance._tribal_wiki_store = None
            instance._bus = None
            callable_obj = getattr(instance, parts[2])
    else:
        raise ValueError(f"unsupported qualname depth: {target.builder_qualname!r}")
    return render(callable_obj, args=fixture.args, faked_deps=fixture.faked_deps)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    target: AuditTarget
    rendered: str
    scorecard: Scorecard


_CATEGORY_ORDER = ["Triage", "Plan", "Implement", "Review", "HITL", "Adjacent"]
_SEVERITY_ORDER = ["High", "Medium", "Low", "Unscored"]


def _excerpt(rendered: str, limit: int = 500) -> str:
    ex = rendered[:limit].rstrip()
    return ex + ("…" if len(rendered) > limit else "")


def _fail_reason_note(criterion: int) -> str:
    return {
        1: "request buried — model may misidentify task intent",
        6: "long context placed after the request — degrades recall in long prompts",
    }.get(criterion, "")


def write_markdown(
    results: list[AuditResult],
    out_path: Path,
    rubric_stub: Path,
    handoff_stub: Path,
) -> None:
    sev_counter = Counter(severity_for(r.scorecard) for r in results)
    total_fails: Counter[int] = Counter()
    for r in results:
        for k, v in r.scorecard.scores.items():
            if v == "Fail":
                total_fails[k] += 1
    top_fail_ids = [c for c, _ in total_fails.most_common(3)]

    lines: list[str] = []
    lines.append("# Prompt Audit — 2026-04-20")
    lines.append("")

    # Section 1: Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Prompts audited: {len(results)}")
    for sev in _SEVERITY_ORDER:
        lines.append(f"- {sev}: {sev_counter.get(sev, 0)}")
    lines.append(f"- Most common Fails by criterion: {top_fail_ids}")
    lines.append("")

    # Section 2: Rubric reference (static stub)
    if rubric_stub.exists():
        lines.append(rubric_stub.read_text().strip())
        lines.append("")

    # Section 3: Inventory table
    lines.append("## Inventory")
    lines.append("")
    lines.append("| Prompt | Category | File:Line | Severity | Fails | Partials |")
    lines.append("|---|---|---|---|---|---|")
    ordered = sorted(
        results,
        key=lambda r: (
            _SEVERITY_ORDER.index(severity_for(r.scorecard)),
            r.target.category,
            r.target.name,
        ),
    )
    for r in ordered:
        sev = severity_for(r.scorecard)
        fails = (
            ",".join(str(k) for k, v in r.scorecard.scores.items() if v == "Fail")
            or "—"
        )
        partials = (
            ",".join(str(k) for k, v in r.scorecard.scores.items() if v == "Partial")
            or "—"
        )
        lines.append(
            f"| `{r.target.name}` | {r.target.category} | {r.target.call_site} | "
            f"{sev} | {fails} | {partials} |"
        )
    lines.append("")

    # Section 4: Per-category scorecards
    for category in _CATEGORY_ORDER:
        cat_results = [r for r in results if r.target.category == category]
        if not cat_results:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for r in cat_results:
            sev = severity_for(r.scorecard)
            scores_str = " · ".join(
                f"#{k} {v}" for k, v in sorted(r.scorecard.scores.items())
            )
            lines.append(f"### {r.target.name}")
            lines.append(f"{r.target.call_site} · Severity: **{sev}**")
            lines.append("")
            lines.append(f"Scores: {scores_str}")
            lines.append("")
            fails = [k for k, v in r.scorecard.scores.items() if v == "Fail"]
            if fails:
                lines.append("Findings:")
                for k in fails:
                    note = _fail_reason_note(k)
                    suffix = f" — {note}" if note else ""
                    lines.append(f"- #{k} failed{suffix}")
                lines.append("")
            lines.append("Excerpt (first 500 chars):")
            lines.append("")
            lines.append("```")
            lines.append(_excerpt(r.rendered))
            lines.append("```")
            lines.append("")
            lines.append(
                f"Full rendered: "
                f"[`tests/fixtures/prompts/rendered/{r.target.name}.txt`]"
                f"(../tests/fixtures/prompts/rendered/{r.target.name}.txt)"
            )
            lines.append("")

    # Section 5: Prioritized fix list
    lines.append("## Prioritized fix list")
    lines.append("")
    for sev in ["High", "Medium", "Low"]:
        grouped = [r for r in results if severity_for(r.scorecard) == sev]
        if not grouped:
            continue
        grouped.sort(
            key=lambda r: (
                _CATEGORY_ORDER.index(r.target.category)
                if r.target.category in _CATEGORY_ORDER
                else 99,
                r.target.name,
            )
        )
        lines.append(f"### {sev}")
        lines.append("")
        for r in grouped:
            fails = [k for k, v in r.scorecard.scores.items() if v == "Fail"]
            note = ""
            if sev == "High":
                top_note = next(
                    (_fail_reason_note(k) for k in fails if _fail_reason_note(k)), ""
                )
                if top_note:
                    note = f" — {top_note}"
            lines.append(f"- `{r.target.name}` ({r.target.category}){note}")
        lines.append("")

    # Section 6: Handoff (static stub)
    if handoff_stub.exists():
        lines.append(handoff_stub.read_text().strip())
        lines.append("")

    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Canary cross-check
# ---------------------------------------------------------------------------


def _levenshtein_ratio(a: str, b: str) -> float:
    """Return distance / max-length, in [0.0, 1.0]. Inline impl — no external dep."""
    if not a and not b:
        return 0.0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[n] / max(m, n)


def cross_check_canary_coverage(trace_path: Path) -> list[str]:
    errors: list[str] = []
    trace_entries = [
        json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()
    ]

    registered_qualnames = {t.builder_qualname for t in PROMPT_REGISTRY}

    for entry in trace_entries:
        call_site: str = entry.get("call_site", "")
        matching = [
            q for q in registered_qualnames if q.rsplit(".", 1)[-1] in call_site
        ]
        if not matching:
            errors.append(f"trace has unregistered builder in call_site: {call_site!r}")
            continue
        trace_prompt = entry.get("prompt", "")
        best = 1.0
        for target in PROMPT_REGISTRY:
            if target.builder_qualname not in matching:
                continue
            snapshot_path = Path(f"tests/fixtures/prompts/rendered/{target.name}.txt")
            if not snapshot_path.exists():
                continue
            ratio = _levenshtein_ratio(trace_prompt, snapshot_path.read_text())
            best = min(best, ratio)
        if best > 0.5:
            errors.append(
                f"drift >50% between trace and nearest snapshot for {call_site!r} "
                f"(ratio={best:.2f})"
            )
    return errors


def main() -> None:
    out_path = Path(
        os.environ.get("PROMPT_AUDIT_OUT", "docs/prompt-audit-2026-04-20.md")
    )
    rubric_stub = Path(
        os.environ.get("PROMPT_AUDIT_RUBRIC_STUB", "docs/_prompt_audit_rubric.md")
    )
    handoff_stub = Path(
        os.environ.get("PROMPT_AUDIT_HANDOFF_STUB", "docs/_prompt_audit_handoff.md")
    )

    results: list[AuditResult] = []
    for target in PROMPT_REGISTRY:
        if target.unrenderable:
            results.append(
                AuditResult(
                    target=target,
                    rendered="",
                    scorecard=Scorecard(scores=dict.fromkeys(range(1, 9), "N/A")),
                )
            )
            continue
        rendered = render_target(target)
        results.append(
            AuditResult(
                target=target,
                rendered=rendered,
                scorecard=score(rendered),
            )
        )
    write_markdown(results, out_path, rubric_stub, handoff_stub)
    print(f"wrote {out_path}")

    trace_path = Path(
        os.environ.get(
            "PROMPT_AUDIT_TRACE", "tests/fixtures/prompts/canary-trace.jsonl"
        )
    )
    if trace_path.exists():
        errors = cross_check_canary_coverage(trace_path)
        if errors:
            print("canary cross-check warnings:")
            for e in errors:
                print(f"  - {e}")


if __name__ == "__main__":
    main()
