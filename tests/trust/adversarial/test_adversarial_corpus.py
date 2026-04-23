"""Adversarial corpus harness — iterates tests/trust/adversarial/cases/*.

Each case directory contains:
  - before/                 minimal pre-diff repo subset
  - after/                  minimal post-diff repo subset
  - expected_catcher.txt    one of the registered skills' names, or "none"
  - README.md               describes the bug + names a required keyword

The harness synthesizes a unified diff from before/ vs after/, feeds it to
every skill's registered prompt_builder, records what the corresponding
result_parser would return when given a canned "RETRY+summary" transcript
from a captured fixture at cases/<name>/expected_transcript.txt (if present)
or produced on demand from an LLM call against the prompt. The "pass"
assertion is: the expected_catcher skill's parser reports passed=False AND
the keyword from the README appears (case-insensitive substring) in the
parser's summary field.

The `none` sentinel asserts that NO skill reports passed=False on the
case — i.e. a deliberately benign diff must not trip any catcher.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
REPO_ROOT = HERE.parent.parent.parent
SRC = REPO_ROOT / "src"

sys.path.insert(0, str(SRC))

from skill_registry import BUILTIN_SKILLS, AgentSkill  # noqa: E402

# Map skill.name -> AgentSkill, resolved at module import from the live
# registry. If a new post-impl skill is added to BUILTIN_SKILLS, the
# corpus automatically accepts expected_catcher.txt values naming it.
_SKILLS_BY_NAME: dict[str, AgentSkill] = {s.name: s for s in BUILTIN_SKILLS}
_VALID_CATCHERS: frozenset[str] = frozenset({*_SKILLS_BY_NAME.keys(), "none"})


def _discover_cases() -> list[Path]:
    if not CASES_DIR.is_dir():
        return []
    return sorted(
        p for p in CASES_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def _read_case_files(root: Path) -> dict[str, str]:
    """Return {relative_path: file_text} under *root*."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            try:
                out[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                out[rel] = ""
    return out


def _synthesize_diff(before_dir: Path, after_dir: Path) -> str:
    """Build a unified diff from before/ -> after/ with git-style headers."""
    before = _read_case_files(before_dir)
    after = _read_case_files(after_dir)
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        b = before.get(rel, "")
        a = after.get(rel, "")
        if b == a:
            continue
        diff = difflib.unified_diff(
            b.splitlines(keepends=True),
            a.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
        chunks.append(f"diff --git a/{rel} b/{rel}\n")
        chunks.extend(diff)
    return "".join(chunks)


def _load_transcript(case_dir: Path, prompt: str) -> str:
    """Return the canned LLM transcript for *case_dir*, or invoke live claude."""
    fixture = case_dir / "expected_transcript.txt"
    if fixture.exists():
        return fixture.read_text(encoding="utf-8")
    if os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE") != "1":
        pytest.skip(
            f"No expected_transcript.txt for {case_dir.name}; set "
            "HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1 to invoke the real claude CLI."
        )
    try:
        result = subprocess.run(  # noqa: S603
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as exc:
        pytest.fail(f"Live claude invocation failed for {case_dir.name}: {exc}")
    return result.stdout


def _read_keyword(readme_path: Path) -> str:
    """Extract the required keyword from a case README.

    Convention: one line of the README reads `Keyword: <word-or-phrase>`.
    The match is case-insensitive substring against the parser's summary.
    """
    text = readme_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().lower().startswith("keyword:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"README.md {readme_path} missing 'Keyword:' line")


def _read_expected_catcher(case_dir: Path) -> str:
    catcher = (case_dir / "expected_catcher.txt").read_text(encoding="utf-8").strip()
    if catcher not in _VALID_CATCHERS:
        raise AssertionError(
            f"{case_dir.name}/expected_catcher.txt = {catcher!r}; must be one of "
            f"{sorted(_VALID_CATCHERS)} (from live skill_registry.BUILTIN_SKILLS)"
        )
    return catcher


def _load_plan_text(case_dir: Path) -> str:
    """Return plan_text for plan-compliance / scope-check cases, or empty."""
    plan = case_dir / "plan.md"
    return plan.read_text(encoding="utf-8") if plan.exists() else ""


@pytest.mark.parametrize(
    "case_dir",
    _discover_cases(),
    ids=lambda p: p.name,
)
def test_case(case_dir: Path) -> None:
    """For each case, assert the expected catcher flags it."""
    before_dir = case_dir / "before"
    after_dir = case_dir / "after"
    assert before_dir.is_dir(), f"{case_dir.name}: missing before/"
    assert after_dir.is_dir(), f"{case_dir.name}: missing after/"

    diff = _synthesize_diff(before_dir, after_dir)
    assert diff.strip(), f"{case_dir.name}: before/ and after/ produced empty diff"

    catcher = _read_expected_catcher(case_dir)
    plan_text = _load_plan_text(case_dir)

    # For every skill, build its prompt and parse the transcript.
    results: dict[str, tuple[bool, str, list[str]]] = {}
    for skill in BUILTIN_SKILLS:
        prompt = skill.prompt_builder(
            issue_number=0,
            issue_title=f"adversarial-corpus::{case_dir.name}",
            diff=diff,
            plan_text=plan_text,
        )
        transcript = _load_transcript(case_dir, prompt)
        results[skill.name] = skill.result_parser(transcript)

    if catcher == "none":
        failing = [name for name, (passed, _, _) in results.items() if not passed]
        assert not failing, (
            f"{case_dir.name}: sentinel 'none' case was flagged by {failing} "
            "but should pass every skill"
        )
        return

    passed, summary, findings = results[catcher]
    assert not passed, (
        f"{case_dir.name}: expected_catcher '{catcher}' returned OK; "
        f"summary={summary!r} findings={findings!r}"
    )

    keyword = _read_keyword(case_dir / "README.md")
    haystack = (summary + "\n" + "\n".join(findings)).lower()
    assert keyword.lower() in haystack, (
        f"{case_dir.name}: expected_catcher '{catcher}' returned RETRY but "
        f"summary/findings did not contain required keyword {keyword!r}. "
        f"summary={summary!r}, findings={findings!r}"
    )
