"""Live shadow corpus — Phase 0 of #8786.

Captures real subprocess interactions (gh/git/docker/claude) so a follow-up
``LiveCorpusReplayLoop`` can diff them against fake-adapter outputs without
needing a shared sandbox repo. This module owns *storage*; wiring into
``subprocess_util.run_subprocess`` lives in a separate PR so the surface
area stays small.

Design constraints from #8786:

- **Bounded**: ``max_per_adapter`` caps the corpus by per-adapter LRU on
  file mtime. One sample per (adapter, command, args) shape — repeated
  invocations overwrite the same file (most recent wins).
- **Normalized**: every persisted ``stdout`` / ``stderr`` passes through
  the existing cassette normalizers (``pr_number``, ``sha:short``,
  ``sha:long``, ``timestamps.ISO8601``) so volatile fields collapse to
  stable tokens before persistence.
- **PII-scrubbed**: defence in depth above normalizers — emails, GitHub
  PAT tokens, and basic-auth credentials in URLs are redacted before the
  bytes hit disk. Other tokens (Slack, SSH keys, etc.) can be added as
  the corpus grows; the test suite documents the supported scrubs.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml

from contracts._schema import apply_normalizers

logger = logging.getLogger("hydraflow.contracts.shadow")

# Adapters the shadow corpus knows how to label. Keep aligned with the
# cassette schema's ``_KNOWN_ADAPTERS`` plus ``claude`` (whose contract
# fixtures are JSONL streams; this module handles command-shaped calls).
Adapter = Literal["github", "git", "docker", "claude"]
_KNOWN_ADAPTERS: frozenset[str] = frozenset({"github", "git", "docker", "claude"})

# Normalizers applied to every persisted stdout/stderr. Order matches
# ``contracts._schema.NORMALIZERS`` — sha:long before sha:short so the
# 40-char hashes aren't half-consumed by the 7-12 char rule.
_DEFAULT_NORMALIZERS: tuple[str, ...] = (
    "pr_number",
    "timestamps.ISO8601",
    "sha:long",
    "sha:short",
)

# PII scrub regexes. Applied after normalizers, before write. Each rule is
# (compiled regex, replacement token). Patterns are deliberately
# conservative to avoid over-redacting legitimate output.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_GH_TOKEN_RE = re.compile(r"\bgh[psoru]_[A-Za-z0-9]{20,}\b")
_BASIC_AUTH_RE = re.compile(r"://[^/\s@]+:[^/\s@]+@")
_PII_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Basic-auth in URLs must scrub first — the email regex would otherwise
    # grab ``user:secrettoken@host`` and mask the credential as ``<EMAIL>``,
    # losing the "this was a credential" signal in the persisted sample.
    (_BASIC_AUTH_RE, "://<CREDS>@"),
    (_GH_TOKEN_RE, "<GH_TOKEN>"),
    (_EMAIL_RE, "<EMAIL>"),
)


@dataclass(frozen=True)
class ShadowSample:
    """One live-recorded subprocess interaction (in-memory view)."""

    adapter: str
    command: str
    args: list[str]
    exit_code: int
    stdout: str
    stderr: str
    sampled_at: str
    call_hash: str


def _scrub(text: str) -> str:
    """Apply normalizers then PII rules. Idempotent."""
    text = apply_normalizers(text, list(_DEFAULT_NORMALIZERS))
    for pattern, token in _PII_RULES:
        text = pattern.sub(token, text)
    return text


def _call_hash(adapter: str, command: str, args: list[str]) -> str:
    """Stable 12-hex-char digest of the call shape.

    Deterministic on (adapter, command, args) so repeated invocations of
    the same shape land at the same path. Truncated to 12 chars — the
    corpus is small enough that collision odds are negligible at that
    width (~1 in 2^48).
    """
    raw = "\n".join([adapter, command, *args]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


class ShadowCorpus:
    """Bounded, normalized, PII-scrubbed storage for live subprocess samples."""

    def __init__(self, root: Path, *, max_per_adapter: int = 100) -> None:
        if max_per_adapter < 1:
            msg = f"max_per_adapter must be >= 1, got {max_per_adapter}"
            raise ValueError(msg)
        self._root = root
        self._max_per_adapter = max_per_adapter

    def record(
        self,
        *,
        adapter: str,
        command: str,
        args: list[str],
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> Path | None:
        """Persist one sample and return its path.

        Returns ``None`` if persistence is skipped for any reason — the
        caller treats that as "no observation this tick" rather than an
        error. Unknown adapters are a programming bug, not a runtime
        condition, so they raise.
        """
        if adapter not in _KNOWN_ADAPTERS:
            msg = (
                f"unknown adapter {adapter!r}; expected one of "
                f"{sorted(_KNOWN_ADAPTERS)}"
            )
            raise ValueError(msg)

        adapter_dir = self._root / adapter
        adapter_dir.mkdir(parents=True, exist_ok=True)

        call_hash = _call_hash(adapter, command, args)
        path = adapter_dir / f"{call_hash}.yaml"

        payload = {
            "adapter": adapter,
            "command": command,
            "args": list(args),
            "sampled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "call_hash": call_hash,
            "output": {
                "exit_code": exit_code,
                "stdout": _scrub(stdout),
                "stderr": _scrub(stderr),
            },
        }
        try:
            with path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
        except OSError as exc:
            logger.warning("shadow corpus: failed to persist %s: %s", path, exc)
            return None

        self._prune(adapter)
        return path

    def list(self, *, adapter: str | None = None) -> list[Path]:
        """Enumerate samples; if ``adapter`` is None, return every adapter's."""
        if adapter is not None:
            if adapter not in _KNOWN_ADAPTERS:
                msg = f"unknown adapter {adapter!r}"
                raise ValueError(msg)
            adapter_dir = self._root / adapter
            if not adapter_dir.is_dir():
                return []
            return sorted(adapter_dir.glob("*.yaml"))
        out: list[Path] = []
        for name in sorted(_KNOWN_ADAPTERS):
            adapter_dir = self._root / name
            if adapter_dir.is_dir():
                out.extend(sorted(adapter_dir.glob("*.yaml")))
        return out

    def load(self, path: Path) -> ShadowSample:
        """Parse a persisted YAML back into a typed ShadowSample."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        output = raw.get("output") or {}
        return ShadowSample(
            adapter=str(raw["adapter"]),
            command=str(raw["command"]),
            args=list(raw.get("args") or []),
            exit_code=int(output.get("exit_code", 0)),
            stdout=str(output.get("stdout", "")),
            stderr=str(output.get("stderr", "")),
            sampled_at=str(raw.get("sampled_at", "")),
            call_hash=str(raw.get("call_hash", "")),
        )

    def _prune(self, adapter: str) -> int:
        """LRU-evict oldest samples in ``adapter`` until count <= cap.

        Returns the number of files evicted (0 if under cap). Uses mtime
        as the LRU signal — the most-recently-recorded shape wins.
        """
        adapter_dir = self._root / adapter
        if not adapter_dir.is_dir():
            return 0
        samples = sorted(adapter_dir.glob("*.yaml"), key=lambda p: p.stat().st_mtime)
        excess = len(samples) - self._max_per_adapter
        if excess <= 0:
            return 0
        evicted = 0
        for victim in samples[:excess]:
            try:
                victim.unlink()
                evicted += 1
            except OSError as exc:
                logger.warning("shadow corpus: failed to evict %s: %s", victim, exc)
        return evicted
