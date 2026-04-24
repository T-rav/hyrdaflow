"""Unit tests for src/contract_diff.py (§4.2 Task 14).

These tests fabricate recorded vs committed cassette pairs in ``tmp_path``
and exercise the diff detection pipeline end-to-end:

1. ``detect_adapter_drift`` — per-adapter comparison that loads each
   cassette via ``tests.trust.contracts._schema.Cassette``, applies the
   registered normalizers to volatile string fields, and flags drift by
   comparing the canonical normalized payload (not the raw YAML —
   timestamps and recorder SHA would always differ).
2. ``detect_fleet_drift`` — the ``dict[adapter, list[Path]]`` fan-out that
   the background loop's ``_do_work`` will call once per tick.

Scenarios covered per Task 14 acceptance criteria:

* no-drift: identical normalized payloads — reports ``None``.
* value-drift: one output field changed — flagged in ``drifted_cassettes``.
* new-cassette-only: recorded file has no committed sibling — flagged in
  ``new_cassettes``.
* deleted-cassette-only: committed file has no recorded sibling — flagged
  in ``deleted_cassettes``.
* mixed: combinations of the above in one adapter.
* claude adapter: raw JSONL byte compare (no Cassette schema).
* volatile metadata (``recorded_at``, ``recorder_sha``) must NOT trigger
  drift even if changed — that's the whole point of normalized compare.
* normalizer-token drift (e.g. PR number change) must NOT trigger drift
  when the ``pr_number`` normalizer is declared on the cassette.

Hermetic — no subprocess, no network. All paths live under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from contract_diff import (
    AdapterDriftReport,
    FleetDriftReport,
    detect_adapter_drift,
    detect_fleet_drift,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _base_github_payload(**overrides: Any) -> dict[str, Any]:
    """Build a valid github Cassette dict. Override fields via kwargs."""
    payload: dict[str, Any] = {
        "adapter": "github",
        "interaction": "pr_create",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "abc1234",
        "fixture_repo": "T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
        "input": {
            "command": "create_pr",
            "args": ["42", "contract-branch"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": "https://github.com/test-org/test-repo/pull/101\n",
            "stderr": "",
        },
        "normalizers": ["pr_number"],
    }
    payload.update(overrides)
    return payload


def _base_docker_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "adapter": "docker",
        "interaction": "run_alpine_echo",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "abc1234",
        "fixture_repo": "alpine:3.19",
        "input": {
            "command": "run_agent",
            "args": ["alpine:3.19", "echo", "hello"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": '{"exit_code": 0, "success": true, "type": "result"}\n',
            "stderr": "",
        },
        "normalizers": [],
    }
    payload.update(overrides)
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


def _write_jsonl(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# detect_adapter_drift — YAML adapters (github / git / docker)
# ---------------------------------------------------------------------------


def test_adapter_drift_none_when_payloads_match(tmp_path: Path) -> None:
    """Identical normalized payloads → no drift → returns None."""
    recorded = _write_yaml(tmp_path / "rec/pr_create.yaml", _base_github_payload())
    committed = _write_yaml(tmp_path / "com/pr_create.yaml", _base_github_payload())

    report = detect_adapter_drift("github", [recorded], [committed])

    assert report is None


def test_adapter_drift_none_when_only_volatile_metadata_differs(
    tmp_path: Path,
) -> None:
    """``recorded_at`` and ``recorder_sha`` must NOT trigger drift.

    Two recordings of the same real call will always have different
    timestamps and a different recorder SHA — reporting that as drift
    would mean every weekly tick fires a refresh PR. The whole point of
    normalized compare is to ignore these.
    """
    rec = _base_github_payload(
        recorded_at="2026-04-23T09:00:00Z", recorder_sha="fff9999"
    )
    com = _base_github_payload(
        recorded_at="2026-04-22T14:00:00Z", recorder_sha="abc1234"
    )
    r_path = _write_yaml(tmp_path / "rec/pr_create.yaml", rec)
    c_path = _write_yaml(tmp_path / "com/pr_create.yaml", com)

    assert detect_adapter_drift("github", [r_path], [c_path]) is None


def test_adapter_drift_none_when_normalizer_token_differs(tmp_path: Path) -> None:
    """A PR number change with ``pr_number`` normalizer → no drift.

    The cassette declares ``normalizers: [pr_number]``; the registry
    replaces the number with ``<PR_NUMBER>`` before compare, so PR 101 vs
    PR 202 must collapse to the same canonical bytes.
    """
    rec = _base_github_payload(
        output={
            "exit_code": 0,
            "stdout": "https://github.com/test-org/test-repo/pull/202\n",
            "stderr": "",
        }
    )
    com = _base_github_payload()
    r_path = _write_yaml(tmp_path / "rec/pr_create.yaml", rec)
    c_path = _write_yaml(tmp_path / "com/pr_create.yaml", com)

    assert detect_adapter_drift("github", [r_path], [c_path]) is None


def test_adapter_drift_flags_value_drift_in_output_stdout(tmp_path: Path) -> None:
    """A non-normalized output change → flagged as drifted."""
    rec = _base_docker_payload(
        output={
            "exit_code": 0,
            "stdout": '{"exit_code": 0, "success": true, "type": "DIFFERENT"}\n',
            "stderr": "",
        }
    )
    com = _base_docker_payload()
    r_path = _write_yaml(tmp_path / "rec/run_alpine_echo.yaml", rec)
    c_path = _write_yaml(tmp_path / "com/run_alpine_echo.yaml", com)

    report = detect_adapter_drift("docker", [r_path], [c_path])

    assert report is not None
    assert isinstance(report, AdapterDriftReport)
    assert report.adapter == "docker"
    assert report.drifted_cassettes == [r_path]
    assert report.new_cassettes == []
    assert report.deleted_cassettes == []


def test_adapter_drift_flags_exit_code_change(tmp_path: Path) -> None:
    """``exit_code`` is not string-normalized — any change is drift."""
    rec = _base_github_payload(
        output={
            "exit_code": 1,
            "stdout": "https://github.com/test-org/test-repo/pull/101\n",
            "stderr": "",
        }
    )
    com = _base_github_payload()
    r_path = _write_yaml(tmp_path / "rec/pr_create.yaml", rec)
    c_path = _write_yaml(tmp_path / "com/pr_create.yaml", com)

    report = detect_adapter_drift("github", [r_path], [c_path])

    assert report is not None
    assert report.drifted_cassettes == [r_path]


def test_adapter_drift_flags_input_args_change(tmp_path: Path) -> None:
    """Changes on the ``input`` side also count as drift."""
    rec = _base_github_payload(
        input={
            "command": "create_pr",
            "args": ["99", "different-branch"],
            "stdin": None,
            "env": {},
        }
    )
    com = _base_github_payload()
    r_path = _write_yaml(tmp_path / "rec/pr_create.yaml", rec)
    c_path = _write_yaml(tmp_path / "com/pr_create.yaml", com)

    report = detect_adapter_drift("github", [r_path], [c_path])

    assert report is not None
    assert report.drifted_cassettes == [r_path]


def test_adapter_drift_reports_new_cassette_only(tmp_path: Path) -> None:
    """Recorded file with no committed sibling → ``new_cassettes``."""
    rec = _write_yaml(tmp_path / "rec/pr_create.yaml", _base_github_payload())
    # no committed file with that slug

    report = detect_adapter_drift("github", [rec], [])

    assert report is not None
    assert report.new_cassettes == [rec]
    assert report.drifted_cassettes == []
    assert report.deleted_cassettes == []


def test_adapter_drift_reports_deleted_cassette_only(tmp_path: Path) -> None:
    """Committed file with no recorded sibling → ``deleted_cassettes``."""
    com = _write_yaml(tmp_path / "com/pr_create.yaml", _base_github_payload())

    report = detect_adapter_drift("github", [], [com])

    assert report is not None
    assert report.deleted_cassettes == [com]
    assert report.drifted_cassettes == []
    assert report.new_cassettes == []


def test_adapter_drift_reports_mixed(tmp_path: Path) -> None:
    """Drift + new + deleted in one adapter all land in the right bucket."""
    # a: drift
    rec_a = _write_yaml(
        tmp_path / "rec/a.yaml",
        _base_github_payload(
            output={
                "exit_code": 0,
                "stdout": "https://github.com/test-org/test-repo/pull/101\nEXTRA\n",
                "stderr": "",
            }
        ),
    )
    com_a = _write_yaml(tmp_path / "com/a.yaml", _base_github_payload())
    # b: no-drift
    rec_b = _write_yaml(tmp_path / "rec/b.yaml", _base_github_payload())
    com_b = _write_yaml(tmp_path / "com/b.yaml", _base_github_payload())
    # c: new (recorded only)
    rec_c = _write_yaml(tmp_path / "rec/c.yaml", _base_github_payload())
    # d: deleted (committed only)
    com_d = _write_yaml(tmp_path / "com/d.yaml", _base_github_payload())

    report = detect_adapter_drift(
        "github", [rec_a, rec_b, rec_c], [com_a, com_b, com_d]
    )

    assert report is not None
    assert report.adapter == "github"
    assert report.drifted_cassettes == [rec_a]
    assert report.new_cassettes == [rec_c]
    assert report.deleted_cassettes == [com_d]


def test_adapter_drift_matches_by_filename_not_path(tmp_path: Path) -> None:
    """Matching committed cassette is located by basename, not full path.

    Recorded cassettes live under a tmp dir; committed live under
    ``tests/trust/contracts/cassettes/<adapter>/`` — only the filename
    (slug + extension) is shared.
    """
    rec = _write_yaml(tmp_path / "weird/rec/pr_create.yaml", _base_github_payload())
    com = _write_yaml(
        tmp_path / "deep/nested/cassettes/github/pr_create.yaml",
        _base_github_payload(),
    )

    assert detect_adapter_drift("github", [rec], [com]) is None


def test_adapter_drift_empty_inputs_returns_none(tmp_path: Path) -> None:
    """No recordings and no committed cassettes → no drift."""
    assert detect_adapter_drift("github", [], []) is None


# ---------------------------------------------------------------------------
# detect_adapter_drift — claude JSONL adapter (raw byte compare)
# ---------------------------------------------------------------------------


def test_adapter_drift_claude_no_drift_when_jsonl_identical(tmp_path: Path) -> None:
    lines = [
        '{"type": "session", "session_id": "sess_001"}',
        '{"type": "result", "result": "ok"}',
    ]
    rec = _write_jsonl(tmp_path / "rec/stream_001.jsonl", lines)
    com = _write_jsonl(tmp_path / "com/stream_001.jsonl", lines)

    assert detect_adapter_drift("claude", [rec], [com]) is None


def test_adapter_drift_claude_flags_value_drift(tmp_path: Path) -> None:
    rec = _write_jsonl(
        tmp_path / "rec/stream_001.jsonl",
        ['{"type": "result", "result": "DIFFERENT"}'],
    )
    com = _write_jsonl(
        tmp_path / "com/stream_001.jsonl",
        ['{"type": "result", "result": "ok"}'],
    )

    report = detect_adapter_drift("claude", [rec], [com])

    assert report is not None
    assert report.adapter == "claude"
    assert report.drifted_cassettes == [rec]


def test_adapter_drift_claude_new_and_deleted(tmp_path: Path) -> None:
    rec_new = _write_jsonl(tmp_path / "rec/new.jsonl", ['{"type": "ok"}'])
    com_gone = _write_jsonl(tmp_path / "com/gone.jsonl", ['{"type": "ok"}'])

    report = detect_adapter_drift("claude", [rec_new], [com_gone])

    assert report is not None
    assert report.new_cassettes == [rec_new]
    assert report.deleted_cassettes == [com_gone]
    assert report.drifted_cassettes == []


# ---------------------------------------------------------------------------
# detect_fleet_drift
# ---------------------------------------------------------------------------


def test_fleet_drift_no_drift_across_all_four_adapters(tmp_path: Path) -> None:
    """All four adapters recorded and identical → has_drift=False, empty reports."""
    repo_root = tmp_path / "repo"
    # github
    gh_rec = _write_yaml(tmp_path / "rec/github/pr_create.yaml", _base_github_payload())
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/github/pr_create.yaml",
        _base_github_payload(),
    )
    # git
    git_rec = _write_yaml(
        tmp_path / "rec/git/commit.yaml",
        _base_github_payload(adapter="git", interaction="commit", normalizers=[]),
    )
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/git/commit.yaml",
        _base_github_payload(adapter="git", interaction="commit", normalizers=[]),
    )
    # docker
    dk_rec = _write_yaml(
        tmp_path / "rec/docker/run_alpine_echo.yaml", _base_docker_payload()
    )
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/docker/run_alpine_echo.yaml",
        _base_docker_payload(),
    )
    # claude
    cl_rec = _write_jsonl(tmp_path / "rec/claude/stream_001.jsonl", ['{"type": "ok"}'])
    _write_jsonl(
        repo_root / "tests/trust/contracts/claude_streams/stream_001.jsonl",
        ['{"type": "ok"}'],
    )

    recordings = {
        "github": [gh_rec],
        "git": [git_rec],
        "docker": [dk_rec],
        "claude": [cl_rec],
    }
    fleet = detect_fleet_drift(recordings, repo_root)

    assert isinstance(fleet, FleetDriftReport)
    assert fleet.has_drift is False
    assert fleet.reports == []


def test_fleet_drift_flags_drift_on_subset_of_adapters(tmp_path: Path) -> None:
    """Only docker drifted → fleet report contains one adapter entry."""
    repo_root = tmp_path / "repo"
    # github: no drift
    gh_rec = _write_yaml(tmp_path / "rec/github/pr_create.yaml", _base_github_payload())
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/github/pr_create.yaml",
        _base_github_payload(),
    )
    # docker: drift (output changed)
    dk_rec = _write_yaml(
        tmp_path / "rec/docker/run_alpine_echo.yaml",
        _base_docker_payload(
            output={
                "exit_code": 0,
                "stdout": '{"exit_code": 0, "success": false, "type": "result"}\n',
                "stderr": "",
            }
        ),
    )
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/docker/run_alpine_echo.yaml",
        _base_docker_payload(),
    )

    fleet = detect_fleet_drift({"github": [gh_rec], "docker": [dk_rec]}, repo_root)

    assert fleet.has_drift is True
    assert len(fleet.reports) == 1
    assert fleet.reports[0].adapter == "docker"
    assert fleet.reports[0].drifted_cassettes == [dk_rec]


def test_fleet_drift_skips_adapters_without_recordings(tmp_path: Path) -> None:
    """An adapter absent from ``recordings`` is silently skipped.

    The recorder returns ``[]`` when the tool is missing (Task 13); the
    diff layer must not treat that as "everything deleted" — that would
    fire a catastrophic refresh PR every time ``docker`` is down.
    """
    repo_root = tmp_path / "repo"
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/github/pr_create.yaml",
        _base_github_payload(),
    )

    fleet = detect_fleet_drift({}, repo_root)

    assert fleet.has_drift is False
    assert fleet.reports == []


def test_fleet_drift_empty_recording_list_treats_as_no_recordings(
    tmp_path: Path,
) -> None:
    """An adapter key with an empty list must also be skipped.

    Same rationale as above — the recorder returns ``[]`` on infra
    failure. An empty list is the same signal as the key being absent.
    """
    repo_root = tmp_path / "repo"
    _write_yaml(
        repo_root / "tests/trust/contracts/cassettes/github/pr_create.yaml",
        _base_github_payload(),
    )

    fleet = detect_fleet_drift({"github": []}, repo_root)

    assert fleet.has_drift is False
    assert fleet.reports == []


def test_fleet_drift_new_cassette_in_empty_committed_dir(tmp_path: Path) -> None:
    """Recordings produced but the committed dir doesn't exist → all new."""
    repo_root = tmp_path / "repo"  # no committed dirs seeded
    rec = _write_yaml(tmp_path / "rec/github/pr_create.yaml", _base_github_payload())

    fleet = detect_fleet_drift({"github": [rec]}, repo_root)

    assert fleet.has_drift is True
    assert len(fleet.reports) == 1
    assert fleet.reports[0].new_cassettes == [rec]


def test_fleet_drift_unknown_adapter_raises(tmp_path: Path) -> None:
    """Unknown adapter name is a programmer error, not a runtime case."""
    with pytest.raises(ValueError, match="unknown adapter"):
        detect_fleet_drift({"not-a-real-adapter": []}, tmp_path)
