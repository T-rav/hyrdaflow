"""Contract test fixtures — snapshot assertion helper.

Provides ``assert_screenshot``, a lightweight equivalent of Playwright JS's
``expect(page).toHaveScreenshot()``.

Usage::

    # First run — generate baselines:
    pytest ... --update-snapshots

    # Subsequent runs — compare against baselines:
    pytest ...

Snapshots are stored under::

    tests/scenarios/browser/contract/__snapshots__/<name>
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.async_api import Page


# ---------------------------------------------------------------------------
# Snapshot directory
# ---------------------------------------------------------------------------

_SNAPSHOTS_DIR = Path(__file__).parent / "__snapshots__"


def pytest_addoption(parser: pytest.Parser) -> None:  # type: ignore[misc]
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Overwrite existing snapshot baselines with the current render.",
    )


# ---------------------------------------------------------------------------
# Minimal PNG pixel-diff (stdlib only — no Pillow / numpy required)
# ---------------------------------------------------------------------------


def _decode_png_pixels(data: bytes) -> tuple[int, int, list[int]]:
    """Return (width, height, flat_rgba_pixel_list) for a PNG bytestring."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG")

    ihdr_data: bytes = b""
    idat_parts: list[bytes] = []
    pos = 8
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4 : pos + 8]
        cdata = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            ihdr_data = cdata
        elif ctype == b"IDAT":
            # Multiple IDAT chunks must be concatenated before decompressing.
            idat_parts.append(cdata)
        pos += 12 + length

    if not ihdr_data:
        raise ValueError("Missing IHDR chunk")
    if not idat_parts:
        raise ValueError("Missing IDAT chunk")

    ihdr = ihdr_data
    width, height = struct.unpack_from(">II", ihdr)
    bit_depth, color_type = ihdr[8], ihdr[9]

    if bit_depth != 8:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    # colour_type -> bytes per pixel
    bpp_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in bpp_map:
        raise ValueError(f"Unsupported colour type: {color_type}")
    bpp = bpp_map[color_type]

    raw = zlib.decompress(b"".join(idat_parts))
    stride = width * bpp

    pixels: list[int] = []
    prev_row = bytes(stride)
    offset = 0
    for _ in range(height):
        ftype = raw[offset]
        offset += 1
        row_raw = bytearray(raw[offset : offset + stride])
        offset += stride

        if ftype == 0:  # None
            row = row_raw
        elif ftype == 1:  # Sub
            for i in range(bpp, stride):
                row_raw[i] = (row_raw[i] + row_raw[i - bpp]) & 0xFF
            row = row_raw
        elif ftype == 2:  # Up
            row = bytearray(
                (a + b) & 0xFF for a, b in zip(row_raw, prev_row, strict=False)
            )
        elif ftype == 3:  # Average
            row = bytearray(row_raw)
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                row[i] = (row_raw[i] + (left + up) // 2) & 0xFF
        elif ftype == 4:  # Paeth
            row = bytearray(row_raw)
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev_row[i]
                c = prev_row[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (row_raw[i] + pr) & 0xFF
        else:
            raise ValueError(f"Unknown filter type: {ftype}")

        # Expand to RGBA
        if color_type == 6:  # RGBA
            pixels.extend(row)
        elif color_type == 2:  # RGB
            for i in range(0, stride, 3):
                pixels.extend([row[i], row[i + 1], row[i + 2], 255])
        elif color_type == 0:  # Greyscale
            for v in row:
                pixels.extend([v, v, v, 255])
        elif color_type == 4:  # Greyscale+Alpha
            for i in range(0, stride, 2):
                pixels.extend([row[i], row[i], row[i], row[i + 1]])
        else:
            # Indexed — treat as opaque grey; good enough for diff counting
            for v in row:
                pixels.extend([v, v, v, 255])

        prev_row = bytes(row)

    return width, height, pixels


def _count_diff_pixels(baseline: bytes, actual: bytes) -> int:
    """Return number of pixels that differ by any amount."""
    try:
        w1, h1, pix1 = _decode_png_pixels(baseline)
        w2, h2, pix2 = _decode_png_pixels(actual)
    except Exception:
        # If decoding fails, treat as fully different (max sentinel)
        return 999_999

    if w1 != w2 or h1 != h2:
        return w1 * h1  # size mismatch — all pixels "differ"

    diff = 0
    for i in range(0, len(pix1), 4):
        if pix1[i : i + 4] != pix2[i : i + 4]:
            diff += 1
    return diff


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def assert_screenshot(request: pytest.FixtureRequest) -> _AssertScreenshotFn:
    """Return an async callable ``assert_screenshot(page, name, max_diff_pixels=60)``."""
    update = request.config.getoption("--update-snapshots", default=False)

    async def _assert(page: Page, name: str, max_diff_pixels: int = 60) -> None:
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        snap_path = _SNAPSHOTS_DIR / name

        # Always wait for paint to settle
        await page.wait_for_load_state("networkidle")

        actual_bytes: bytes = await page.screenshot(full_page=False)

        if update or not snap_path.exists():
            snap_path.write_bytes(actual_bytes)
            return  # Baseline written — test vacuously passes

        baseline_bytes = snap_path.read_bytes()
        diff = _count_diff_pixels(baseline_bytes, actual_bytes)
        assert diff <= max_diff_pixels, (
            f"Screenshot '{name}' differs by {diff} pixels "
            f"(tolerance: {max_diff_pixels}). "
            f"Run with --update-snapshots to regenerate."
        )

    return _assert  # type: ignore[return-value]


# Type alias for IDE autocomplete (not runtime-enforced)
from typing import Protocol


class _AssertScreenshotFn(Protocol):
    async def __call__(
        self, page: Page, name: str, max_diff_pixels: int = 60
    ) -> None: ...
