"""Screenshot upload verifier — validates that uploaded data is a valid PNG image.

Checks the PNG magic bytes and basic structural integrity before the payload
is saved to disk or uploaded to a gist.  This prevents corrupt, truncated,
or non-PNG payloads from propagating through the screenshot pipeline.
"""

from __future__ import annotations

import base64
import binascii
import logging
import struct

logger = logging.getLogger("hydraflow.screenshot_upload_verifier")

# PNG files always start with these 8 bytes.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Minimum valid PNG: 8-byte signature + 25-byte IHDR chunk + 12-byte IEND chunk = 45
_MIN_PNG_SIZE = 45

# 10 MB hard cap — anything larger is almost certainly not a dashboard screenshot.
_MAX_PNG_SIZE = 10 * 1024 * 1024

# IHDR chunk type as bytes.
_IHDR_TYPE = b"IHDR"


class ScreenshotVerificationError(ValueError):
    """Raised when a screenshot payload fails validation."""


def verify_png_bytes(data: bytes) -> tuple[int, int]:
    """Validate that *data* is a structurally valid PNG image.

    Returns ``(width, height)`` extracted from the IHDR chunk on success.

    Raises :class:`ScreenshotVerificationError` on any validation failure:
    - Missing or incorrect PNG magic bytes
    - Payload too small or too large
    - Missing or malformed IHDR chunk
    - Zero-dimension image
    """
    if len(data) < len(_PNG_MAGIC):
        raise ScreenshotVerificationError(
            f"Payload too small to be a PNG ({len(data)} bytes)"
        )

    if data[: len(_PNG_MAGIC)] != _PNG_MAGIC:
        raise ScreenshotVerificationError("Missing PNG magic bytes — not a valid PNG")

    if len(data) < _MIN_PNG_SIZE:
        raise ScreenshotVerificationError(
            f"PNG payload truncated ({len(data)} bytes, minimum {_MIN_PNG_SIZE})"
        )

    if len(data) > _MAX_PNG_SIZE:
        raise ScreenshotVerificationError(
            f"PNG payload exceeds size limit "
            f"({len(data)} bytes, maximum {_MAX_PNG_SIZE})"
        )

    # The IHDR chunk must be the first chunk after the 8-byte signature.
    # Chunk layout: 4-byte length + 4-byte type + data + 4-byte CRC.
    ihdr_type = data[12:16]
    if ihdr_type != _IHDR_TYPE:
        raise ScreenshotVerificationError(
            f"First chunk is not IHDR (got {ihdr_type!r})"
        )

    # IHDR data starts at offset 16: width (4 bytes) + height (4 bytes).
    if len(data) < 24:
        raise ScreenshotVerificationError("IHDR chunk truncated")

    width, height = struct.unpack(">II", data[16:24])
    if width == 0 or height == 0:
        raise ScreenshotVerificationError(f"Invalid PNG dimensions: {width}x{height}")

    return width, height


def verify_base64_png(png_base64: str) -> tuple[int, int]:
    """Decode a base64-encoded PNG and validate its structure.

    Handles optional ``data:`` URI prefixes and embedded whitespace.

    Returns ``(width, height)`` on success.

    Raises :class:`ScreenshotVerificationError` on invalid base64 or
    PNG validation failure.
    """
    payload = png_base64
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")

    # Strip whitespace that may be introduced during transport.
    payload = payload.translate({ord(c): None for c in " \t\n\r"})

    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ScreenshotVerificationError(f"Invalid base64 payload: {exc}") from exc

    return verify_png_bytes(raw)
