"""Tests for GlobalMemoryStore — global digest, overrides, promotion, override detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from global_memory import GlobalMemoryStore  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> GlobalMemoryStore:
    global_dir = tmp_path / "global_memory"
    global_dir.mkdir(parents=True, exist_ok=True)
    return GlobalMemoryStore(global_dir)


def _write_digest(tmp_path: Path, content: str) -> None:
    (tmp_path / "global_memory" / "digest.md").write_text(content, encoding="utf-8")


def _write_project_items(
    memory_dir: Path,
    items: list[tuple[int, str, float]],
) -> None:
    """Write item files and item_scores.json into a project memory directory."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    items_dir = memory_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    scores: dict[str, dict] = {}
    for item_id, text, score in items:
        (items_dir / f"{item_id}.md").write_text(text, encoding="utf-8")
        scores[str(item_id)] = {
            "score": score,
            "appearances": 6,
            "trail": [],
            "condensed_summary": "",
        }
    (memory_dir / "item_scores.json").write_text(
        json.dumps(scores, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# TestLoadGlobalDigest
# ---------------------------------------------------------------------------


# TestLoadGlobalDigest and TestGetCombinedDigest removed — digest.md eliminated,
# Hindsight is the exclusive memory store.


# ---------------------------------------------------------------------------
# TestOverrideRecording
# ---------------------------------------------------------------------------


class TestOverrideRecording:
    def test_record_creates_file(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        overrides_path = tmp_path / "proj_memory" / "global_overrides.json"
        store.record_override_at(overrides_path, "global-15", "We use Prisma")
        assert overrides_path.exists()

    def test_record_stores_reason(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        overrides_path = tmp_path / "proj_memory" / "global_overrides.json"
        store.record_override_at(overrides_path, "global-15", "We use Prisma")
        data = json.loads(overrides_path.read_text())
        assert "global-15" in data["overrides"]
        assert data["overrides"]["global-15"]["reason"] == "We use Prisma"

    def test_record_stores_created_at(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        overrides_path = tmp_path / "proj_memory" / "global_overrides.json"
        store.record_override_at(overrides_path, "global-15", "Reason")
        data = json.loads(overrides_path.read_text())
        assert data["overrides"]["global-15"]["created_at"]

    def test_multiple_overrides_accumulate(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        overrides_path = tmp_path / "proj_memory" / "global_overrides.json"
        store.record_override_at(overrides_path, "global-1", "Reason A")
        store.record_override_at(overrides_path, "global-2", "Reason B")
        ids = store.load_overrides_at(overrides_path)
        assert ids == {"global-1", "global-2"}

    def test_load_overrides_returns_empty_when_file_missing(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        ids = store.load_overrides_at(tmp_path / "nonexistent.json")
        assert ids == set()

    def test_load_overrides_returns_empty_on_corrupt_file(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        corrupt = tmp_path / "bad.json"
        corrupt.write_text("not json!!!", encoding="utf-8")
        assert store.load_overrides_at(corrupt) == set()

    def test_overridden_ids_returned_by_get_overrides(self, tmp_path: Path) -> None:
        # When global_memory dir parent + slug/memory path lines up
        global_dir = tmp_path / "global_memory"
        global_dir.mkdir(parents=True, exist_ok=True)
        store = GlobalMemoryStore(global_dir)
        slug = "myrepo"
        # Manually write the expected file
        override_dir = global_dir.parent / slug / "memory"
        override_dir.mkdir(parents=True, exist_ok=True)
        overrides_file = override_dir / "global_overrides.json"
        overrides_file.write_text(
            json.dumps(
                {
                    "overrides": {
                        "global-42": {
                            "reason": "test",
                            "created_at": "2024-01-01T00:00:00",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        ids = store.get_overrides(slug)
        assert "global-42" in ids


# ---------------------------------------------------------------------------
# TestFindPromotionCandidates
# ---------------------------------------------------------------------------

_LEARNING_A = "Always configure database connection pooling for production deployments"
_LEARNING_B = "Always configure database connection pooling production performance tune"
_LEARNING_C = (
    "Always configure database connection pooling production environment setup"
)


class TestFindPromotionCandidates:
    def test_returns_empty_when_fewer_than_3_projects(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        p1 = tmp_path / "p1" / "memory"
        p2 = tmp_path / "p2" / "memory"
        _write_project_items(p1, [(1, _LEARNING_A, 0.8)])
        _write_project_items(p2, [(1, _LEARNING_B, 0.8)])
        candidates = store.find_promotion_candidates({"p1": p1, "p2": p2})
        assert candidates == []

    def test_returns_empty_when_scores_below_threshold(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        stores: dict[str, Path] = {}
        for i in range(3):
            mem = tmp_path / f"p{i}" / "memory"
            _write_project_items(mem, [(1, _LEARNING_A, 0.3)])  # below threshold
            stores[f"p{i}"] = mem
        candidates = store.find_promotion_candidates(stores)
        assert candidates == []

    def test_detects_matching_items_across_3_projects(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        learnings = [_LEARNING_A, _LEARNING_B, _LEARNING_C]
        stores: dict[str, Path] = {}
        for i, text in enumerate(learnings):
            mem = tmp_path / f"p{i}" / "memory"
            _write_project_items(mem, [(10 + i, text, 0.8)])
            stores[f"p{i}"] = mem
        candidates = store.find_promotion_candidates(stores)
        assert len(candidates) >= 1
        c = candidates[0]
        assert len(c["project_slugs"]) >= 3
        assert c["avg_score"] >= 0.6

    def test_candidate_has_expected_keys(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        learnings = [_LEARNING_A, _LEARNING_B, _LEARNING_C]
        stores: dict[str, Path] = {}
        for i, text in enumerate(learnings):
            mem = tmp_path / f"p{i}" / "memory"
            _write_project_items(mem, [(i + 1, text, 0.9)])
            stores[f"p{i}"] = mem
        candidates = store.find_promotion_candidates(stores)
        assert candidates
        c = candidates[0]
        assert "representative_text" in c
        assert "project_slugs" in c
        assert "avg_score" in c
        assert "item_ids" in c

    def test_unrelated_items_not_promoted(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        unrelated = [
            "Always configure database connection pooling",
            "Use type hints everywhere for better IDE support",
            "Write tests before implementation for better coverage",
        ]
        stores: dict[str, Path] = {}
        for i, text in enumerate(unrelated):
            mem = tmp_path / f"p{i}" / "memory"
            _write_project_items(mem, [(i + 1, text, 0.9)])
            stores[f"p{i}"] = mem
        candidates = store.find_promotion_candidates(stores)
        assert candidates == []

    def test_returns_empty_when_stores_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        candidates = store.find_promotion_candidates({})
        assert candidates == []

    def test_returns_empty_when_project_items_dir_missing(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        stores: dict[str, Path] = {
            "p1": tmp_path / "missing1",
            "p2": tmp_path / "missing2",
            "p3": tmp_path / "missing3",
        }
        candidates = store.find_promotion_candidates(stores)
        assert candidates == []


# ---------------------------------------------------------------------------
# TestDetectOverrideCandidates
# ---------------------------------------------------------------------------


class TestDetectOverrideCandidates:
    def _write_global_scores(self, tmp_path: Path, scores: dict[str, dict]) -> None:
        global_dir = tmp_path / "global_memory"
        global_dir.mkdir(parents=True, exist_ok=True)
        (global_dir / "item_scores.json").write_text(
            json.dumps(scores, indent=2), encoding="utf-8"
        )

    def test_returns_empty_when_no_global_scores(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.detect_override_candidates({})
        assert result == []

    def test_returns_empty_when_global_score_below_threshold(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        self._write_global_scores(
            tmp_path, {"global-1": {"score": 0.4, "appearances": 10}}
        )
        mem = tmp_path / "p1" / "memory"
        _write_project_items(mem, [(1, "some text", 0.1)])
        result = store.detect_override_candidates({"p1": mem})
        assert result == []

    def test_detects_outlier_project(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # Global item "global-1" scores high globally
        self._write_global_scores(
            tmp_path, {"global-1": {"score": 0.8, "appearances": 20}}
        )
        # One project has this item scoring poorly with enough appearances
        proj_mem = tmp_path / "outlier" / "memory"
        proj_mem.mkdir(parents=True, exist_ok=True)
        scores = {
            "global-1": {
                "score": 0.2,
                "appearances": 8,
                "trail": [],
                "condensed_summary": "",
            }
        }
        (proj_mem / "item_scores.json").write_text(
            json.dumps(scores, indent=2), encoding="utf-8"
        )
        result = store.detect_override_candidates({"outlier": proj_mem})
        assert len(result) == 1
        assert result[0]["global_item_id"] == "global-1"
        assert result[0]["global_avg_score"] == pytest.approx(0.8)
        assert len(result[0]["outlier_projects"]) == 1
        assert result[0]["outlier_projects"][0]["slug"] == "outlier"

    def test_does_not_flag_project_with_few_appearances(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._write_global_scores(
            tmp_path, {"global-2": {"score": 0.9, "appearances": 30}}
        )
        proj_mem = tmp_path / "newproj" / "memory"
        proj_mem.mkdir(parents=True, exist_ok=True)
        # Only 3 appearances — below threshold of 5
        scores = {
            "global-2": {
                "score": 0.1,
                "appearances": 3,
                "trail": [],
                "condensed_summary": "",
            }
        }
        (proj_mem / "item_scores.json").write_text(
            json.dumps(scores, indent=2), encoding="utf-8"
        )
        result = store.detect_override_candidates({"newproj": proj_mem})
        assert result == []

    def test_does_not_flag_project_with_adequate_score(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._write_global_scores(
            tmp_path, {"global-3": {"score": 0.8, "appearances": 20}}
        )
        proj_mem = tmp_path / "okproj" / "memory"
        proj_mem.mkdir(parents=True, exist_ok=True)
        # Score is above the bad threshold (0.3)
        scores = {
            "global-3": {
                "score": 0.5,
                "appearances": 10,
                "trail": [],
                "condensed_summary": "",
            }
        }
        (proj_mem / "item_scores.json").write_text(
            json.dumps(scores, indent=2), encoding="utf-8"
        )
        result = store.detect_override_candidates({"okproj": proj_mem})
        assert result == []

    def test_result_has_expected_keys(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._write_global_scores(
            tmp_path, {"global-5": {"score": 0.75, "appearances": 15}}
        )
        proj_mem = tmp_path / "badproj" / "memory"
        proj_mem.mkdir(parents=True, exist_ok=True)
        scores = {
            "global-5": {
                "score": 0.15,
                "appearances": 7,
                "trail": [],
                "condensed_summary": "",
            }
        }
        (proj_mem / "item_scores.json").write_text(
            json.dumps(scores, indent=2), encoding="utf-8"
        )
        result = store.detect_override_candidates({"badproj": proj_mem})
        assert result
        r = result[0]
        assert "global_item_id" in r
        assert "global_avg_score" in r
        assert "outlier_projects" in r
        outlier = r["outlier_projects"][0]
        assert "slug" in outlier
        assert "score" in outlier
        assert "appearances" in outlier
