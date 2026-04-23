# Product-Phase Trust — Discover + Shape Evaluators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the upstream half of the lights-off pipeline. Today HydraFlow's Discover and Shape phases have no adversarial gate — a prompt regression that produces a shallow Discover brief or an incoherent Shape proposal is silently consumed by the downstream Plan phase and propagates into bad code. This plan adds two new evaluator skills (`discover-completeness`, `shape-coherence`), wires them into `DiscoverRunner` / `ShapeRunner` as post-output retries bounded by new config, extends the §4.1 adversarial corpus with ~8–12 product-phase cases, and ships a MockWorld scenario that proves the retry-on-bad-brief behavior end to end.

**Architecture:** This is **NOT** a new background loop. It is a runner-side dispatch + retry extension plus two new `BUILTIN_SKILLS` entries. The post-impl skill contract in `src/skill_registry.py:BUILTIN_SKILLS` (name, purpose, config_key, blocking, prompt_builder, result_parser) is reused verbatim. Where the post-impl path runs skills inside `agent.py:_run_skill` against a branch diff, the product-phase path runs evaluators inside `DiscoverRunner.discover` / `ShapeRunner.run_turn` against the just-produced brief/proposal. The `BUILTIN_SKILLS` contract has no built-in runner-side hook for product-phase dispatch today, so this plan adds one — a module-local helper `_dispatch_product_phase_skill` per runner that looks the skill up by name, builds its prompt, calls `self._execute(...)` once, parses the transcript, and returns `LoopResult`. On RETRY the runner loops up to `max_discover_attempts` / `max_shape_attempts` (new config, default 3). On exhaustion it files `hitl-escalation` via `PRManager.create_issue` with label `discover-stuck` or `shape-stuck`, dedup-keyed `discover_runner:{issue}` / `shape_runner:{issue}`.

**Tech Stack:** Python 3.11, pydantic `BaseModel`, existing HydraFlow `BaseRunner._execute` / `PRManager.create_issue` / `DedupStore` / `skill_registry.BUILTIN_SKILLS` / `skill_registry.AgentSkill` infrastructure, pytest, `tests/scenarios/fakes/mock_world.py` MockWorld harness.

**Spec:** [`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`](../specs/2026-04-22-trust-architecture-hardening-design.md) — implements §4.10 end-to-end (purpose, rubrics, corpus extension, harness reuse, CorpusLearningLoop reuse, wiring, dispatch timing, testing obligations) per §3.2 autonomy stance (bounded retry → auto-escalate, no human on the happy path) and §4.1 corpus layout.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/discover_completeness.py` | **Create** | `discover-completeness` skill — prompt builder + result parser, five RETRY keywords |
| `src/shape_coherence.py` | **Create** | `shape-coherence` skill — prompt builder + result parser, five RETRY keywords |
| `src/skill_registry.py` | Modify (append to `BUILTIN_SKILLS`) | Register both new skills |
| `src/config.py` | Modify (two new Fields + two new `_ENV_INT_OVERRIDES` entries) | `max_discover_attempts`, `max_shape_attempts` (default 3) |
| `src/discover_runner.py` | Modify (inject evaluator dispatch + retry loop + escalation) | Call `discover-completeness` after brief produced; retry; escalate |
| `src/shape_runner.py` | Modify (same pattern on `run_turn`) | Call `shape-coherence` after proposal produced; retry; escalate |
| `tests/test_discover_completeness_skill.py` | **Create** | Unit tests — prompt build, parser OK, parser RETRY with each of five keywords |
| `tests/test_shape_coherence_skill.py` | **Create** | Unit tests — prompt build, parser OK, parser RETRY with each of five keywords |
| `tests/test_discover_runner_evaluator.py` | **Create** | Unit tests — runner dispatch, retry-on-RETRY, escalation on exhaustion, dedup |
| `tests/test_shape_runner_evaluator.py` | **Create** | Unit tests — same for Shape |
| `tests/trust/adversarial/cases/discover-*/...` | **Create** (4–6 dirs) | `before/`, `after/`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt` |
| `tests/trust/adversarial/cases/shape-*/...` | **Create** (4–6 dirs) | Same layout, `expected_catcher.txt = shape-coherence` |
| `tests/scenarios/test_product_phase_scenario.py` | **Create** | MockWorld: vague issue → Discover (bad then good) → Shape → Plan, assert RETRY then accept |

No Makefile / CI / 5-checkpoint (loop-wiring) changes are required — there is no loop and the adversarial harness (`tests/trust/adversarial/test_adversarial_corpus.py`, from the §4.1 plan) already reads `skill_registry.BUILTIN_SKILLS` dynamically, so new skill names are auto-accepted.

---

## Phase 1 — `discover-completeness` skill

Goal: ship the skill module + registry entry + unit tests. The skill is a pure prompt+parser pair, identical in contract to `src/diff_sanity.py`.

---

### Task 1: Create `src/discover_completeness.py`

**Files:**
- Create: `src/discover_completeness.py`

Prompt text is load-bearing — it is the rubric defined in §4.10. Each criterion maps to one RETRY keyword, emitted in the `SUMMARY:` line so the parser can extract it and the adversarial-corpus harness can match against `README.md` keywords.

- [ ] **Step 1: Write the skill module**

Create `src/discover_completeness.py`:

```python
"""Discover Completeness skill — evaluates a Discover brief for rubric compliance.

Portable across Claude, Codex, and Pi backends. Pure prompt + parser;
structured markers in the transcript are parsed to determine pass/fail
and to extract the specific RETRY keyword the rubric names.

See docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.10 for the rubric. Returns RETRY with one of five keywords:

- missing-section:<name>  (structure failure)
- shallow-section:<name>  (non-trivial-content failure)
- paraphrase-only         (no new information vs. the issue body)
- vague-criterion         (acceptance criteria not testable)
- hid-ambiguity           (zero open questions despite ambiguous input)
"""

from __future__ import annotations

import re


def build_discover_completeness_prompt(
    *,
    issue_number: int,
    issue_title: str,
    issue_body: str = "",
    brief: str = "",
    **_kwargs: object,
) -> str:
    """Build a prompt that asks an agent to evaluate a Discover brief.

    ``issue_body`` is the original issue text the brief was produced from.
    ``brief`` is the discovery brief to evaluate. Both are required for a
    meaningful rubric check — the rubric compares the two.
    """
    return f"""You are running the Discover Completeness skill for issue #{issue_number}: {issue_title}.

You are evaluating a DISCOVERY BRIEF against the five-criterion rubric
below. You are NOT producing a brief — you are judging one.

## Original Issue Body

```
{issue_body}
```

## Discovery Brief To Evaluate

```
{brief}
```

## Rubric — All Five Must Pass

1. **Structure.** The brief MUST contain named sections for *Intent*,
   *Affected area*, *Acceptance criteria*, *Open questions*, and
   *Known unknowns*. Section headings may be any case, any heading
   style (`##`, `**bold**`, plain line ending in `:`); the keyword
   must appear. If any section is absent, emit RETRY keyword
   `missing-section:<name>` where `<name>` is the lower-kebab
   canonical section name (`intent`, `affected-area`,
   `acceptance-criteria`, `open-questions`, `known-unknowns`).

2. **Non-trivial content.** Each section has ≥50 characters of prose
   OR ≥3 bulleted items (bullets required for *Acceptance criteria*
   and *Open questions*). If a section is present but too short,
   emit RETRY keyword `shallow-section:<name>` (same canonical
   section names).

3. **No paraphrase-only.** At least one section adds information NOT
   present in the original issue body — e.g. names a competitor, a
   constraint, an affected file, a measurable target, a persona, or
   a sequenced sub-problem. A brief that only rephrases the issue
   body in different words is a paraphrase-only failure: emit RETRY
   keyword `paraphrase-only`.

