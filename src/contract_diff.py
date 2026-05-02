"""Cassette drift detection for the ``ContractRefreshLoop`` (§4.2 Task 14).

The refresh tick records fresh cassettes against the live ``gh`` / ``git``
/ ``docker`` / ``claude`` CLIs (:mod:`contract_recording`) and needs to
decide, per adapter, whether those recordings differ from the committed
cassettes shipped in ``tests/trust/contracts/cassettes/<adapter>/`` (+
``tests/trust/contracts/claude_streams/`` for the Claude adapter). Three
classes of change matter:

1. **Drift** — a slug exists on both sides and the *normalized* payload
   differs. Task 15 turns this into a ``contract-refresh`` PR.
2. **New** — a slug was recorded but has no committed sibling. Task 15
   writes the new cassette into the committed tree and ships it in the
   same refresh PR.
3. **Deleted** — a slug is committed but was not produced by this
   tick. Flagged so Task 15 can decide whether the committed file is
   stale or whether the recorder regressed.

Why normalize before compare
----------------------------

Raw YAML bytes would always differ: ``recorded_at`` and ``recorder_sha``
change every tick. The :mod:`contracts._schema` module
already defines the normalizer registry used by the replay harness —
reuse it here so the diff side agrees with the replay side on what
counts as "the same interaction". A cassette declares its normalizers
in a ``normalizers:`` list; we apply each one to ``input.stdin``,
``output.stdout``, and ``output.stderr`` before comparison.

Volatile metadata (``recorded_at``, ``recorder_sha``) is dropped from
the canonical payload entirely — these are audit-trail fields, not
contract fields, so changing them must never fire a refresh PR.

Claude streams are JSONL, not YAML, and do not go through the
``Cassette`` schema. Each line is parsed as JSON, recursively stripped
of volatile identifiers (``session_id``, ``timestamp``, ``id``,
``parent_tool_use_id``, ``uuid``, ``created_at``), and the canonical
list is serialized with ``sort_keys=True`` for compare (Task 17). This
way two recordings of the same prompt with different session IDs do
*not* fire drift, but a protocol bump that renames a load-bearing key
or changes the event sequence does.

Spec: ``docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md``
§4.2 "ContractRefreshLoop — full caretaker".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contracts._schema import (
    Cassette,
    apply_normalizers,
    load_cassette,
)

# The four recorder-side adapter names. Must stay aligned with
# ``ADAPTER_PLANS`` in ``src/contract_refresh_loop.py`` and with the
# three YAML adapters accepted by ``_schema.Cassette._validate_adapter``
# plus the ``claude`` JSONL stream adapter.
_KNOWN_ADAPTERS: frozenset[str] = frozenset({"github", "git", "docker", "claude"})

# Committed cassette directories per adapter, relative to the repo root.
# Mirrors ``ADAPTER_PLANS`` — duplicated here rather than imported to
# avoid pulling the whole loop module (and its ``BaseBackgroundLoop``
# transitive deps) into the diff layer.
_COMMITTED_DIR_RELPATH: dict[str, str] = {
    "github": "tests/trust/contracts/cassettes/github",
    "git": "tests/trust/contracts/cassettes/git",
    "docker": "tests/trust/contracts/cassettes/docker",
    "claude": "tests/trust/contracts/claude_streams",
}


@dataclass(frozen=True)
class AdapterDriftReport:
    """Per-adapter diff outcome.

    ``drifted_cassettes`` — recorded paths whose normalized payload does
    not match the committed sibling.
    ``new_cassettes`` — recorded paths with no committed sibling.
    ``deleted_cassettes`` — committed paths with no recorded sibling.

    Only the *recorded* path is stored in ``drifted_cassettes`` and
    ``new_cassettes`` so Task 15 can read the fresh bytes directly.
    ``deleted_cassettes`` stores the *committed* path — there's nothing
    new on the recorder side to link to.
    """

    adapter: str
    drifted_cassettes: list[Path] = field(default_factory=list)
    new_cassettes: list[Path] = field(default_factory=list)
    deleted_cassettes: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class FleetDriftReport:
    """Fleet-wide aggregate. ``has_drift`` is the single trigger Task 15 checks.

    ``reports`` contains only adapters that had at least one bucket
    populated — a clean adapter contributes nothing so the background
    loop's status payload stays terse on the happy path.
    """

    reports: list[AdapterDriftReport]
    has_drift: bool


def _canonical_payload(cassette: Cassette) -> bytes:
    """Return a deterministic byte representation of *cassette* for compare.

    * Volatile metadata (``recorded_at``, ``recorder_sha``) is dropped.
    * String fields that carry volatile tokens (``input.stdin``,
      ``output.stdout``, ``output.stderr``) are run through each
      registered normalizer in the order declared on the cassette.
    * The result is JSON-serialized with ``sort_keys=True`` so dict key
      ordering cannot introduce phantom drift.
    """
    payload: dict[str, Any] = cassette.model_dump(mode="json")

    # Drop audit-trail metadata that changes every tick.
    payload.pop("recorded_at", None)
    payload.pop("recorder_sha", None)

    normalizers = cassette.normalizers

    stdin_val = payload["input"].get("stdin")
    if isinstance(stdin_val, str):
        payload["input"]["stdin"] = apply_normalizers(stdin_val, normalizers)

    payload["output"]["stdout"] = apply_normalizers(
        payload["output"].get("stdout", ""), normalizers
    )
    payload["output"]["stderr"] = apply_normalizers(
        payload["output"].get("stderr", ""), normalizers
    )

    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _canonical_yaml(path: Path) -> bytes:
    """Load a YAML cassette via the schema model and canonicalize it."""
    return _canonical_payload(load_cassette(path))


# Fields that vary per invocation and carry no semantic contract — dropped
# before comparing two claude stream samples. Byte-wise compare was too
# brittle once a protocol version touches any of these (Task 17).
_CLAUDE_VOLATILE_FIELDS: frozenset[str] = frozenset(
    {
        "session_id",
        "timestamp",
        "id",
        "parent_tool_use_id",
        "uuid",
        "created_at",
    }
)


def _strip_volatile(obj: Any) -> Any:
    """Recursively drop ``_CLAUDE_VOLATILE_FIELDS`` keys from a JSON value.

    Claude stream events nest under ``message.content[*]`` and a few other
    places where a volatile identifier can live. Walking the tree means a
    protocol change that moves ``id`` down one level still gets stripped.
    """
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v)
            for k, v in obj.items()
            if k not in _CLAUDE_VOLATILE_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _normalize_claude_stream(lines: list[str]) -> list[dict[str, Any]]:
    """Parse a claude JSONL stream into a canonical list of events.

    Each line is a standalone JSON object. Blank / whitespace-only lines
    and malformed JSON are silently dropped — the stream-json recorder
    can emit a trailing blank line and a mid-flight truncation is noise,
    not signal. Surviving events have every key in
    :data:`_CLAUDE_VOLATILE_FIELDS` recursively stripped so two runs of
    the same prompt produce the same canonical list.

    The diff layer compares these canonical lists instead of raw bytes
    (spec §4.2 Task 17), so a protocol bump that renames a load-bearing
    field still fires drift but a fresh ``session_id`` alone does not.
    """
    out: list[dict[str, Any]] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        out.append(_strip_volatile(event))
    return out


def _canonical_jsonl(path: Path) -> bytes:
    """Canonical representation of a claude JSONL stream (Task 17).

    Parses every line through :func:`_normalize_claude_stream` and
    re-serializes the resulting list with ``sort_keys=True`` so dict-key
    reordering between runs cannot introduce phantom drift. Falls back
    to raw bytes when the file is not valid UTF-8 — a corrupt recording
    will legitimately flag as drift that way.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes()
    normalized = _normalize_claude_stream(text.splitlines())
    return json.dumps(normalized, sort_keys=True).encode("utf-8")


