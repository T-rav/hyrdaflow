"""Visual regression diff engine.

Compares baseline and candidate screenshot directories, computing
per-screen pixel diffs and emitting a structured ``VisualReport``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.models import (
    FailureCategory,
    ScreenResult,
    ScreenVerdict,
    VisualReport,
)

logger = logging.getLogger(__name__)

# PNG header bytes (first 8 bytes of any valid PNG).
_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _load_image_bytes(path: Path) -> tuple[bytes, int, int] | None:
    """Read a PNG file and return (raw_pixels, width, height).

    Uses only the stdlib: reads the IHDR chunk for dimensions and
    returns the raw file bytes for size accounting.  Pixel comparison
    is done byte-by-byte on the raw file content — this is intentionally
    simple and avoids requiring Pillow or any image library.

    Returns ``None`` if the file cannot be read or is not a valid PNG.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data.startswith(_PNG_HEADER):
        return None

    # IHDR chunk starts at byte 8: 4-byte length, 4-byte type, then data.
    # Width is bytes 16–19, height is bytes 20–23 (big-endian uint32).
    if len(data) < 24:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return data, width, height


def _count_diff_bytes(a: bytes, b: bytes) -> int:
    """Count the number of byte positions that differ between *a* and *b*.

    Operates on raw file bytes — not decoded pixel data — so the result
    is a proxy for visual difference rather than exact pixel-count.
    """
    diff = sum(x != y for x, y in zip(a, b, strict=False))
    # Any excess bytes in the longer file count as differences.
    diff += abs(len(a) - len(b))
    return diff


def compare_screen(
    screen_name: str,
    baseline_path: Path,
    candidate_path: Path,
    *,
    diff_threshold: float,
    warn_threshold: float,
    budget_bytes: int,
) -> ScreenResult:
    """Compare a single screen's baseline and candidate images.

    Returns a :class:`ScreenResult` with verdict, diff ratio, and timing.
    """
    t0 = time.monotonic()

    # --- Load baseline ---
    baseline_data = _load_image_bytes(baseline_path)
    if baseline_data is None:
        elapsed = time.monotonic() - t0
        return ScreenResult(
            screen_name=screen_name,
            verdict=ScreenVerdict.ERROR,
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
            runtime_seconds=round(elapsed, 4),
            error_message=f"Cannot load baseline: {baseline_path}",
        )

    # --- Load candidate ---
    candidate_data = _load_image_bytes(candidate_path)
    if candidate_data is None:
        elapsed = time.monotonic() - t0
        return ScreenResult(
            screen_name=screen_name,
            verdict=ScreenVerdict.ERROR,
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
            runtime_seconds=round(elapsed, 4),
            error_message=f"Cannot load candidate: {candidate_path}",
        )

    b_bytes, b_w, b_h = baseline_data
    c_bytes, c_w, c_h = candidate_data

    # --- Budget check ---
    artifact_total = len(b_bytes) + len(c_bytes)
    if artifact_total > budget_bytes:
        elapsed = time.monotonic() - t0
        return ScreenResult(
            screen_name=screen_name,
            verdict=ScreenVerdict.ERROR,
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
            artifact_bytes=artifact_total,
            runtime_seconds=round(elapsed, 4),
            error_message=(
                f"Artifact size {artifact_total} exceeds budget {budget_bytes}"
            ),
        )

    # --- Size mismatch ---
    if (b_w, b_h) != (c_w, c_h):
        elapsed = time.monotonic() - t0
        return ScreenResult(
            screen_name=screen_name,
            verdict=ScreenVerdict.FAIL,
            diff_ratio=1.0,
            changed_pixels=b_w * b_h,
            total_pixels=b_w * b_h,
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
            artifact_bytes=artifact_total,
            runtime_seconds=round(elapsed, 4),
            error_message=(
                f"Size mismatch: baseline {b_w}x{b_h} vs candidate {c_w}x{c_h}"
            ),
        )

    # --- Byte-level diff ---
    total_bytes = max(len(b_bytes), len(c_bytes), 1)
    changed = _count_diff_bytes(b_bytes, c_bytes)
    diff_ratio = changed / total_bytes

    total_pixels = b_w * b_h
    # Approximate changed-pixel count scaled from byte diff.
    changed_pixels = round(diff_ratio * total_pixels)

    # --- Verdict ---
    if diff_ratio >= diff_threshold:
        verdict = ScreenVerdict.FAIL
    elif diff_ratio >= warn_threshold:
        verdict = ScreenVerdict.WARN
    else:
        verdict = ScreenVerdict.PASS

    elapsed = time.monotonic() - t0
    return ScreenResult(
        screen_name=screen_name,
        verdict=verdict,
        diff_ratio=round(diff_ratio, 6),
        changed_pixels=changed_pixels,
        total_pixels=total_pixels,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
        artifact_bytes=artifact_total,
        runtime_seconds=round(elapsed, 4),
    )