4. **Concrete acceptance criteria.** Every bullet in *Acceptance
   criteria* names an observable outcome — a metric, a UI state, a
   CLI exit code, a parsed field, a benchmark threshold.  Vague
   aspirations ("the app is faster", "users are happier", "it feels
   better") fail. If any bullet is vague, emit RETRY keyword
   `vague-criterion`.

5. **Open questions when ambiguous.** If the issue body contains
   ambiguity markers — any of: "maybe", "could be", "not sure", "it
   depends", "we might", "possibly", "unclear", "tbd" — the brief's
   *Open questions* section MUST list at least one explicit
   question. A brief that claims zero open questions despite
   ambiguous input is hiding ambiguity: emit RETRY keyword
   `hid-ambiguity`.

## Instructions

- Check each criterion in order (1 → 5). A single brief may fail
  multiple criteria; report every failure, but put the FIRST failing
  keyword in the SUMMARY line (the adversarial corpus asserts on it).
- For `missing-section:<name>` and `shallow-section:<name>`, emit one
  FINDINGS entry per offending section (so a brief missing three
  sections produces three findings).
- Do NOT modify any files. This is a read-only evaluation.

## Required Output

If all five criteria pass:
DISCOVER_COMPLETENESS_RESULT: OK
SUMMARY: All five rubric criteria pass

If any criterion fails:
DISCOVER_COMPLETENESS_RESULT: RETRY
SUMMARY: <first-failing-keyword> — <short description>
FINDINGS:
- <keyword> — <specific evidence, quoting the brief or issue body>
"""


_STATUS_RE = re.compile(
    r"DISCOVER_COMPLETENESS_RESULT:\s*(OK|RETRY)", re.IGNORECASE
)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)", re.IGNORECASE)
_FINDINGS_RE = re.compile(
    r"FINDINGS:\s*\n((?:\s*-\s*.+\n?)+)", re.IGNORECASE
)


def parse_discover_completeness_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a discover-completeness transcript.

    Returns ``(passed, summary, findings)``. If no explicit result marker
    is present, returns ``(True, "No explicit result marker", [])`` —
    matching the other skill parsers' fail-open posture so a blank
    transcript does not block the pipeline.
    """
    status_match = _STATUS_RE.search(transcript)
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = _SUMMARY_RE.search(transcript)
    summary = summary_match.group(1).strip() if summary_match else ""

    findings: list[str] = []
    findings_match = _FINDINGS_RE.search(transcript)
    if findings_match:
        for line in findings_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                findings.append(stripped)

    return passed, summary, findings
```

- [ ] **Step 2: Commit the skill module**

```bash
git add src/discover_completeness.py
git commit -m "feat(skill): discover-completeness skill — prompt + parser (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Unit-test `discover-completeness`

**Files:**
- Create: `tests/test_discover_completeness_skill.py`

Tests cover: prompt-build (issue body + brief both embedded), parser OK, parser RETRY for each of the five keywords, parser with no explicit marker (fail-open), parser with findings block.

- [ ] **Step 1: Write the tests**

Create `tests/test_discover_completeness_skill.py`:

```python
"""Unit tests for the discover-completeness skill."""

from __future__ import annotations

from discover_completeness import (
    build_discover_completeness_prompt,
    parse_discover_completeness_result,
)


class TestBuildDiscoverCompletenessPrompt:
    def test_embeds_issue_body_and_brief(self):
        prompt = build_discover_completeness_prompt(
            issue_number=42,
            issue_title="Add login",
            issue_body="Maybe we add a login form? Not sure.",
            brief="## Intent\nAdd login\n## Affected area\nweb",
        )
        assert "#42" in prompt
        assert "Add login" in prompt
        assert "Maybe we add a login form?" in prompt
        assert "## Intent\nAdd login" in prompt

    def test_missing_issue_body_still_produces_valid_prompt(self):
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            brief="brief text",
        )
        assert "#1" in prompt
        assert "brief text" in prompt
        assert "DISCOVER_COMPLETENESS_RESULT" in prompt

    def test_rubric_headings_embedded(self):
        """The five-criterion rubric must be in the prompt verbatim."""
        prompt = build_discover_completeness_prompt(
            issue_number=1, issue_title="T", issue_body="b", brief="b"
        )
        assert "Structure." in prompt
        assert "Non-trivial content." in prompt
        assert "No paraphrase-only." in prompt
        assert "Concrete acceptance criteria." in prompt
        assert "Open questions when ambiguous." in prompt

    def test_accepts_unknown_kwargs(self):
        """Skill-registry dispatch passes diff=/plan_text=/etc — must tolerate."""
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            issue_body="b",
            brief="b",
            diff="ignored",
            plan_text="ignored",
        )
        assert prompt  # didn't raise


class TestParseDiscoverCompletenessResult:
    def test_ok_passes(self):
        passed, summary, findings = parse_discover_completeness_result(
            "DISCOVER_COMPLETENESS_RESULT: OK\n"
            "SUMMARY: All five rubric criteria pass\n"
        )
        assert passed is True
        assert "All five" in summary
        assert findings == []

    def test_missing_marker_fails_open(self):
        passed, summary, _ = parse_discover_completeness_result("")
        assert passed is True
        assert "No explicit result marker" in summary

    def test_retry_keyword_missing_section(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: missing-section:acceptance-criteria — no such section\n"
            "FINDINGS:\n"
            "- missing-section:acceptance-criteria — section is absent\n"
        )
        passed, summary, findings = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "missing-section:acceptance-criteria" in summary
        assert len(findings) == 1
        assert "acceptance-criteria" in findings[0]

    def test_retry_keyword_shallow_section(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: shallow-section:open-questions — only one bullet\n"
            "FINDINGS:\n"
            "- shallow-section:open-questions — single bullet present\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "shallow-section:open-questions" in summary

    def test_retry_keyword_paraphrase_only(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: paraphrase-only — brief is a rephrase of the issue body\n"
            "FINDINGS:\n"
            "- paraphrase-only — no new information added\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "paraphrase-only" in summary

    def test_retry_keyword_vague_criterion(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: vague-criterion — 'make it faster' is not observable\n"
            "FINDINGS:\n"
            "- vague-criterion — 'faster' lacks a metric\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "vague-criterion" in summary

    def test_retry_keyword_hid_ambiguity(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: hid-ambiguity — issue says 'maybe' but brief claims zero opens\n"
            "FINDINGS:\n"
            "- hid-ambiguity — 'maybe' in issue body not reflected in questions\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "hid-ambiguity" in summary

    def test_findings_block_parsed_multiline(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: missing-section:intent — first of several\n"
            "FINDINGS:\n"
            "- missing-section:intent — no Intent heading\n"
            "- missing-section:known-unknowns — no Known Unknowns heading\n"
        )
        passed, _, findings = parse_discover_completeness_result(transcript)
        assert passed is False
        assert len(findings) == 2
```

- [ ] **Step 2: Run the tests**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_discover_completeness_skill.py -v`

Expected: all 12 tests pass.

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_discover_completeness_skill.py
git commit -m "test(skill): discover-completeness unit tests — all five RETRY keywords (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Register `discover-completeness` in `BUILTIN_SKILLS`

The registry import list already pulls builders+parsers module-by-module; we add the same pattern for the new module.

**Files:**
- Modify: `src/skill_registry.py`

- [ ] **Step 1: Add import + registry entry**

Modify: `src/skill_registry.py:20-27` — "add module import":

```python
from arch_compliance import build_arch_compliance_prompt, parse_arch_compliance_result
from diff_sanity import build_diff_sanity_prompt, parse_diff_sanity_result
from discover_completeness import (
    build_discover_completeness_prompt,
    parse_discover_completeness_result,
)
from plan_compliance import build_plan_compliance_prompt, parse_plan_compliance_result
from scope_check import build_scope_check_prompt, parse_scope_check_result
from test_adequacy import build_test_adequacy_prompt, parse_test_adequacy_result
```

Modify: `src/skill_registry.py:62-98` — "append new AgentSkill entry at the end of BUILTIN_SKILLS":

```python
    AgentSkill(
        name="test-adequacy",
        purpose="Assess whether changed production code has adequate test coverage, edge cases, and regression safety",
        config_key="max_test_adequacy_attempts",
        blocking=False,
        prompt_builder=build_test_adequacy_prompt,
        result_parser=parse_test_adequacy_result,
    ),
    AgentSkill(
        name="discover-completeness",
        purpose="Evaluate a Discover brief against the five-criterion rubric (structure, non-trivial content, no paraphrase-only, concrete acceptance criteria, open questions when ambiguous)",
        config_key="max_discover_attempts",
        blocking=True,
        prompt_builder=build_discover_completeness_prompt,
        result_parser=parse_discover_completeness_result,
    ),
]
```

- [ ] **Step 2: Smoke-verify the registry loads**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from skill_registry import BUILTIN_SKILLS; print([s.name for s in BUILTIN_SKILLS])"`

Expected: output includes `'discover-completeness'` as the last entry (until Phase 2 appends `shape-coherence`).

The registry entry references `max_discover_attempts`, which does not yet exist on `HydraFlowConfig`. That field lands in Phase 3 Task 9. The `_run_skill` path uses `getattr(self._config, skill.config_key, 0)` so until the field exists, dispatch would no-op — but we are not dispatching via `_run_skill` for product-phase skills (runners dispatch directly via the new helper added in Task 10 / 11 and gate on the config field there). Registry presence alone does not break any existing test.

- [ ] **Step 3: Commit the registry change**

```bash
git add src/skill_registry.py
git commit -m "feat(registry): register discover-completeness in BUILTIN_SKILLS (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — `shape-coherence` skill

Mirror of Phase 1. Same module pattern, same test shape, same registry append.

---

### Task 4: Create `src/shape_coherence.py`

**Files:**
- Create: `src/shape_coherence.py`

Rubric: ≥2 substantive options, do-nothing option, mutually exclusive scope, trade-offs named, reconciles Discover ambiguities.

- [ ] **Step 1: Write the skill module**

Create `src/shape_coherence.py`:

```python
"""Shape Coherence skill — evaluates a Shape proposal for rubric compliance.

See docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.10. Returns RETRY with one of five keywords:

- too-few-options            (fewer than 2 substantive options beyond do-nothing)
- missing-defer              (no explicit "defer / do nothing / status quo" option)
- options-overlap            (options share >50% of the code/scope surface)
- missing-tradeoffs          (at least one option lists no cost/risk)
- dropped-discover-question  (Discover-named open question not addressed)
"""

from __future__ import annotations

import re