def _canonicalize(adapter: str, path: Path) -> bytes:
    if adapter == "claude":
        return _canonical_jsonl(path)
    return _canonical_yaml(path)


def detect_adapter_drift(
    adapter: str,
    recorded_cassettes: list[Path],
    committed_cassettes: list[Path],
) -> AdapterDriftReport | None:
    """Diff *recorded_cassettes* against *committed_cassettes* by filename.

    Two cassettes match when they share a basename (e.g. ``pr_create.yaml``).
    Match → canonicalize both sides and byte-compare; a mismatch lands in
    ``drifted_cassettes``. A recorded-only slug lands in ``new_cassettes``;
    a committed-only slug in ``deleted_cassettes``.

    Returns ``None`` when all three buckets are empty (the fast-path the
    loop hits on every clean tick).
    """
    if adapter not in _KNOWN_ADAPTERS:
        msg = f"unknown adapter {adapter!r}; known: {sorted(_KNOWN_ADAPTERS)}"
        raise ValueError(msg)

    recorded_by_name: dict[str, Path] = {p.name: p for p in recorded_cassettes}
    committed_by_name: dict[str, Path] = {p.name: p for p in committed_cassettes}

    drifted: list[Path] = []
    new: list[Path] = []
    deleted: list[Path] = []

    for name, rec_path in recorded_by_name.items():
        com_path = committed_by_name.get(name)
        if com_path is None:
            new.append(rec_path)
            continue
        if _canonicalize(adapter, rec_path) != _canonicalize(adapter, com_path):
            drifted.append(rec_path)

    for name, com_path in committed_by_name.items():
        if name not in recorded_by_name:
            deleted.append(com_path)

    if not drifted and not new and not deleted:
        return None
    return AdapterDriftReport(
        adapter=adapter,
        drifted_cassettes=drifted,
        new_cassettes=new,
        deleted_cassettes=deleted,
    )