def run_visual_diff(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    diff_threshold: float = 0.01,
    warn_threshold: float = 0.005,
    max_screens: int = 20,
    budget_bytes: int = 5_000_000,
    retry_count: int = 0,
) -> VisualReport:
    """Run visual diff across all PNG screens in *baseline_dir*.

    Iterates over ``*.png`` files in *baseline_dir*, finds the
    corresponding file in *candidate_dir*, and produces a
    :class:`VisualReport` with per-screen and aggregate verdicts.
    """
    from datetime import UTC, datetime

    t0 = time.monotonic()
    screens: list[ScreenResult] = []
    failure_category = FailureCategory.NONE

    baseline_pngs = sorted(baseline_dir.glob("*.png"))[:max_screens]

    if not baseline_pngs:
        failure_category = FailureCategory.MISSING_BASELINE

    for png in baseline_pngs:
        candidate_path = candidate_dir / png.name
        result = compare_screen(
            screen_name=png.stem,
            baseline_path=png,
            candidate_path=candidate_path,
            diff_threshold=diff_threshold,
            warn_threshold=warn_threshold,
            budget_bytes=budget_bytes,
        )
        screens.append(result)

    # --- Aggregate ---
    passed = sum(1 for s in screens if s.verdict == ScreenVerdict.PASS)
    warned = sum(1 for s in screens if s.verdict == ScreenVerdict.WARN)
    failed = sum(1 for s in screens if s.verdict == ScreenVerdict.FAIL)
    errored = sum(1 for s in screens if s.verdict == ScreenVerdict.ERROR)

    if errored > 0:
        aggregate = ScreenVerdict.ERROR
        # Classify the first error.
        first_err = next(s for s in screens if s.verdict == ScreenVerdict.ERROR)
        if "budget" in first_err.error_message.lower():
            failure_category = FailureCategory.BUDGET_EXCEEDED
        elif "size mismatch" in first_err.error_message.lower():
            failure_category = FailureCategory.SIZE_MISMATCH
        elif "baseline" in first_err.error_message.lower():
            failure_category = FailureCategory.MISSING_BASELINE
        else:
            failure_category = FailureCategory.IMAGE_LOAD_ERROR
    elif failed > 0:
        aggregate = ScreenVerdict.FAIL
        failure_category = FailureCategory.THRESHOLD_EXCEEDED
    elif failure_category == FailureCategory.MISSING_BASELINE:
        # No screens processed because baseline dir is empty — treat as ERROR
        # so callers cannot silently pass with a misconfigured baseline.
        aggregate = ScreenVerdict.ERROR
    elif warned > 0:
        aggregate = ScreenVerdict.WARN
    else:
        aggregate = ScreenVerdict.PASS

    total_runtime = round(time.monotonic() - t0, 4)
    total_artifact = sum(s.artifact_bytes for s in screens)

    return VisualReport(
        aggregate_verdict=aggregate,
        screens=screens,
        total_screens=len(screens),
        passed=passed,
        warned=warned,
        failed=failed,
        errored=errored,
        diff_threshold=diff_threshold,
        warn_threshold=warn_threshold,
        total_runtime_seconds=total_runtime,
        retry_count=retry_count,
        total_artifact_bytes=total_artifact,
        failure_category=failure_category,
        generated_at=datetime.now(UTC).isoformat(),
    )


def write_visual_report(report: VisualReport, output_path: Path) -> Path:
    """Serialize *report* as JSON to *output_path* and return the path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Visual report written to %s", output_path)
    return output_path