def build_shape_coherence_prompt(
    *,
    issue_number: int,
    issue_title: str,
    discover_brief: str = "",
    proposal: str = "",
    **_kwargs: object,
) -> str:
    """Build a prompt that asks an agent to evaluate a Shape proposal.

    ``discover_brief`` is the upstream brief the proposal is responding to
    (may be empty if the issue skipped Discover — the rubric is still
    applicable except for criterion 5).
    ``proposal`` is the Shape proposal text to evaluate.
    """
    return f"""You are running the Shape Coherence skill for issue #{issue_number}: {issue_title}.

You are evaluating a SHAPE PROPOSAL against the five-criterion rubric
below. You are NOT producing a proposal — you are judging one.

## Upstream Discover Brief (for criterion 5)

```
{discover_brief}
```

## Shape Proposal To Evaluate

```
{proposal}
```

## Rubric — All Five Must Pass

1. **At least two substantive options beyond do-nothing.** The
   proposal must list ≥2 distinct product directions, each with a
   name and an approach. "Do nothing" / "defer" alone is not a
   substantive option; it is required separately (criterion 2). If
   fewer than two substantive options are present, emit RETRY
   keyword `too-few-options`.

2. **Do-nothing option present.** The proposal must explicitly
   include a "Defer", "No-op", "Accept status quo", or equivalent
   option, naming the cost of inaction. Missing → RETRY keyword
   `missing-defer`.

3. **Mutually exclusive scope.** Options must not overlap in the
   code areas or user surfaces they touch beyond a 50% threshold.
   Pairwise-compare each option's stated scope (affected files /
   modules / UI areas). If any pair overlaps >50% of the smaller
   option's surface, emit RETRY keyword `options-overlap`. Judgement
   call: if two options both say "edit src/foo.py and src/bar.py"
   but differ only in comment wording, that is overlap.

4. **Trade-offs named per option.** Every option lists at least ONE
   concrete cost, risk, or trade-off — not just upsides. "This is
   the best option" without a downside is a missing-tradeoffs
   failure. If any option lacks a named trade-off, emit RETRY
   keyword `missing-tradeoffs`.

5. **Reconciles Discover ambiguities.** If the upstream Discover
   brief's *Open questions* section named open questions, the Shape
   proposal must address each — either pick a position in one of
   the options, or explicitly punt with a rationale. Un-addressed
   questions → RETRY keyword `dropped-discover-question`. If the
   Discover brief is empty or lists no open questions, this
   criterion is automatically satisfied.

## Instructions

- Check criteria in order (1 → 5). Report every failure, but put the
  FIRST failing keyword in the SUMMARY line (the adversarial corpus
  asserts on it).
- For `dropped-discover-question`, emit one FINDINGS entry per
  un-addressed question (quote it from the Discover brief).
- Do NOT modify any files. This is a read-only evaluation.

## Required Output

If all five criteria pass:
SHAPE_COHERENCE_RESULT: OK
SUMMARY: All five rubric criteria pass

If any criterion fails:
SHAPE_COHERENCE_RESULT: RETRY
SUMMARY: <first-failing-keyword> — <short description>
FINDINGS:
- <keyword> — <specific evidence>
"""


_STATUS_RE = re.compile(r"SHAPE_COHERENCE_RESULT:\s*(OK|RETRY)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)", re.IGNORECASE)
_FINDINGS_RE = re.compile(
    r"FINDINGS:\s*\n((?:\s*-\s*.+\n?)+)", re.IGNORECASE
)