def _committed_cassettes_for(adapter: str, repo_root: Path) -> list[Path]:
    """Enumerate the committed cassette files for *adapter*.

    Returns ``[]`` if the committed directory does not exist (e.g. first
    time this adapter is being recorded) — the caller then treats every
    recorded cassette as ``new_cassettes``.
    """
    committed_dir = repo_root / _COMMITTED_DIR_RELPATH[adapter]
    if not committed_dir.is_dir():
        return []
    suffix = ".jsonl" if adapter == "claude" else ".yaml"
    return sorted(committed_dir.glob(f"*{suffix}"))


def detect_fleet_drift(
    recordings: dict[str, list[Path]], repo_root: Path
) -> FleetDriftReport:
    """Run :func:`detect_adapter_drift` for each adapter in *recordings*.

    An adapter absent from *recordings* (or mapped to an empty list) is
    silently skipped — that's the signal :mod:`contract_recording` uses
    when a tool is missing or the sandbox is offline. Treating the
    absence as "everything deleted" would fire a catastrophic refresh PR
    every time the docker daemon hiccups; explicit opt-in prevents that.

    Unknown adapter names raise ``ValueError`` so a typo in the caller is
    loud at dispatch time.
    """
    for adapter in recordings:
        if adapter not in _KNOWN_ADAPTERS:
            msg = f"unknown adapter {adapter!r}; known: {sorted(_KNOWN_ADAPTERS)}"
            raise ValueError(msg)

    reports: list[AdapterDriftReport] = []
    for adapter, recorded in recordings.items():
        if not recorded:
            # See docstring — empty list is a no-signal, not a sweep.
            continue
        committed = _committed_cassettes_for(adapter, repo_root)
        report = detect_adapter_drift(adapter, recorded, committed)
        if report is not None:
            reports.append(report)

    return FleetDriftReport(reports=reports, has_drift=bool(reports))
