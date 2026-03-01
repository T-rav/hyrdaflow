"""Screenshot secret scanner — detects obvious secrets in base64-encoded images.

Scans the raw base64 payload for high-entropy token patterns that should never
appear in a screenshot destined for upload.  The scanner inspects the decoded
text representation (not the pixel content) to catch secrets accidentally
rendered as visible text in the dashboard UI.
"""

from __future__ import annotations

import re

# Patterns that match common secret/token formats.
# Each tuple: (label, compiled regex)
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GitHub PAT (classic)", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
    ("GitHub PAT (fine-grained)", re.compile(r"github_pat_[A-Za-z0-9_]{40,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{36,}")),
    ("GitHub App token", re.compile(r"ghu_[A-Za-z0-9]{36,}")),
    ("GitHub App installation", re.compile(r"ghs_[A-Za-z0-9]{36,}")),
    ("GitHub refresh token", re.compile(r"ghr_[A-Za-z0-9]{36,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "AWS secret key",
        re.compile(r"(?:aws_secret_access_key|secret_key)\s*[:=]\s*\S{20,}"),
    ),
    ("Slack token", re.compile(r"xox[bporas]-[A-Za-z0-9\-]+")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    (
        "Generic private key",
        re.compile(r"-----BEGIN\s+(RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "Generic secret assignment",
        re.compile(
            r"(?:secret|password|token|api_key)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
            re.IGNORECASE,
        ),
    ),
]


def scan_base64_for_secrets(png_base64: str) -> list[str]:
    """Scan a base64-encoded PNG payload for embedded secret patterns.

    Returns a list of matched pattern labels.  An empty list means no
    secrets were detected.

    **Important limitation:** This scan operates on the raw base64 string, not
    the decoded pixel data.  For actual PNG screenshots captured by html2canvas,
    visible text goes through zlib compression before base64 encoding, which
    means rendered secrets will NOT produce recognisable substrings in the
    encoded payload.  This scanner is therefore primarily effective when the
    payload is not a compressed binary (e.g. an SVG data URI, a plain-text
    blob, or a payload erroneously containing a raw token).  The principal
    protection against leaking sensitive UI content is the frontend DOM
    redaction step (redactSensitiveElements), which runs before capture.
    This scanner provides a defence-in-depth backstop for non-PNG payloads.
    """
    matches: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(png_base64):
            matches.append(label)
    return matches