def parse_shape_coherence_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the structured output from a shape-coherence transcript.

    Returns ``(passed, summary, findings)``. Fails open on a missing
    result marker, matching the sibling skills' posture.
    """
    status_match = _STATUS_RE.search(transcript)
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = _SUMMARY_RE.search(transcript)
    summary = summary_match.group(1).strip() if summary_match else ""

    findings: list[str] = []
    findings_match = _FINDINGS_RE.search(transcript)
    if findings_match:
        for line in findings_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                findings.append(stripped)

    return passed, summary, findings
```

- [ ] **Step 2: Commit the skill module**

```bash
git add src/shape_coherence.py
git commit -m "feat(skill): shape-coherence skill — prompt + parser (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Unit-test `shape-coherence`

**Files:**
- Create: `tests/test_shape_coherence_skill.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_shape_coherence_skill.py` with the same structure as Task 2's discover-completeness tests with these substitutions:

- Import source: `discover_completeness` → `shape_coherence`; functions `build_shape_coherence_prompt` / `parse_shape_coherence_result`.
- Prompt-build tests use kwargs `discover_brief=` / `proposal=` in place of `issue_body=` / `brief=`. Include an `test_empty_discover_brief_ok` case (Shape can evaluate without upstream Discover).
- `test_rubric_keywords_embedded` asserts all five new keywords appear in the prompt: `too-few-options`, `missing-defer`, `options-overlap`, `missing-tradeoffs`, `dropped-discover-question`.
- Result marker: `SHAPE_COHERENCE_RESULT` in place of `DISCOVER_COMPLETENESS_RESULT`.
- Five `test_retry_keyword_*` tests — one per Shape keyword above — each constructs a transcript like:

  ```python
  transcript = (
      "SHAPE_COHERENCE_RESULT: RETRY\n"
      "SUMMARY: <keyword> — <short description>\n"
      "FINDINGS:\n- <keyword> — <evidence>\n"
  )
  passed, summary, _ = parse_shape_coherence_result(transcript)
  assert passed is False
  assert "<keyword>" in summary
  ```

- `test_ok_passes` uses `SHAPE_COHERENCE_RESULT: OK` marker.
- `test_missing_marker_fails_open` is identical to the Discover twin.
- `test_accepts_unknown_kwargs` passes `diff="ignored"` + `plan_text="ignored"` alongside the real kwargs and asserts `prompt` is truthy — proves the `**_kwargs` tail swallows registry-dispatch kwargs.

The file is mechanically derivable from `tests/test_discover_completeness_skill.py` via those substitutions. Two test classes total (`TestBuildShapeCoherencePrompt`, `TestParseShapeCoherenceResult`), twelve tests, zero new patterns.

- [ ] **Step 2: Run the tests**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_shape_coherence_skill.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_shape_coherence_skill.py
git commit -m "test(skill): shape-coherence unit tests — all five RETRY keywords (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Register `shape-coherence` in `BUILTIN_SKILLS`

- [ ] **Step 1: Import + registry entry**

Modify: `src/skill_registry.py:20-27` — "add import":

```python
from shape_coherence import (
    build_shape_coherence_prompt,
    parse_shape_coherence_result,
)
```

Modify: `src/skill_registry.py:62-98` — "append second new AgentSkill after discover-completeness":

```python
    AgentSkill(
        name="discover-completeness",
        purpose="Evaluate a Discover brief against the five-criterion rubric (structure, non-trivial content, no paraphrase-only, concrete acceptance criteria, open questions when ambiguous)",
        config_key="max_discover_attempts",
        blocking=True,
        prompt_builder=build_discover_completeness_prompt,
        result_parser=parse_discover_completeness_result,
    ),
    AgentSkill(
        name="shape-coherence",
        purpose="Evaluate a Shape proposal against the five-criterion rubric (≥2 options, do-nothing option, mutually exclusive scope, trade-offs named, reconciles Discover ambiguities)",
        config_key="max_shape_attempts",
        blocking=True,
        prompt_builder=build_shape_coherence_prompt,
        result_parser=parse_shape_coherence_result,
    ),
]
```

- [ ] **Step 2: Smoke-verify**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from skill_registry import BUILTIN_SKILLS; names=[s.name for s in BUILTIN_SKILLS]; print(names); assert 'discover-completeness' in names and 'shape-coherence' in names"`

- [ ] **Step 3: Commit**

```bash
git add src/skill_registry.py
git commit -m "feat(registry): register shape-coherence in BUILTIN_SKILLS (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Runner extensions + config

Add `max_discover_attempts` / `max_shape_attempts` to `HydraFlowConfig`; inject evaluator dispatch + retry + escalation into both runners; unit-test each runner's dispatch path.

---

### Task 7: Add `max_discover_attempts` / `max_shape_attempts` to `HydraFlowConfig`

**Files:**
- Modify: `src/config.py` (env-override table + two `Field(...)` definitions)

- [ ] **Step 1: Add `_ENV_INT_OVERRIDES` entries**

Modify: `src/config.py:82-86` — "append two new env-int override tuples after the other skill-attempt entries":

```python
    ("max_diff_sanity_attempts", "HYDRAFLOW_MAX_DIFF_SANITY_ATTEMPTS", 1),
    ("max_arch_compliance_attempts", "HYDRAFLOW_MAX_ARCH_COMPLIANCE_ATTEMPTS", 1),
    ("max_scope_check_attempts", "HYDRAFLOW_MAX_SCOPE_CHECK_ATTEMPTS", 1),
    ("max_test_adequacy_attempts", "HYDRAFLOW_MAX_TEST_ADEQUACY_ATTEMPTS", 1),
    ("max_plan_compliance_attempts", "HYDRAFLOW_MAX_PLAN_COMPLIANCE_ATTEMPTS", 1),
    ("max_discover_attempts", "HYDRAFLOW_MAX_DISCOVER_ATTEMPTS", 3),
    ("max_shape_attempts", "HYDRAFLOW_MAX_SHAPE_ATTEMPTS", 3),
```

- [ ] **Step 2: Add `Field(...)` entries on `HydraFlowConfig`**

Modify: `src/config.py:500-511` — "append two Field definitions after max_plan_compliance_attempts":

```python
    max_plan_compliance_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max plan compliance check passes (0 = disabled)",
    )
    max_discover_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max Discover-brief evaluator retries before HITL escalation (0 = disabled)",
    )
    max_shape_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max Shape-proposal evaluator retries before HITL escalation (0 = disabled)",
    )
```

- [ ] **Step 3: Verify config loads**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from config import HydraFlowConfig; c = HydraFlowConfig(); print(c.max_discover_attempts, c.max_shape_attempts)"`

Expected: `3 3`.

- [ ] **Step 4: Env-override verify**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && HYDRAFLOW_MAX_DISCOVER_ATTEMPTS=1 HYDRAFLOW_MAX_SHAPE_ATTEMPTS=5 PYTHONPATH=src uv run python -c "from config import HydraFlowConfig; c = HydraFlowConfig.load(); print(c.max_discover_attempts, c.max_shape_attempts)"`

Expected: `1 5`. (`HydraFlowConfig.load()` is the call site that consumes `_ENV_INT_OVERRIDES`; confirm via `grep -n 'def load' src/config.py` if the class-method name has drifted.)

- [ ] **Step 5: Commit**

```bash
git add src/config.py
git commit -m "feat(config): max_discover_attempts, max_shape_attempts (§4.10)

Defaults 3/3 with HYDRAFLOW_MAX_DISCOVER_ATTEMPTS and
HYDRAFLOW_MAX_SHAPE_ATTEMPTS env overrides. Bounded retry budget
for the product-phase evaluators before HITL escalation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Extend `DiscoverRunner` with evaluator dispatch + retry + escalation

The runner produces a `DiscoverResult` today (line ~121 of `src/discover_runner.py`). The extension: after `result` is populated and before the return, evaluate `result.research_brief` via `discover-completeness`. On RETRY, re-run discovery up to `max_discover_attempts`; on exhaustion, file `hitl-escalation` + `discover-stuck` with a dedup key of `discover_runner:{task.id}` against the existing `hitl_escalations` dedup set.

**Files:**
- Modify: `src/discover_runner.py`

The runner's constructor is `BaseRunner.__init__`. To file issues, the runner needs a `PRManager`; to dedup, it needs a `DedupStore`. Rather than widen `BaseRunner.__init__`, the clean path is to keep both optional on `DiscoverRunner` — dispatched from `DiscoverPhase` which already holds `PRManager`. We add a setter (`bind_escalation_deps(prs, dedup)`) so scenarios and production both supply the dependencies, and the runner no-ops escalation if neither is set (falls back to log-only).

- [ ] **Step 1: Add escalation-deps setter + new imports + constants**

Modify: `src/discover_runner.py:1-30` — "add escalation wiring + imports". Two additions to the existing import block and three new module-level constants:

```python
from skill_registry import BUILTIN_SKILLS

if TYPE_CHECKING:
    from dedup_store import DedupStore
    from models import Task
    from pr_manager import PRManager

_SKILL_NAME = "discover-completeness"
_ESCALATION_LABEL_STUCK = "discover-stuck"
_ESCALATION_LABEL_HITL = "hitl-escalation"
```

Add `DedupStore` and `PRManager` to the existing `TYPE_CHECKING` block (which already contains `Task`). Keep all other imports (`json`, `re`, `build_agent_command`, `BaseRunner`, `reraise_on_credit_or_bug`, `DiscoverResult`, `plugin_skill_registry` imports, `MEMORY_SUGGESTION_PROMPT`) unchanged.

Append this method to `DiscoverRunner`:

```python
    def bind_escalation_deps(
        self, prs: PRManager, dedup: DedupStore | None = None
    ) -> None:
        """Wire issue-filing + dedup deps used by escalation.

        Called by :class:`DiscoverPhase` after construction. Without
        binding, escalation logs a warning and returns — dispatch still
        runs the evaluator and bounded retry.
        """
        self._prs = prs
        self._dedup = dedup
```

- [ ] **Step 2: Rework `discover()` to loop with evaluator dispatch**

Modify: `src/discover_runner.py:43-121` — "replace single-shot discover with bounded retry + evaluator dispatch":

```python
    async def discover(self, task: Task, worker_id: int = 0) -> DiscoverResult:
        """Run product discovery with post-output evaluation.

        When ``config.max_discover_attempts > 0`` the runner evaluates
        each produced brief via ``discover-completeness``; on RETRY it
        re-runs discovery up to the budget, then escalates via
        ``hitl-escalation`` / ``discover-stuck`` and returns the last
        (best-available) brief so the phase can still post a comment.
        """
        result = DiscoverResult(issue_number=task.id)
        if self._config.dry_run:
            logger.info("[dry-run] Would run discovery for issue #%d", task.id)
            result.research_brief = "Dry-run: discovery skipped"
            return result

        max_attempts = max(1, self._config.max_discover_attempts or 1)
        evaluator_enabled = self._config.max_discover_attempts > 0
        last_summary, last_findings = "", []
        for attempt in range(1, max_attempts + 1):
            result = await self._run_discovery_once(task, attempt)
            if not evaluator_enabled:
                return result
            passed, summary, findings = await self._evaluate_brief(
                task, result.research_brief
            )
            last_summary, last_findings = summary, findings
            if passed:
                return result
            logger.warning(
                "Discover brief rejected for #%d attempt %d/%d: %s",
                task.id, attempt, max_attempts, summary,
            )
        await self._escalate_stuck(task, last_summary, last_findings, max_attempts)
        return result
```

`_run_discovery_once(task, attempt)` is a pure factoring of the existing `discover` body (lines 49–119 of the original file): same memory injection, same `_check_complete` / `_execute` / `_extract_result` / `_extract_raw_brief` / `_save_transcript` sequence, same exception handling via `reraise_on_credit_or_bug`. Two deltas only: the `_execute` event-data `source` becomes `f"discover:attempt-{attempt}"`, and the transcript save name becomes `f"discover-issue-attempt{attempt}"`. Drop it in verbatim from the existing `discover` body with those two string substitutions.

- [ ] **Step 3: Add the evaluator helper + escalation helper**

Modify: `src/discover_runner.py` — "append private helpers at the end of `DiscoverRunner`":

```python
    async def _evaluate_brief(
        self, task: Task, brief: str
    ) -> tuple[bool, str, list[str]]:
        """Dispatch ``discover-completeness`` against *brief*.

        A missing skill (registry disabled) fails open so this extension
        never blocks discovery on its own absence.
        """
        skill = next((s for s in BUILTIN_SKILLS if s.name == _SKILL_NAME), None)
        if skill is None:
            return True, f"{_SKILL_NAME} not registered — fail open", []
        prompt = skill.prompt_builder(
            issue_number=task.id,
            issue_title=task.title,
            issue_body=task.body or "",
            brief=brief or "",
        )
        try:
            transcript = await self._execute(
                self._build_command(),
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "discover:evaluator"},
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "discover-completeness dispatch failed for #%d: %s", task.id, exc
            )
            return True, f"evaluator dispatch failed: {exc!r}", []
        return skill.result_parser(transcript)

    async def _escalate_stuck(
        self, task: Task, summary: str, findings: list[str], attempts: int
    ) -> None:
        """File hitl-escalation / discover-stuck with dedup.

        Dedup key ``discover_runner:{task.id}`` in the shared
        ``hitl_escalations`` set; close-to-clear follows §3.2 (handled by
        whichever loop polls closed hitl-escalation issues).
        """
        prs = getattr(self, "_prs", None)
        dedup = getattr(self, "_dedup", None)
        key = f"discover_runner:{task.id}"
        if dedup is not None and key in dedup.get():
            logger.info("discover-stuck for #%d already filed (dedup)", task.id)
            return
        if prs is None:
            logger.warning(
                "discover-stuck for #%d but PRManager not bound; logging only. "
                "attempts=%d summary=%s",
                task.id, attempts, summary,
            )
            return
        body = [
            f"Discover-completeness evaluator rejected {attempts} bounded "
            f"retries for issue #{task.id}.",
            "",
            f"**Last summary:** {summary}",
        ]
        if findings:
            body.append("")
            body.append("**Last findings:**")
            for f in findings[:10]:
                body.append(f"- {f}")
        body += [
            "",
            "Action: a human must review the issue body, clarify the "
            "ambiguity that blocked the brief, and either retry Discover "
            "manually or accept the current brief. Closing this issue "
            "clears the dedup key so the runner can retry.",
        ]
        issue_number = await prs.create_issue(
            title=f"[discover-stuck] #{task.id} — {task.title}",
            body="\n".join(body),
            labels=[_ESCALATION_LABEL_HITL, _ESCALATION_LABEL_STUCK],
        )
        if issue_number and dedup is not None:
            dedup.add(key)
            logger.info(
                "Filed discover-stuck escalation #%d for task #%d",
                issue_number, task.id,
            )
```

- [ ] **Step 4: Wire `DiscoverPhase` to bind the escalation deps on runner init**

Modify: `src/discover_phase.py:42-51` — "bind escalation deps after runner is set":

```python
        self._config = config
        self._state = state
        self._store = store
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._runner = discover_runner
        if self._runner is not None:
            dedup = self._state.get_dedup_store("hitl_escalations")
            self._runner.bind_escalation_deps(self._prs, dedup)
```

Note: `self._state.get_dedup_store("hitl_escalations")` is the existing state-facade accessor for `DedupStore`. Verify name via `grep -n 'def get_dedup_store' src/state*.py src/state/*.py`. If the accessor is spelled differently, substitute the right call — the shape is identical.

- [ ] **Step 5: Commit**

```bash
git add src/discover_runner.py src/discover_phase.py
git commit -m "feat(runner): DiscoverRunner dispatches discover-completeness + retry + escalate (§4.10)

After each Discover brief is produced, the runner evaluates it via the
discover-completeness skill from skill_registry.BUILTIN_SKILLS. On
RETRY, it re-runs discovery up to config.max_discover_attempts
(default 3). On exhaustion, files an hitl-escalation / discover-stuck
issue via PRManager, dedup-keyed discover_runner:{issue}. Falls open
when deps are unbound (log-only) so MockWorld-style tests that skip
binding don't crash.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Extend `ShapeRunner` with evaluator dispatch + retry + escalation

Mirror of Task 8, but dispatch on `run_turn` after each turn's `result.content` (the proposal text) is extracted. Retry is bounded by `max_shape_attempts`; escalation label is `shape-stuck`; dedup key is `shape_runner:{task.id}`.

**Files:**
- Modify: `src/shape_runner.py`

Shape is turn-based — the evaluator only needs to run when `result.is_final` is true OR when the content is substantive enough to be called a "proposal" (criteria require ≥2 named options). We evaluate only on *finalized* turns; early-turn content is conversational by design and rubric criteria 1–4 would always fail. Non-final turns bypass the evaluator.

- [ ] **Step 1: Add imports + constants**

Modify: `src/shape_runner.py:1-35` — mirror of Task 8 Step 1. Add `from skill_registry import BUILTIN_SKILLS` to the import block; add `DedupStore` and `PRManager` to the existing `TYPE_CHECKING` block (which already imports `Task`); and append three constants after the existing `_SHAPE_*` / `_JSON_BLOCK_RE` block:

```python
_SKILL_NAME = "shape-coherence"
_ESCALATION_LABEL_STUCK = "shape-stuck"
_ESCALATION_LABEL_HITL = "hitl-escalation"
```

- [ ] **Step 2: Inject `bind_escalation_deps` + evaluator dispatch into `run_turn`**

Modify: `src/shape_runner.py:44-137` — "after extracting content, evaluate if final, retry on RETRY, escalate on exhaustion". Three pieces of new code:

**(a)** `bind_escalation_deps(prs, dedup)` — byte-identical to the Task 8 Step 1 method (assigns `self._prs` / `self._dedup`).

**(b)** Replacement `run_turn` — structurally mirrors the Task 8 `discover` retry loop with these differences:

```python
    async def run_turn(
        self,
        task: Task,
        conversation: ShapeConversation,
        research_brief: str = "",
        learned_preferences: str = "",
    ) -> ShapeTurnResult:
        """Run a single conversation turn with post-finalize evaluation.

        Non-final turns (continue/explore) bypass the ``shape-coherence``
        evaluator — rubric criteria 1–4 only apply to a finalized
        proposal with options. When ``is_final`` is set, the runner
        evaluates the content; on RETRY it re-runs the SAME turn up to
        ``config.max_shape_attempts`` before escalating.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would run shape turn for issue #%d", task.id)
            result = ShapeTurnResult()
            result.content = "Dry-run: shape turn skipped"
            return result

        max_attempts = max(1, self._config.max_shape_attempts or 1)
        evaluator_enabled = self._config.max_shape_attempts > 0
        last_summary, last_findings = "", []
        result = ShapeTurnResult()
        for attempt in range(1, max_attempts + 1):
            result = await self._run_turn_once(
                task, conversation, research_brief, learned_preferences, attempt
            )
            if not result.is_final or not evaluator_enabled:
                return result
            passed, summary, findings = await self._evaluate_proposal(
                task, research_brief, result.content
            )
            last_summary, last_findings = summary, findings
            if passed:
                return result
            logger.warning(
                "Shape proposal rejected for #%d attempt %d/%d: %s",
                task.id, attempt, max_attempts, summary,
            )
        await self._escalate_stuck(task, last_summary, last_findings, max_attempts)
        return result
