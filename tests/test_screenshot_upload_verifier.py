"""Tests for the screenshot upload verifier."""

from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from screenshot_upload_verifier import (
    _MAX_PNG_SIZE,
    _PNG_MAGIC,
    ScreenshotVerificationError,
    verify_base64_png,
    verify_png_bytes,
)
from tests.helpers import make_minimal_png


class TestVerifyPngBytes:
    """Tests for verify_png_bytes."""

    def test_valid_minimal_png(self) -> None:
        """A minimal valid PNG passes verification."""
        data = make_minimal_png(800, 600)
        w, h = verify_png_bytes(data)
        assert w == 800
        assert h == 600

    def test_valid_1x1_png(self) -> None:
        """A 1x1 PNG passes verification."""
        data = make_minimal_png(1, 1)
        w, h = verify_png_bytes(data)
        assert w == 1
        assert h == 1

    def test_empty_payload_raises(self) -> None:
        """An empty payload is rejected."""
        with pytest.raises(ScreenshotVerificationError, match="too small"):
            verify_png_bytes(b"")

    def test_short_payload_raises(self) -> None:
        """A payload shorter than the PNG magic is rejected."""
        with pytest.raises(ScreenshotVerificationError, match="too small"):
            verify_png_bytes(b"\x89PN")

    def test_wrong_magic_raises(self) -> None:
        """A payload with incorrect magic bytes is rejected."""
        data = b"\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 50
        with pytest.raises(ScreenshotVerificationError, match="magic bytes"):
            verify_png_bytes(data)

    def test_jpeg_magic_raises(self) -> None:
        """A JPEG file is rejected with a clear error."""
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        with pytest.raises(ScreenshotVerificationError, match="magic bytes"):
            verify_png_bytes(jpeg_header)

    def test_truncated_after_magic_raises(self) -> None:
        """A payload with valid magic but truncated body is rejected."""
        data = _PNG_MAGIC + b"\x00" * 10  # Too short for IHDR
        with pytest.raises(ScreenshotVerificationError, match="truncated"):
            verify_png_bytes(data)

    def test_missing_ihdr_chunk_raises(self) -> None:
        """A PNG without IHDR as the first chunk is rejected."""
        # Build a payload with valid magic but wrong chunk type
        sig = _PNG_MAGIC
        fake_chunk = struct.pack(">I", 13) + b"tEXt" + b"\x00" * 13 + b"\x00" * 4
        iend_chunk = struct.pack(">I", 0) + b"IEND" + b"\x00" * 4
        data = sig + fake_chunk + iend_chunk
        with pytest.raises(ScreenshotVerificationError, match="not IHDR"):
            verify_png_bytes(data)

    def test_zero_width_raises(self) -> None:
        """A PNG with zero width is rejected."""
        data = make_minimal_png(0, 100)
        with pytest.raises(ScreenshotVerificationError, match="Invalid PNG dimensions"):
            verify_png_bytes(data)

    def test_zero_height_raises(self) -> None:
        """A PNG with zero height is rejected."""
        data = make_minimal_png(100, 0)
        with pytest.raises(ScreenshotVerificationError, match="Invalid PNG dimensions"):
            verify_png_bytes(data)

    def test_zero_width_and_height_raises(self) -> None:
        """A PNG with zero dimensions is rejected."""
        data = make_minimal_png(0, 0)
        with pytest.raises(ScreenshotVerificationError, match="Invalid PNG dimensions"):
            verify_png_bytes(data)

    def test_oversized_payload_raises(self) -> None:
        """A payload exceeding the size limit is rejected."""
        data = make_minimal_png(1, 1) + b"\x00" * (_MAX_PNG_SIZE + 1)
        with pytest.raises(ScreenshotVerificationError, match="exceeds size limit"):
            verify_png_bytes(data)

    def test_large_valid_dimensions(self) -> None:
        """A PNG with large but valid dimensions passes."""
        data = make_minimal_png(3840, 2160)
        w, h = verify_png_bytes(data)
        assert w == 3840
        assert h == 2160

    def test_error_is_value_error_subclass(self) -> None:
        """ScreenshotVerificationError is a ValueError subclass."""
        assert issubclass(ScreenshotVerificationError, ValueError)


class TestVerifyBase64Png:
    """Tests for verify_base64_png."""

    def test_valid_base64_png(self) -> None:
        """A valid base64-encoded PNG passes verification."""
        data = make_minimal_png(640, 480)
        b64 = base64.b64encode(data).decode()
        w, h = verify_base64_png(b64)
        assert w == 640
        assert h == 480

    def test_data_uri_prefix_stripped(self) -> None:
        """A data: URI prefix is stripped before verification."""
        data = make_minimal_png(320, 240)
        b64 = base64.b64encode(data).decode()
        w, h = verify_base64_png(f"data:image/png;base64,{b64}")
        assert w == 320
        assert h == 240

    def test_whitespace_in_base64_handled(self) -> None:
        """Embedded whitespace in base64 is stripped."""
        data = make_minimal_png(100, 200)
        b64 = base64.b64encode(data).decode()
        # Insert newlines every 4 chars
        spaced = "\n".join(b64[i : i + 4] for i in range(0, len(b64), 4))
        w, h = verify_base64_png(spaced)
        assert w == 100
        assert h == 200

    def test_invalid_base64_raises(self) -> None:
        """Invalid base64 raises ScreenshotVerificationError."""
        with pytest.raises(ScreenshotVerificationError, match="Invalid base64"):
            verify_base64_png("not-valid-base64!!!")

    def test_valid_base64_but_not_png_raises(self) -> None:
        """Valid base64 encoding of non-PNG data raises verification error."""
        b64 = base64.b64encode(b"This is just text, not a PNG").decode()
        with pytest.raises(ScreenshotVerificationError):
            verify_base64_png(b64)

    def test_data_uri_with_invalid_base64_raises(self) -> None:
        """A data URI with invalid base64 content raises."""
        with pytest.raises(ScreenshotVerificationError, match="Invalid base64"):
            verify_base64_png("data:image/png;base64,!!!invalid!!!")

    def test_empty_string_raises(self) -> None:
        """An empty string raises ScreenshotVerificationError."""
        with pytest.raises(ScreenshotVerificationError):
            verify_base64_png("")


class TestIntegrationWithReportFlow:
    """Integration-style tests verifying the verifier works with the
    same payloads used in the report issue loop and PR manager."""

    def test_valid_png_round_trip(self) -> None:
        """A PNG can be encoded, verified, and the dimensions match."""
        png = make_minimal_png(1920, 1080)
        b64 = base64.b64encode(png).decode()
        w, h = verify_base64_png(b64)
        assert (w, h) == (1920, 1080)

    def test_data_uri_round_trip(self) -> None:
        """A data URI PNG can be verified end-to-end."""
        png = make_minimal_png(800, 600)
        b64 = f"data:image/png;base64,{base64.b64encode(png).decode()}"
        w, h = verify_base64_png(b64)
        assert (w, h) == (800, 600)

    def test_fake_png_header_only_rejected(self) -> None:
        """A payload with only the PNG magic but no valid IHDR is rejected."""
        fake = _PNG_MAGIC + b"\x00" * 5
        b64 = base64.b64encode(fake).decode()
        with pytest.raises(ScreenshotVerificationError):
            verify_base64_png(b64)
