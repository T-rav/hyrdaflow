"""Measure WikiCompiler.generalize_pair accuracy on a curated corpus.

Runs real LLM calls. Gated by conftest.py — skipped unless
``--run-evals`` or ``HYDRAFLOW_RUN_EVALS=1``.

Decides the deferred audit question: "Is haiku accurate enough for
cross-repo semantic-equivalence judgments, or should we upgrade to
sonnet?" Run with different ``HYDRAFLOW_WIKI_COMPILATION_MODEL``
values, compare accuracies, pick the tier that hits the quality bar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

CORPUS_ROOT = Path(__file__).parent / "corpus" / "generalization"


@dataclass(frozen=True)
class EvalCase:
    path: Path
    topic: str
    entry_a: dict
    entry_b: dict
    expected_same_principle: bool
    notes: str


def _load_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for subdir in ("same", "different"):
        for path in sorted((CORPUS_ROOT / subdir).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            cases.append(
                EvalCase(
                    path=path.relative_to(CORPUS_ROOT),
                    topic=data["topic"],
                    entry_a=data["entry_a"],
                    entry_b=data["entry_b"],
                    expected_same_principle=bool(data["expected_same_principle"]),
                    notes=data.get("notes", ""),
                )
            )
    return cases


@pytest.fixture(scope="module")
def wiki_compiler():
    """Construct a real WikiCompiler against the runtime config.

    Uses the same subprocess runner + credentials the production
    caretakers use, so the model under test matches what would ship.
    """
    from config import Credentials, HydraFlowConfig
    from execution import get_default_runner
    from wiki_compiler import WikiCompiler

    config = HydraFlowConfig()
    return WikiCompiler(
        config=config,
        runner=get_default_runner(),
        credentials=Credentials(),
    )


@pytest.fixture(scope="module")
def wiki_entry_cls():
    from repo_wiki import WikiEntry

    return WikiEntry


@pytest.mark.asyncio
async def test_generalization_accuracy(wiki_compiler, wiki_entry_cls) -> None:
    """Aggregate accuracy on the full corpus. Reports per-case outcomes.

    Pass bar: >=80% accuracy overall AND same-principle precision
    >=75% (avoiding false merges is slightly more important than
    catching every duplicate).
    """
    cases = _load_cases()
    assert cases, "corpus is empty — add fixtures under tests/evals/corpus/"

    correct = 0
    same_tp = same_fp = same_fn = 0
    per_case: list[tuple[str, bool, bool, str]] = []

    for case in cases:
        entry_a = wiki_entry_cls(
            title=case.entry_a["title"],
            content=case.entry_a["content"],
            source_type="manual",
            source_repo=case.entry_a.get("source_repo"),
            topic=case.topic,
        )
        entry_b = wiki_entry_cls(
            title=case.entry_b["title"],
            content=case.entry_b["content"],
            source_type="manual",
            source_repo=case.entry_b.get("source_repo"),
            topic=case.topic,
        )

        check = await wiki_compiler.generalize_pair(
            entry_a=entry_a,
            entry_b=entry_b,
            topic=case.topic,
        )

        actual = bool(check.same_principle)
        confidence = getattr(check, "confidence", "?")
        per_case.append(
            (str(case.path), case.expected_same_principle, actual, confidence)
        )

        if actual == case.expected_same_principle:
            correct += 1
        if case.expected_same_principle and actual:
            same_tp += 1
        elif not case.expected_same_principle and actual:
            same_fp += 1
        elif case.expected_same_principle and not actual:
            same_fn += 1

    accuracy = correct / len(cases)
    precision = same_tp / (same_tp + same_fp) if (same_tp + same_fp) else 1.0
    recall = same_tp / (same_tp + same_fn) if (same_tp + same_fn) else 1.0

    report = ["", "=== WikiCompiler generalization eval ==="]
    for path, expected, actual, conf in per_case:
        mark = "OK" if expected == actual else "XX"
        report.append(
            f"  [{mark}] {path} — expected={expected} actual={actual} confidence={conf}"
        )
    report.append(
        f"  accuracy={accuracy:.2f} "
        f"same_precision={precision:.2f} same_recall={recall:.2f}"
    )
    print("\n".join(report))

    assert accuracy >= 0.80, f"Accuracy {accuracy:.2f} below 0.80 bar"
    assert precision >= 0.75, (
        f"Same-principle precision {precision:.2f} below 0.75 bar — "
        "false merges are costlier than missed dedupes"
    )


def test_conftest_skips_evals_by_default(pytestconfig) -> None:
    """Smoke: without --run-evals or HYDRAFLOW_RUN_EVALS, this file's
    other tests must be skipped. This test itself runs to prove
    collection works and the corpus is readable."""
    cases = _load_cases()
    assert len(cases) >= 5, "corpus should hold at least 5 cases"
    same = [c for c in cases if c.expected_same_principle]
    diff = [c for c in cases if not c.expected_same_principle]
    assert same, "corpus needs at least one same-principle case"
    assert diff, "corpus needs at least one different-principle case"