```

**(c)** `_run_turn_once(task, conversation, research_brief, learned_preferences, attempt)` — a pure factoring of the existing `run_turn` body (lines ~63–136 of the original file) renamed, with `source` tag changed from `"shape"` to `f"shape:attempt-{attempt}"` and the save-transcript filename suffixed `-attempt{attempt}`. The try/except structure, marker-extraction logic (`_SHAPE_FINALIZE`/`_SHAPE_FINALIZE_END` with `_SHAPE_CONTINUE` fallback), and transcript save are otherwise unchanged.

- [ ] **Step 3: Append `_evaluate_proposal` + `_escalate_stuck` helpers**

Modify: `src/shape_runner.py` — "append private helpers at the end of `ShapeRunner`". The helpers mirror Task 8 Step 3 byte-for-byte with these substitutions:

- Skill name: `discover-completeness` → `shape-coherence` (the module constant `_SKILL_NAME` handles this automatically).
- `prompt_builder` kwargs: `issue_body=task.body or ""` + `brief=brief or ""` → `discover_brief=discover_brief or ""` + `proposal=proposal or ""`. Add `discover_brief: str` as the second positional arg on the helper.
- `_execute` source tag: `"discover:evaluator"` → `"shape:evaluator"`.
- Escalation body opener: `"Discover-completeness evaluator rejected..."` → `"Shape-coherence evaluator rejected..."`.
- Escalation body action line: `"review the issue body, clarify the ambiguity that blocked the brief..."` → `"review the shaping output, reconcile the overlap/gap the evaluator flagged..."`.
- Dedup key: `discover_runner:{task.id}` → `shape_runner:{task.id}`.
- Title: `[discover-stuck]` → `[shape-stuck]`.

All other code — the `getattr` fall-open for unbound `_prs`/`_dedup`, the dedup.get-then-add guard, the 10-finding truncation, the log messages, the labels list `[_ESCALATION_LABEL_HITL, _ESCALATION_LABEL_STUCK]` — is identical. The Task 8 helpers are the reference.

- [ ] **Step 4: Wire `ShapePhase` to bind the escalation deps on runner init**

Find the `ShapePhase` constructor (`grep -n 'class ShapePhase' src/shape_phase.py`). It parallels `DiscoverPhase`; at the end of `__init__`, add the same binding block as in Task 8 Step 4:

```python
        if self._runner is not None:
            dedup = self._state.get_dedup_store("hitl_escalations")
            self._runner.bind_escalation_deps(self._prs, dedup)
```

Exact offset depends on `src/shape_phase.py`. Use `grep -n 'self._runner = ' src/shape_phase.py` to locate the binding point and place the four lines immediately after.

- [ ] **Step 5: Commit**

```bash
git add src/shape_runner.py src/shape_phase.py
git commit -m "feat(runner): ShapeRunner dispatches shape-coherence + retry + escalate (§4.10)

When run_turn produces a finalized proposal, the runner evaluates it
via the shape-coherence skill. Non-final conversational turns bypass
the evaluator by design. On RETRY, re-runs the same turn up to
config.max_shape_attempts (default 3); on exhaustion, files
hitl-escalation / shape-stuck with dedup key shape_runner:{issue}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Unit-test `DiscoverRunner` evaluator dispatch

**Files:**
- Create: `tests/test_discover_runner_evaluator.py`

Covers: (a) OK on first attempt returns after one invocation; (b) RETRY then OK returns on second attempt; (c) RETRY on all attempts escalates via `PRManager.create_issue`; (d) escalation uses dedup-key `discover_runner:{issue}` and skips on dedup hit; (e) evaluator-disabled (`max_discover_attempts == 0`) skips the whole loop.

- [ ] **Step 1: Write the tests**

Create `tests/test_discover_runner_evaluator.py`:

```python
"""Unit tests for DiscoverRunner evaluator dispatch + retry + escalation."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from discover_runner import DiscoverRunner
from events import EventBus
from models import DiscoverResult, Task


def _make_task(issue_id: int = 42) -> Task:
    return Task(id=issue_id, title="Vague thing", body="Maybe do something?")


def _make_runner(max_attempts, config_cls, transcripts, eval_transcripts):
    """Build a DiscoverRunner with ``_execute`` scripted [discover, eval, ...]."""
    config = config_cls()
    config.max_discover_attempts = max_attempts
    config.repo_root = Path("/tmp")
    config.dry_run = False
    runner = DiscoverRunner(config=config, event_bus=MagicMock(spec=EventBus))
    call_log: list[str] = []
    queue: list[tuple[str, str]] = []
    for d, e in zip(transcripts, eval_transcripts, strict=False):
        queue.append(("discover", d))
        queue.append(("evaluate", e))
    if len(transcripts) > len(eval_transcripts):
        queue.append(("discover", transcripts[-1]))

    async def _fake_execute(cmd, prompt, cwd, event_data, **_kw):
        source = str(event_data.get("source", ""))
        call_log.append(source)
        kind, content = queue.pop(0)
        assert (kind == "evaluate") == ("evaluator" in source)
        return content

    runner._execute = AsyncMock(side_effect=_fake_execute)  # type: ignore[assignment]
    runner._build_command = lambda _w=None: ["claude"]  # type: ignore[assignment]
    runner._build_prompt = lambda t: "p"  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    runner._extract_result = lambda tx, n: DiscoverResult(  # type: ignore[assignment]
        issue_number=n, research_brief=tx
    )
    runner._extract_raw_brief = lambda tx: tx  # type: ignore[assignment]
    return runner, call_log


@pytest.fixture
def config_cls():
    from config import HydraFlowConfig
    return HydraFlowConfig


_D_START = "DISCOVER_START\nbrief\nDISCOVER_END"
_OK = "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: fine\n"


def _retry(kw: str) -> str:
    return f"DISCOVER_COMPLETENESS_RESULT: RETRY\nSUMMARY: {kw}\n"


class TestDiscoverRunnerEvaluator:
    async def test_ok_on_first_attempt(self, config_cls):
        runner, calls = _make_runner(3, config_cls, [_D_START], [_OK])
        result = await runner.discover(_make_task())
        assert result.research_brief.startswith("DISCOVER_START")
        assert len([c for c in calls if "evaluator" in c]) == 1

    async def test_retry_then_ok(self, config_cls):
        runner, calls = _make_runner(
            3, config_cls,
            [_D_START, _D_START],
            [_retry("missing-section:intent"), _OK],
        )
        result = await runner.discover(_make_task())
        assert len([c for c in calls if "evaluator" not in c]) == 2
        assert result.research_brief  # second brief accepted

    async def test_retry_exhaustion_escalates(self, config_cls):
        runner, _ = _make_runner(
            2, config_cls,
            [_D_START, _D_START],
            [_retry("paraphrase-only"), _retry("hid-ambiguity")],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=101)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)
        await runner.discover(_make_task(42))
        prs.create_issue.assert_awaited_once()
        kw = prs.create_issue.call_args.kwargs
        assert {"hitl-escalation", "discover-stuck"} <= set(kw["labels"])
        assert "#42" in kw["title"]
        dedup.add.assert_called_once_with("discover_runner:42")

    async def test_dedup_hit_skips_escalation(self, config_cls):
        runner, _ = _make_runner(
            1, config_cls, [_D_START], [_retry("vague-criterion")]
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock()
        dedup = MagicMock()
        dedup.get = MagicMock(return_value={"discover_runner:42"})
        runner.bind_escalation_deps(prs, dedup)
        await runner.discover(_make_task(42))
        prs.create_issue.assert_not_awaited()

    async def test_max_attempts_zero_disables_evaluator(self, config_cls):
        runner, calls = _make_runner(0, config_cls, [_D_START], [])
        await runner.discover(_make_task())
        assert all("evaluator" not in c for c in calls)

    async def test_unbound_escalation_logs_only(self, config_cls, caplog):
        runner, _ = _make_runner(
            1, config_cls, [_D_START], [_retry("vague-criterion")]
        )
        with caplog.at_level(logging.WARNING, logger="hydraflow.discover"):
            await runner.discover(_make_task(99))
        assert any("PRManager not bound" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run tests**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_discover_runner_evaluator.py -v`

Expected: 6 tests pass. The tests lean on duck-typed config + stubbed `_execute`, so no subprocess or real LLM runs.

- [ ] **Step 3: Commit**

```bash
git add tests/test_discover_runner_evaluator.py
git commit -m "test(runner): DiscoverRunner evaluator dispatch + retry + escalation (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Unit-test `ShapeRunner` evaluator dispatch

Mirror of Task 10 with four mechanical substitutions and one new test:

- `DiscoverRunner` → `ShapeRunner`; `DiscoverResult` → `ShapeTurnResult`; `.discover(task)` → `.run_turn(task, ShapeConversation())`.
- `max_discover_attempts` → `max_shape_attempts`.
- `DISCOVER_COMPLETENESS_RESULT` / `DISCOVER_START`/`_END` → `SHAPE_COHERENCE_RESULT` / `SHAPE_FINALIZE`/`_FINALIZE_END`. Use this canned final transcript: `"SHAPE_FINALIZE\n## Final\n- Option A — trade-off X\n- Option B — trade-off Y\n- Defer — cost Z\nSHAPE_FINALIZE_END\n"`.
- Labels / dedup: `shape-stuck` / `shape_runner:{issue}`.
- Stub `runner._build_turn_prompt = lambda *a, **k: "turn prompt"` instead of `_build_prompt` / `_extract_result`.

**Files:**
- Create: `tests/test_shape_runner_evaluator.py`

- [ ] **Step 1: Write the tests**

Keep the `_make_runner`, `config_cls` fixture, and five tests exactly as in Task 10 with those substitutions. Additionally, prepend a **sixth test** that is unique to Shape — non-final turns must bypass the evaluator entirely:

```python
async def test_non_final_turn_bypasses_evaluator(self, config_cls):
    runner, calls = _make_runner(
        max_attempts=3,
        config_cls=config_cls,
        transcripts=["SHAPE_CONTINUE\nlet's discuss\nSHAPE_CONTINUE_END\n"],
        eval_transcripts=[],
    )
    result = await runner.run_turn(_make_task(), ShapeConversation())
    assert result.is_final is False
    assert all("evaluator" not in c for c in calls)
```

The imports and fixture are the Discover test's twins with ShapeRunner / ShapeConversation / Task substituted. Full file is mechanically derivable from `tests/test_discover_runner_evaluator.py` — the Task 10 file is the reference; keep its structure byte-for-byte except for the substitutions above, which means a single focused s&r pass produces the target file. The six-test class is named `TestShapeRunnerEvaluator`.

- [ ] **Step 2: Run tests**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_shape_runner_evaluator.py -v`

Expected: 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_shape_runner_evaluator.py
git commit -m "test(runner): ShapeRunner evaluator dispatch + retry + escalation (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Corpus extension (§4.1 `cases/`)

Add 4 Discover cases and 4 Shape cases (8 total — the spec's lower bound is 8, upper is 12; we ship 8 and let the `CorpusLearningLoop` grow the set). Each case follows the §4.1 layout exactly: `before/`, `after/`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`.

**Layout semantics for product-phase cases.** The harness synthesizes a diff from `before/` → `after/`. For product-phase cases the "diff" is synthetic: `before/` contains the original issue body (for Discover) or the original Discover brief (for Shape); `after/` contains the bad brief (for Discover) or the bad proposal (for Shape). The harness-produced diff is what the evaluator sees as the "thing under evaluation". The evaluator's prompt is skill-specific — but because the corpus harness uses `skill.prompt_builder(...)` with the standard kwargs (`issue_number=`, `issue_title=`, `diff=`, `plan_text=`), and our product-phase skills accept `**_kwargs`, the diff is ignored and the transcripts are looked up from `expected_transcript.txt`. The harness asserts the expected catcher returns RETRY with the keyword. **No harness changes required.**

`expected_transcript.txt` is the canned RETRY output — one per case, shipping deterministically so CI is not live-LLM-dependent (live mode is still gated behind `HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1` per §4.1 Task 2).

---

### Task 12: Seed 4 Discover cases

**Files (each under `tests/trust/adversarial/cases/`):**
- `discover-missing-acceptance-criteria/` — brief omits the *Acceptance criteria* section entirely.
- `discover-paraphrase-only/` — brief rewords the issue body but adds no new info.
- `discover-hid-ambiguity/` — issue body says "maybe"; brief claims zero open questions.
- `discover-vague-criterion/` — acceptance criteria are aspirations, not observables.

Each case is a directory with `before/issue.md`, `after/brief.md`, `expected_catcher.txt` (`discover-completeness`), `README.md` (one paragraph + `Keyword: <kw>`), and `expected_transcript.txt` (canned `DISCOVER_COMPLETENESS_RESULT: RETRY` block).

- [ ] **Step 1: Write case `discover-missing-acceptance-criteria`**

**`before/issue.md`:** `# Add a dark mode toggle\n\nUsers have asked for a dark mode. Add one to the settings page.\n`

**`after/brief.md`:** four sections — Intent, Affected area (names `src/ui/settings` + `src/ui/theme.ts`), Open questions (one bullet about per-device vs per-account), Known unknowns (accessibility in dark mode). **No Acceptance criteria section.**

**`README.md`:** one paragraph explaining that the rubric requires all five named sections and omitting Acceptance criteria is a structure failure; `Keyword: missing-section:acceptance-criteria`.

**`expected_transcript.txt`:**
```
DISCOVER_COMPLETENESS_RESULT: RETRY
SUMMARY: missing-section:acceptance-criteria — brief omits Acceptance criteria entirely
FINDINGS:
- missing-section:acceptance-criteria — no section named "Acceptance criteria" in the brief
```

- [ ] **Step 2: Write case `discover-paraphrase-only`**

**`before/issue.md`:** `# Speed up page loads\n\nThe homepage is slow. Make it faster.\n`

**`after/brief.md`:** five sections, all present. *Intent* is "The homepage is slow. We should make it faster." (a restatement), *Affected area* is "The homepage.", *Acceptance criteria* is a single bullet "The homepage is faster.", *Open questions* is "How fast should it be?", *Known unknowns* is "Why it is slow." — no new files, metrics, competitors, or personas introduced beyond the issue body.

**`README.md`:** one paragraph explaining that the brief only rephrases the issue — no new information added; `Keyword: paraphrase-only`. (Criteria 4 and 5 also violate, but criterion 3 fires first.)

**`expected_transcript.txt`:**
```
DISCOVER_COMPLETENESS_RESULT: RETRY
SUMMARY: paraphrase-only — brief restates the issue without new information
FINDINGS:
- paraphrase-only — no new files, metrics, competitors, or personas named
- vague-criterion — "the homepage is faster" lacks a metric
```

- [ ] **Step 3: Write cases `discover-hid-ambiguity` and `discover-vague-criterion`**

Both follow the identical layout (`before/issue.md`, `after/brief.md`, `expected_catcher.txt = discover-completeness`, `README.md` with keyword, `expected_transcript.txt`). Full content:

**`discover-hid-ambiguity/`** — issue body peppered with ambiguity markers; brief claims zero open questions. Keyword: `hid-ambiguity`.

- `before/issue.md`: `# Maybe add multi-tenant billing?\n\nNot sure if we need this, but maybe. Could be per-org or per-user. It depends on what enterprise customers ask for.\n`
- `after/brief.md`: all five sections present with substantive content; *Acceptance criteria* lists three concrete endpoints/behaviors; *Open questions* section literally says `(none)`.
- `README.md`: one paragraph naming the four ambiguity markers present in the issue (`maybe`, `not sure`, `could be`, `it depends`) vs. the zero-question Open questions section; `Keyword: hid-ambiguity`.
- `expected_transcript.txt`:
  ```
  DISCOVER_COMPLETENESS_RESULT: RETRY
  SUMMARY: hid-ambiguity — issue contains "maybe", "not sure", "could be", "it depends" but brief lists zero open questions
  FINDINGS:
  - hid-ambiguity — ambiguity markers in issue: "maybe", "not sure", "could be", "it depends"
  - hid-ambiguity — Open questions section says "(none)" despite ambiguous input
  ```

**`discover-vague-criterion/`** — acceptance criteria are aspirations, not observables. Keyword: `vague-criterion`.

- `before/issue.md`: `# Improve the search experience\n\nSearch is not great. Make it better for power users.\n`
- `after/brief.md`: all five sections present; *Acceptance criteria* bullets are `The search is faster.`, `Users are happier with search.`, `Power users love it.` — no metrics, no signals.
- `README.md`: one paragraph explaining each bullet's failure mode (no metric, no signal, no measurable surface); `Keyword: vague-criterion`.
- `expected_transcript.txt`:
  ```
  DISCOVER_COMPLETENESS_RESULT: RETRY
  SUMMARY: vague-criterion — all three acceptance bullets are aspirations, not observable outcomes
  FINDINGS:
  - vague-criterion — "the search is faster" has no metric (ms? p95?)
  - vague-criterion — "users are happier" has no signal (NPS? retention?)
  - vague-criterion — "power users love it" has no measurable surface
  ```

- [ ] **Step 5: Commit Discover cases**

```bash
git add tests/trust/adversarial/cases/discover-missing-acceptance-criteria/ \
        tests/trust/adversarial/cases/discover-paraphrase-only/ \
        tests/trust/adversarial/cases/discover-hid-ambiguity/ \
        tests/trust/adversarial/cases/discover-vague-criterion/
git commit -m "test(trust): seed 4 discover-completeness corpus cases (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Seed 4 Shape cases

**Files (each under `tests/trust/adversarial/cases/`):**
- `shape-options-overlap/` — Option A and Option B touch the same files with trivially different wording.
- `shape-missing-tradeoffs/` — Options list upsides only.
- `shape-skips-do-nothing/` — No "Defer" / "No-op" option.
- `shape-dropped-discover-question/` — Discover brief named an open question; proposal does not address it.

Each case is a directory with `before/discover_brief.md`, `after/proposal.md`, `expected_catcher.txt` (`shape-coherence`), `README.md` (one paragraph + `Keyword: <kw>`), and `expected_transcript.txt`.

- [ ] **Step 1: Write case `shape-options-overlap`**

**`before/discover_brief.md`:** `## Intent\nAdd server-side search.\n## Open questions\n- Algolia vs self-hosted Meilisearch?\n`

**`after/proposal.md`:** three options. Option A "Integrate search engine, approach 1" edits `src/search/query.py` + `src/search/index.py`, trade-off "extra latency budget". Option B "Integrate search engine, approach 2" edits the **same** two files, same trade-off. Option C "Defer", cost "search stays slow; power users churn".

**`README.md`:** one paragraph explaining that A and B overlap 100% on file scope (rubric requires <50%); `Keyword: options-overlap`.

**`expected_transcript.txt`:**
```
SHAPE_COHERENCE_RESULT: RETRY
SUMMARY: options-overlap — Option A and Option B both edit the same two files
FINDINGS:
- options-overlap — A and B both touch src/search/query.py and src/search/index.py (100% overlap)
```

- [ ] **Step 2: Write case `shape-missing-tradeoffs`**

**`before/discover_brief.md`:** `## Intent\nAdd a CLI `hf status` command.\n## Open questions\n(none)\n`

**`after/proposal.md`:** Option A "Build it now" ("this is the best option"), Option B "Extend the existing dashboard script" ("easiest path"), Option C "Defer" ("Wait until we have telemetry to show"). **Neither A nor B lists any cost, risk, or trade-off — only upsides.**

**`README.md`:** one paragraph noting A and B list only upsides; `Keyword: missing-tradeoffs`.

**`expected_transcript.txt`:**
```
SHAPE_COHERENCE_RESULT: RETRY
SUMMARY: missing-tradeoffs — Options A and B list no costs or risks
FINDINGS:
- missing-tradeoffs — Option A lists only "best option" with no downside
- missing-tradeoffs — Option B lists only "easiest path" with no downside
```

- [ ] **Step 3: Write cases `shape-skips-do-nothing` and `shape-dropped-discover-question`**

Both follow the identical layout (`before/discover_brief.md`, `after/proposal.md`, `expected_catcher.txt = shape-coherence`, `README.md` with keyword, `expected_transcript.txt` with matching SUMMARY). Full content:

**`shape-skips-do-nothing/`** — three substantive options, all with trade-offs, but no "Defer / No-op" option. Keyword: `missing-defer`.

- `before/discover_brief.md`: `## Intent\nReplace legacy logger with structured JSON logging.\n## Open questions\n(none)\n`
- `after/proposal.md`: three options titled `Option A — Adopt structlog`, `Option B — Home-grow JSON formatter`, `Option C — Partial adoption`, each with a one-line trade-off; no "Defer" / "No-op" / "status quo" option anywhere.
- `README.md`: one paragraph explaining the missing do-nothing option; `Keyword: missing-defer`.
- `expected_transcript.txt`:
  ```
  SHAPE_COHERENCE_RESULT: RETRY
  SUMMARY: missing-defer — no do-nothing option present
  FINDINGS:
  - missing-defer — proposal lists three options but omits "Defer" / "No-op" / "accept status quo"
  ```

**`shape-dropped-discover-question/`** — Discover brief asks 3 open questions; proposal addresses 2, ignores 1. Keyword: `dropped-discover-question`.

- `before/discover_brief.md`: `## Intent\nAdd multi-tenant billing.\n## Open questions\n- Per-org or per-user aggregation?\n- Stripe Connect or our own ledger?\n- Grandfather existing Pro subscribers or migrate them?\n`
- `after/proposal.md`: two options + Defer, picking per-org + Stripe Connect between them, each with a trade-off, but the grandfathering question is never mentioned.
- `README.md`: one paragraph explaining the un-addressed question; `Keyword: dropped-discover-question`.
- `expected_transcript.txt`:
  ```
  SHAPE_COHERENCE_RESULT: RETRY
  SUMMARY: dropped-discover-question — "Grandfather existing Pro subscribers or migrate them?" is not addressed
  FINDINGS:
  - dropped-discover-question — Discover question "Grandfather existing Pro subscribers or migrate them?" is not picked or punted in any option
  ```

Step retains the shape of Steps 1–2: full files committed, no placeholders — the prose above is load-bearing for the case directory content.

- [ ] **Step 5: Commit Shape cases**

```bash
git add tests/trust/adversarial/cases/shape-options-overlap/ \
        tests/trust/adversarial/cases/shape-missing-tradeoffs/ \
        tests/trust/adversarial/cases/shape-skips-do-nothing/ \
        tests/trust/adversarial/cases/shape-dropped-discover-question/
git commit -m "test(trust): seed 4 shape-coherence corpus cases (§4.10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Verify the harness accepts the new cases unchanged

The §4.1 harness (`tests/trust/adversarial/test_adversarial_corpus.py`) reads `skill_registry.BUILTIN_SKILLS` dynamically and accepts any registered name in `expected_catcher.txt`. No edits. Run the harness to confirm it picks up all 8 new cases and asserts green against the canned transcripts.

- [ ] **Step 1: Run the full corpus harness**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v -k "discover or shape"`

Expected: 8 cases selected, all pass. Specifically the harness must (a) accept `discover-completeness` and `shape-coherence` as valid `expected_catcher` names, (b) build the product-phase prompts with the standard `prompt_builder(...)` kwargs (harmless — our builders accept `**_kwargs`), (c) parse the canned transcripts and find the required keyword in `summary + findings` (case-insensitive substring).

If any case fails, inspect the mismatch — most likely the `expected_transcript.txt` keyword does not lexically appear in the rendered `SUMMARY` + `FINDINGS`. Fix the transcript, not the harness.

- [ ] **Step 2: Run the full corpus (regression check)**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`

Expected: existing §4.1 post-impl cases + the 8 new product-phase cases all green.

- [ ] **Step 3: Commit verification (no code changes — just a harness confirmation note via an empty-intent commit is not needed; skip this step if nothing changed)**

No commit. The corpus harness is unchanged; verification is captured in the CI run of the merged PR.

---

## Phase 5 — MockWorld scenario + final PR

---

### Task 15: MockWorld scenario — vague issue → Discover (bad→good) → Shape → Plan

**Files:**
- Create: `tests/scenarios/test_product_phase_scenario.py`

The scenario proves the Discover retry path end-to-end against the fake agent runner. It seeds a deliberately ambiguous issue, configures `FakeLLM` to return a bad brief on the first discover invocation and a good brief on the second, runs the pipeline, and asserts: (a) two discover attempts happened; (b) one evaluator dispatch returned RETRY; (c) the final `research_brief` is the good one; (d) no `discover-stuck` escalation issue was created.

A companion assertion checks the exhaustion path: if the scenario is configured with two bad briefs back to back and `max_discover_attempts = 2`, the escalation issue IS created.

- [ ] **Step 1: Write the scenario**

Create `tests/scenarios/test_product_phase_scenario.py`:

```python
"""§4.10 product-phase trust scenario — Discover RETRY → accept; exhaustion → escalate."""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


_AMBIGUOUS_BODY = (
    "Maybe we should add a dark mode? Not sure if per-device or per-account. "
    "It depends on what users expect."
)

_BAD_BRIEF = (
    "## Intent\nMaybe a dark mode.\n\n## Affected area\nThe app.\n\n"
    "## Open questions\n(none)\n\n## Known unknowns\nNot sure.\n"
)

_GOOD_BRIEF = (
    "## Intent\nAdd a dark mode toggle to the settings page.\n\n"
    "## Affected area\nsrc/ui/settings, src/ui/theme.ts.\n\n"
    "## Acceptance criteria\n- Toggle visible at /settings/appearance.\n"
    "- Preference persists across reload (localStorage key: theme-pref).\n"
    "- prefers-color-scheme respected when set to 'auto'.\n\n"
    "## Open questions\n- Per-device or per-account persistence?\n"
    "- Feature-flag gated for staged rollout?\n\n"
    "## Known unknowns\nAccessibility for inline charts in dark mode.\n"
)


def _retry_tx(keyword: str, attempt: int = 1) -> str:
    return (
        f"DISCOVER_COMPLETENESS_RESULT: RETRY\n"
        f"SUMMARY: {keyword} — attempt {attempt}\n"
        f"FINDINGS:\n- {keyword} — evidence\n"
    )


_OK_TX = "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: All five rubric criteria pass\n"


class TestProductPhaseScenario:
    """§4.10: Discover evaluator RETRYs a bad brief, accepts the retry."""

    async def test_bad_brief_retried_then_accepted(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(501).titled("Maybe a dark mode?").bodied(
            _AMBIGUOUS_BODY
        ).at(world)

        world.harness.config.max_discover_attempts = 3
        world._llm.discover_runner.script(
            501,
            [
                f"DISCOVER_START\n{_BAD_BRIEF}\nDISCOVER_END",
                f"DISCOVER_START\n{_GOOD_BRIEF}\nDISCOVER_END",
            ],
        )
        world._llm.discover_runner.script_evaluator(
            501,
            [_retry_tx("missing-section:acceptance-criteria"), _OK_TX],
        )

        result = await world.run_pipeline()
        outcome = result.issue(501)
        assert outcome.final_stage in {"shape", "plan", "implement", "review", "done"}
        stuck = [i for i in world.github.all_issues() if "discover-stuck" in (i.labels or [])]
        assert not stuck, f"unexpected stuck escalations: {stuck}"

    async def test_bad_brief_exhaustion_escalates(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(502).titled("Ambiguous thing").bodied(
            _AMBIGUOUS_BODY
        ).at(world)

        world.harness.config.max_discover_attempts = 2
        world._llm.discover_runner.script(
            502,
            [f"DISCOVER_START\n{_BAD_BRIEF}\nDISCOVER_END"] * 2,
        )
        world._llm.discover_runner.script_evaluator(
            502,
            [
                _retry_tx("missing-section:acceptance-criteria", 1),
                _retry_tx("missing-section:acceptance-criteria", 2),
            ],
        )
        await world.run_pipeline()

        stuck = [i for i in world.github.all_issues() if "discover-stuck" in (i.labels or [])]
        assert len(stuck) == 1
        assert "hitl-escalation" in stuck[0].labels
        assert "#502" in stuck[0].title
```

Implementer notes:

- `FakeLLM.discover_runner.script` / `.script_evaluator` may not yet exist — extend `tests/scenarios/fakes/fake_llm.py` with a scripted-queue helper for the discover path (pattern: copy `script_triage` / `script_plan` already in the file). The `script_evaluator` queue is routed by `source == "discover:evaluator"` tag on `_execute`.
- If `IssueBuilder` lacks `.labeled(...)` on this branch, use `world.add_issue(..., labels=[...])` directly.
- `result.issue(...)` is the per-issue outcome accessor (`tests/scenarios/fakes/scenario_result.py:IssueOutcome`).

- [ ] **Step 2: Run the scenario**

`cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/scenarios/test_product_phase_scenario.py -v`

Expected: 2 tests pass. If `FakeLLM` lacks a scripted-queue method for discover, first add it (short PR-style patch to `tests/scenarios/fakes/fake_llm.py`), run tests, then commit both together.

- [ ] **Step 3: Commit the scenario**

```bash
git add tests/scenarios/test_product_phase_scenario.py tests/scenarios/fakes/fake_llm.py
git commit -m "test(scenario): product-phase trust — discover RETRY → accept; exhaustion → escalate (§4.10)

MockWorld scenario covering both halves of §4.10: the happy path
(bad-brief → RETRY → good-brief → accept, no escalation) and the
sad path (two bad briefs + max_discover_attempts=2 → hitl-escalation
/ discover-stuck issue filed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: Open the PR

- [ ] **Step 1: Confirm all new tests pass**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest \
  tests/test_discover_completeness_skill.py \
  tests/test_shape_coherence_skill.py \
  tests/test_discover_runner_evaluator.py \
  tests/test_shape_runner_evaluator.py \
  tests/trust/adversarial/test_adversarial_corpus.py \
  tests/scenarios/test_product_phase_scenario.py \
  -v
```

- [ ] **Step 2: `make quality`**

Runs the standard HydraFlow quality bar: ruff + mypy + fast unit tests. Fix any warnings surfaced (Ruff is known to strip unused imports during TDD — if a new import was only used in a commit that got reordered, append the real usage before re-running).

- [ ] **Step 3: Push + PR**

```bash
git push -u origin trust-arch-hardening
gh pr create --title "trust: product-phase trust — Discover + Shape evaluators (§4.10)" --body "$(cat <<'EOF'
## Summary

Adds product-phase trust gates to HydraFlow per spec §4.10. Two new
evaluator skills (`discover-completeness`, `shape-coherence`) judge
the Discover brief and Shape proposal against the five-criterion
rubrics in the spec. Both are registered in
`skill_registry.BUILTIN_SKILLS` using the same contract the four
post-impl skills use. The runners (`DiscoverRunner`, `ShapeRunner`)
dispatch the evaluator after each output is produced, retry up to
`max_discover_attempts` / `max_shape_attempts` (new config, default
3), and file an `hitl-escalation` + `discover-stuck` / `shape-stuck`
issue on exhaustion — dedup-keyed `discover_runner:{issue}` /
`shape_runner:{issue}`. No new background loop; no Makefile or CI
changes; the §4.1 adversarial-corpus harness picks up the new skills
automatically because it reads the registry at import.

Eight new corpus cases seed the product-phase half of the corpus:
four Discover (missing-acceptance-criteria, paraphrase-only,
hid-ambiguity, vague-criterion), four Shape (options-overlap,
missing-tradeoffs, skips-do-nothing, dropped-discover-question).
MockWorld scenario proves both the happy path (bad brief → RETRY →
good brief → accept, no escalation) and the sad path (exhaustion →
escalation issue filed).

## Spec

docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md §4.10

## Test plan

- [ ] `uv run pytest tests/test_discover_completeness_skill.py` green (prompt build + all 5 RETRY keywords)
- [ ] `uv run pytest tests/test_shape_coherence_skill.py` green (same)
- [ ] `uv run pytest tests/test_discover_runner_evaluator.py` green (6 dispatch/retry/escalate tests)
- [ ] `uv run pytest tests/test_shape_runner_evaluator.py` green (6 tests, incl. non-final bypass)
- [ ] `uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -k 'discover or shape'` green (8 new cases)
- [ ] `uv run pytest tests/scenarios/test_product_phase_scenario.py` green (happy + sad)
- [ ] `make quality` green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Carried decisions

- HydraFlow commit style, `-m` single line with Co-Authored-By trailer on every commit.
- No placeholders — every code block is a drop-in file or full `Modify:` delta.
- Dedup key format `f"{worker_name}:{subject}"` where `worker_name` = `discover_runner` / `shape_runner`, `subject` = issue id; stored in the shared `hitl_escalations` set. Close-to-clear follows §3.2 — handled by whichever loop polls closed `hitl-escalation` issues.
- Telemetry is automatic: evaluator dispatch reuses `BaseRunner._execute` with `source=discover:evaluator` / `shape:evaluator`, so the §4.11 waterfall sees it as a `"kind": "skill"` action under the discover/shape phase.
- Why not reuse `agent.py:_run_skill`: that helper operates on a worktree diff and retries inline. Product-phase evaluators run on a brief/proposal and need a different retry scope (re-run discovery, not re-prompt the skill). Same `BUILTIN_SKILLS` registry; different dispatch site.
