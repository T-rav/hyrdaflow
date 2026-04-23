# Fake Contract Tests + ContractRefreshLoop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship §4.2 of the trust-architecture hardening spec — VCR-style contract tests against the `MockWorld` fakes (`FakeGitHub`, `FakeGit`, `FakeDocker`, `FakeLLM`), plus a `ContractRefreshLoop` caretaker that auto-refreshes cassettes weekly and auto-dispatches fake/parser repair on drift.

**Architecture:** Phase 1 is a static two-sided harness — YAML cassettes under `tests/trust/contracts/cassettes/<adapter>/` drive a replay side that calls the scenario-ring fake and asserts field-by-field (with normalizers for auto-incrementing fields). `claude_streams/*.jsonl` drive a stream replay that feeds `src/stream_parser.py:StreamParser`. Phase 1 wires both into `make trust-contracts` → extended `make trust` → `rc-promotion-scenario.yml`. Phase 2 adds `src/contract_refresh_loop.py:ContractRefreshLoop`, a `BaseBackgroundLoop` caretaker that re-records against live `gh`/`git`/`docker`/`claude`, commits diffs via `open_automated_pr_async`, and files `fake-drift` or `stream-protocol-drift` `hydraflow-find` issues when a fake or the parser diverges. A per-adapter 3-attempt repair tracker escalates to `hitl-escalation` + `fake-repair-stuck` / `stream-parser-stuck`.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, pyyaml (new dep), pydantic v2, `BaseBackgroundLoop`, `PRManager.create_issue`, `open_automated_pr_async`.

**Spec:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` — §4.2 only (plus §5 infra that §4.2 needs, §6 rows for §4.2, §7 unit tests for §4.2).

**Design decisions made in this plan (deferred by spec):**

1. **FakeGitHub fixture target (§8 out-of-tree dep):** a dedicated `hydraflow-contracts-sandbox` repo under the HydraFlow GitHub org. Simpler than ephemeral forks, predictable auth under the existing `gh` CLI session, no per-run cleanup. Creating it is a one-time manual setup described in Task 0.
2. **Max repair-attempt budget field (§4.2 step 6):** `max_fake_repair_attempts` — a dedicated new field (default 3), not `max_issue_attempts`. `fake-drift` is a distinct repair class; overloading the general issue budget would couple unrelated retries.
3. **Stream-sample prompt (§9 open question 4):** `"List the first three primes. Use no tools."` — short, deterministic, exercises the text-block path without tools. Recorded as `stream_001_list_primes.jsonl`. Two more samples (`stream_002_with_read_tool.jsonl`, `stream_003_with_thinking.jsonl`) cover the tool-use and thinking-block transitions.

**Spec coverage map:**

| Spec requirement (§4.2) | Tasks |
|---|---|
| Cassette tree + YAML schema | Tasks 1, 2, 3 |
| Replay harness (normalizers, two-sided) | Tasks 4, 5 |
| `test_fake_github_contract.py` | Task 6 |
| `test_fake_git_contract.py` | Task 7 |
| `test_fake_docker_contract.py` | Task 8 |
| `test_fake_llm_contract.py` + stream samples | Task 9 |
| `make trust-contracts` + extend `make trust` + CI | Task 10 |
| `ContractRefreshLoop` skeleton | Task 11 |
| Loop construction unit test | Task 12 |
| Recording subroutines (real gh/git/docker/claude) | Task 13 |
| Diff detection | Task 14 |
| Refresh PR via PRManager + auto_pr | Task 15 |
| Cassette-only vs fake-drift split + companion issue filing | Task 16 |
| Stream-protocol drift path | Task 17 |
| 3-attempt escalation tracker + `max_fake_repair_attempts` | Task 18 |
| Five-checkpoint wiring | Tasks 19a–19e |
| Per-loop telemetry emission (§4.11 point 3) | Task 20 |
| Integration test (end-to-end injected drift) | Task 21 |
| `tests/test_loop_wiring_completeness.py` covers new loop | Task 22 |
| MockWorld scenario (§7 integration-side requirement) | Task 23 |
| Commit + PR description | Task 24 |

---

## Task 0: Manual pre-requisite — create sandbox repo

**Files:** none (human task).

This is a human-run setup step — the loop cannot auto-create a GitHub repo under the org without a PAT with org-admin scope, which is out of band for this plan. The engineer executing Task 1 must confirm this is complete before starting.

- [ ] **Step 1: Create the sandbox repo**

Using an org-admin `gh` session, run:

```bash
gh repo create T-rav-Hydra-Ops/hydraflow-contracts-sandbox \
    --public \
    --description "Throwaway fixture repo for HydraFlow FakeGitHub contract cassettes. Managed by ContractRefreshLoop." \
    --add-readme
```

- [ ] **Step 2: Grant the loop's `gh` session write access**

Loop authentication uses the ambient `gh auth status` token (same as the rest of HydraFlow). Confirm that identity has push rights on the sandbox repo:

```bash
gh api repos/T-rav-Hydra-Ops/hydraflow-contracts-sandbox --jq '.permissions'
# expect: {"admin": true, "maintain": true, "push": true, "triage": true, "pull": true}
```

- [ ] **Step 3: Seed a baseline commit so `gh pr create` has a target**

```bash
cd /tmp
gh repo clone T-rav-Hydra-Ops/hydraflow-contracts-sandbox
cd hydraflow-contracts-sandbox
echo "contract-fixture" > FIXTURE.md
git add FIXTURE.md
git commit -m "chore: seed fixture"
git push origin main
```

No test changes. This task produces no code; it's a precondition for Task 13.

---

## Task 1: Scaffold `tests/trust/contracts/` tree

**Files:**
- Create: `tests/trust/__init__.py`
- Create: `tests/trust/contracts/__init__.py`
- Create: `tests/trust/contracts/cassettes/__init__.py`
- Create: `tests/trust/contracts/cassettes/github/.gitkeep`
- Create: `tests/trust/contracts/cassettes/git/.gitkeep`
- Create: `tests/trust/contracts/cassettes/docker/.gitkeep`
- Create: `tests/trust/contracts/claude_streams/.gitkeep`
- Create: `tests/trust/contracts/fixtures/git_sandbox/.gitkeep`

- [ ] **Step 1: Create directories**

```bash
mkdir -p tests/trust/contracts/cassettes/github
mkdir -p tests/trust/contracts/cassettes/git
mkdir -p tests/trust/contracts/cassettes/docker
mkdir -p tests/trust/contracts/claude_streams
mkdir -p tests/trust/contracts/fixtures/git_sandbox
```

- [ ] **Step 2: Create `__init__.py` files**

Write an empty file to each of:

```
tests/trust/__init__.py
tests/trust/contracts/__init__.py
tests/trust/contracts/cassettes/__init__.py
```

- [ ] **Step 3: Create `.gitkeep` placeholders**

Touch empty `.gitkeep` files in the four data directories created in Step 1 (github, git, docker, claude_streams, fixtures/git_sandbox). These keep the directories tracked before any cassettes land.

- [ ] **Step 4: Add `pyyaml` to test deps**

In `pyproject.toml:32-42` (the `[project.optional-dependencies]` `test` list), add `"pyyaml>=6.0"` as the last item before the closing bracket:

```toml
test = [
    "pytest>=9.0.3",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
    "pytest-xdist>=3.5.0",
    "pytest-playwright>=0.5.0",
    "pytest-rerunfailures>=16.0",
    "httpx>=0.27.0",
    "hypothesis>=6.100.0",
    "pyyaml>=6.0",
]
```

Run `uv sync --all-extras` to install.

- [ ] **Step 5: Commit**

```bash
git add tests/trust/ pyproject.toml
git commit -m "feat(trust): scaffold tests/trust/contracts/ tree + add pyyaml"
```

---

## Task 2: Cassette schema + normalizer registry

**Files:**
- Create: `tests/trust/contracts/_schema.py`

The cassette schema is the shared YAML shape from spec §4.2. A pydantic v2 model validates every load; a normalizer registry exposes three canonical field transforms (`pr_number`, `timestamps.ISO8601`, `sha:short`) named in the spec.

- [ ] **Step 1: Write the failing test (goes in Task 3)**

Deferred to Task 3 — we write the schema and the test file together, schema first so we can import it.

- [ ] **Step 2: Write `_schema.py`**

Create `tests/trust/contracts/_schema.py`:

```python
"""Cassette YAML schema + normalizer registry for fake contract tests.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "Cassette schema".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field, field_validator


class CassetteInput(BaseModel):
    """One-interaction input block."""

    command: str
    args: list[str] = Field(default_factory=list)
    stdin: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class CassetteOutput(BaseModel):
    """One-interaction output block."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""


class Cassette(BaseModel):
    """A single recorded interaction between HydraFlow and a real adapter."""

    adapter: str
    interaction: str
    recorded_at: str
    recorder_sha: str
    fixture_repo: str
    input: CassetteInput
    output: CassetteOutput
    normalizers: list[str] = Field(default_factory=list)

    @field_validator("adapter")
    @classmethod
    def _validate_adapter(cls, v: str) -> str:
        if v not in {"github", "git", "docker"}:
            msg = f"adapter must be one of github|git|docker, got {v!r}"
            raise ValueError(msg)
        return v

    @field_validator("normalizers")
    @classmethod
    def _validate_normalizers(cls, v: list[str]) -> list[str]:
        for name in v:
            if name not in NORMALIZERS:
                msg = f"unknown normalizer {name!r}; known: {sorted(NORMALIZERS)}"
                raise ValueError(msg)
        return v


# --- Normalizer registry -----------------------------------------------------

# A normalizer transforms a stdout/stderr string so that volatile bytes
# (e.g. auto-assigned PR numbers, fresh timestamps) collapse to a stable
# token before comparison. Both sides of the replay harness run every
# listed normalizer on both texts before `==`.

_PR_NUMBER_RE = re.compile(r"/pull/(\d+)\b|pr[_ -]?(?:number|num)[:= ]+(\d+)\b", re.IGNORECASE)
_ISO8601_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})\b"
)
_SHORT_SHA_RE = re.compile(r"\b[0-9a-f]{7,12}\b")


def _norm_pr_number(text: str) -> str:
    return _PR_NUMBER_RE.sub(
        lambda m: m.group(0).replace(m.group(1) or m.group(2), "<PR_NUMBER>"), text
    )


def _norm_iso8601(text: str) -> str:
    return _ISO8601_RE.sub("<ISO8601>", text)


def _norm_short_sha(text: str) -> str:
    return _SHORT_SHA_RE.sub("<SHORT_SHA>", text)


NORMALIZERS: dict[str, Callable[[str], str]] = {
    "pr_number": _norm_pr_number,
    "timestamps.ISO8601": _norm_iso8601,
    "sha:short": _norm_short_sha,
}


def apply_normalizers(text: str, names: list[str]) -> str:
    """Apply each named normalizer to *text* in order; return the result."""
    for name in names:
        text = NORMALIZERS[name](text)
    return text


def load_cassette(path: Path) -> Cassette:
    """Parse a YAML cassette file and return a validated Cassette model."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        msg = f"cassette {path} did not parse to a mapping: {type(raw).__name__}"
        raise ValueError(msg)
    return Cassette.model_validate(raw)


def dump_cassette(cassette: Cassette, path: Path) -> None:
    """Serialize *cassette* to YAML at *path*."""
    payload = cassette.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
```

- [ ] **Step 3: Commit**

```bash
git add tests/trust/contracts/_schema.py
git commit -m "feat(trust): cassette YAML schema + normalizer registry"
```

---

## Task 3: Unit-test the cassette schema

**Files:**
- Create: `tests/test_contract_cassette_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for tests/trust/contracts/_schema.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.trust.contracts._schema import (
    Cassette,
    NORMALIZERS,
    apply_normalizers,
    dump_cassette,
    load_cassette,
)


_MINIMAL_YAML = textwrap.dedent(
    """\
    adapter: github
    interaction: pr_create
    recorded_at: 2026-04-22T14:07:03Z
    recorder_sha: abc1234
    fixture_repo: T-rav-Hydra-Ops/hydraflow-contracts-sandbox
    input:
      command: gh pr create
      args: ["--title", "test"]
    output:
      exit_code: 0
      stdout: "https://github.com/test/repo/pull/42\\n"
      stderr: ""
    normalizers:
      - pr_number
    """
)


class TestLoadCassette:
    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(_MINIMAL_YAML)
        cas = load_cassette(path)
        assert cas.adapter == "github"
        assert cas.interaction == "pr_create"
        assert cas.input.command == "gh pr create"
        assert cas.output.exit_code == 0
        assert cas.normalizers == ["pr_number"]

    def test_rejects_unknown_adapter(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(_MINIMAL_YAML.replace("adapter: github", "adapter: slack"))
        with pytest.raises(ValueError, match="adapter must be one of"):
            load_cassette(path)

    def test_rejects_unknown_normalizer(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        bad = _MINIMAL_YAML.replace("pr_number", "not_a_real_normalizer")
        path.write_text(bad)
        with pytest.raises(ValueError, match="unknown normalizer"):
            load_cassette(path)


class TestNormalizers:
    def test_pr_number_replaces_pull_url(self) -> None:
        result = NORMALIZERS["pr_number"]("see https://github.com/a/b/pull/8123 merged")
        assert "<PR_NUMBER>" in result
        assert "8123" not in result

    def test_iso8601_replaces_timestamps(self) -> None:
        text = "started at 2026-04-22T14:07:03Z and ended at 2026-04-22T14:10:45.123+00:00"
        result = NORMALIZERS["timestamps.ISO8601"](text)
        assert "<ISO8601>" in result
        assert "2026-04-22" not in result

    def test_short_sha_replaces_hexes(self) -> None:
        result = NORMALIZERS["sha:short"]("commit abc1234 authored")
        assert "<SHORT_SHA>" in result
        assert "abc1234" not in result

    def test_apply_chains_all_names(self) -> None:
        text = "pr #7 at 2026-04-22T14:00:00Z sha deadbeef"
        result = apply_normalizers(
            text, ["pr_number", "timestamps.ISO8601", "sha:short"]
        )
        assert "2026-04-22" not in result
        assert "deadbeef" not in result


class TestDumpCassette:
    def test_dump_produces_loadable_file(self, tmp_path: Path) -> None:
        cas = Cassette(
            adapter="git",
            interaction="commit",
            recorded_at="2026-04-22T14:07:03Z",
            recorder_sha="abc1234",
            fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
            input={"command": "git commit", "args": ["-m", "x"]},
            output={"exit_code": 0, "stdout": "", "stderr": ""},
            normalizers=[],
        )
        out = tmp_path / "out.yaml"
        dump_cassette(cas, out)
        loaded = load_cassette(out)
        assert loaded.adapter == "git"
        assert loaded.interaction == "commit"
```

- [ ] **Step 2: Run to see failure**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_cassette_schema.py -v`
Expected: PASS — the tests target schema written in Task 2. If any fail, fix the schema first.

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract_cassette_schema.py
git commit -m "test(trust): cassette schema + normalizer registry tests"
```

---

## Task 4: Replay harness helper

**Files:**
- Create: `tests/trust/contracts/_replay.py`

The replay harness is the shared engine for all four `test_fake_*_contract.py` files. It loads a cassette, dispatches to an adapter-specific fake-invoker callback that returns the fake's output (exit code, stdout, stderr), applies normalizers to both sides, and asserts equality. Keeping the dispatch pluggable (`invoke_fake` callback) keeps the fake-specific wiring out of the shared code.

- [ ] **Step 1: Write `_replay.py`**

```python
"""Shared replay harness for fake contract tests.

Each test_fake_*_contract.py uses `replay_cassette` to:
1. Load + validate a YAML cassette,
2. Invoke its adapter-specific fake via a callback,
3. Normalize both sides and assert field-by-field equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from tests.trust.contracts._schema import Cassette, apply_normalizers, load_cassette


@dataclass(frozen=True)
class FakeOutput:
    """Shape the fake-invoker callback must return."""

    exit_code: int
    stdout: str
    stderr: str


FakeInvoker = Callable[[Cassette], Awaitable[FakeOutput]]


async def replay_cassette(path: Path, invoke_fake: FakeInvoker) -> None:
    """Replay *path* through *invoke_fake*; assert equality under normalizers.

    Raises AssertionError on mismatch so pytest reports it. The harness does
    not catch schema errors — let them propagate so a bad cassette fails
    loudly rather than silently being treated as "fake diverged".
    """
    cassette = load_cassette(path)
    got = await invoke_fake(cassette)

    want_stdout = apply_normalizers(cassette.output.stdout, cassette.normalizers)
    got_stdout = apply_normalizers(got.stdout, cassette.normalizers)

    want_stderr = apply_normalizers(cassette.output.stderr, cassette.normalizers)
    got_stderr = apply_normalizers(got.stderr, cassette.normalizers)

    assert got.exit_code == cassette.output.exit_code, (
        f"{path.name}: exit_code mismatch — "
        f"cassette={cassette.output.exit_code} fake={got.exit_code}"
    )
    assert got_stdout == want_stdout, (
        f"{path.name}: stdout drift after normalizers {cassette.normalizers}\n"
        f"--- cassette ---\n{want_stdout}\n--- fake ---\n{got_stdout}"
    )
    assert got_stderr == want_stderr, (
        f"{path.name}: stderr drift after normalizers {cassette.normalizers}\n"
        f"--- cassette ---\n{want_stderr}\n--- fake ---\n{got_stderr}"
    )


def list_cassettes(directory: Path) -> list[Path]:
    """Return sorted list of `*.yaml` files under *directory* (non-recursive)."""
    return sorted(directory.glob("*.yaml"))
```

- [ ] **Step 2: Commit**

```bash
git add tests/trust/contracts/_replay.py
git commit -m "feat(trust): replay harness helper for contract cassettes"
```

---

## Task 5: Unit-test the replay harness

**Files:**
- Create: `tests/test_contract_replay_harness.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for tests/trust/contracts/_replay.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette


_CASSETTE_YAML = textwrap.dedent(
    """\
    adapter: git
    interaction: commit
    recorded_at: 2026-04-22T14:00:00Z
    recorder_sha: abc1234
    fixture_repo: tests/trust/contracts/fixtures/git_sandbox
    input:
      command: git commit
      args: ["-m", "hello"]
    output:
      exit_code: 0
      stdout: "[main deadbeef] hello\\n"
      stderr: ""
    normalizers:
      - sha:short
    """
)


@pytest.mark.asyncio
async def test_replay_passes_when_fake_matches_with_normalizer(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        # Different SHA, but normalizer collapses it.
        return FakeOutput(exit_code=0, stdout="[main cafebabe] hello\n", stderr="")

    await replay_cassette(path, fake)


@pytest.mark.asyncio
async def test_replay_fails_on_exit_code_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        return FakeOutput(exit_code=1, stdout="[main deadbeef] hello\n", stderr="")

    with pytest.raises(AssertionError, match="exit_code mismatch"):
        await replay_cassette(path, fake)


@pytest.mark.asyncio
async def test_replay_fails_on_stdout_body_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        return FakeOutput(exit_code=0, stdout="[main deadbeef] goodbye\n", stderr="")

    with pytest.raises(AssertionError, match="stdout drift"):
        await replay_cassette(path, fake)


def test_list_cassettes_is_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("x")
    (tmp_path / "a.yaml").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    out = list_cassettes(tmp_path)
    assert [p.name for p in out] == ["a.yaml", "b.yaml"]
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_replay_harness.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract_replay_harness.py
git commit -m "test(trust): unit test replay harness"
```

---

## Task 6: `test_fake_github_contract.py` + seed cassettes

**Files:**
- Create: `tests/trust/contracts/test_fake_github_contract.py`
- Create: `tests/trust/contracts/cassettes/github/pr_create.yaml`
- Create: `tests/trust/contracts/cassettes/github/issue_list.yaml`
- Create: `tests/trust/contracts/cassettes/github/pr_merge.yaml`

Three initial cassettes exercise the `create_pr`, `list_issues_by_label`, and `merge_pr` surface on `FakeGitHub` (see `tests/scenarios/fakes/fake_github.py:275-367`). The cassettes are recorded against `T-rav-Hydra-Ops/hydraflow-contracts-sandbox` via `gh` CLI and then hand-trimmed so the fake's deterministic output matches after normalizers.

- [ ] **Step 1: Record the real-side cassettes**

The engineer runs each command below against the sandbox repo (Task 0) and captures stdout/stderr/exit code into the YAML files. For `pr_create.yaml`:

```bash
cd /tmp/hydraflow-contracts-sandbox
git checkout -b contract/pr-create-$(date +%s)
echo "test $(date +%s)" >> FIXTURE.md
git add FIXTURE.md
git commit -m "test: contract record"
git push -u origin HEAD
gh pr create --title "contract record" --body "cassette seed" --base main \
    > /tmp/pr_create.stdout 2> /tmp/pr_create.stderr
echo "exit=$?"
```

Translate the captured outputs into `pr_create.yaml`:

```yaml
adapter: github
interaction: pr_create
recorded_at: "2026-04-22T14:07:03Z"  # Use current UTC timestamp when recording
recorder_sha: "__REPLACE_WITH_RECORDER_HEAD_SHA__"  # git rev-parse --short HEAD in HydraFlow repo
fixture_repo: T-rav-Hydra-Ops/hydraflow-contracts-sandbox
input:
  command: create_pr
  args:
    - "__issue_number_placeholder__"
    - "contract-branch"
  stdin: null
  env: {}
output:
  exit_code: 0
  stdout: "https://github.com/T-rav-Hydra-Ops/hydraflow-contracts-sandbox/pull/<PR_NUMBER>\n"
  stderr: ""
normalizers:
  - pr_number
```

Note: this cassette tests the *scenario-ring fake's own surface*, not the raw `gh` subprocess. The test file (Step 3) calls `FakeGitHub.create_pr(...)` with a synthesized issue object and compares the `url` field on the returned `PRInfo` to the cassette stdout. This matches §4.2's "feed the cassette's input into the corresponding fake" contract: the `command` field is the fake's method name, not a shell command.

Record `issue_list.yaml` analogously via `gh issue list --label test --json number,title,body,updatedAt` against the sandbox repo (seed 1–2 issues first). Record `pr_merge.yaml` via `gh pr merge --auto --squash` after the pr_create step lands. Exact content depends on what the sandbox returns on record day; the key invariant is that the normalized stdout matches what `FakeGitHub` emits when fed the same inputs.

- [ ] **Step 2: Write `test_fake_github_contract.py`**

```python
"""Contract tests: FakeGitHub output must match recorded gh-CLI cassettes.

Spec §4.2. Replay-side gate only — the refresh side lives in
src/contract_refresh_loop.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import IssueFactory
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "github"


async def _invoke_fake_github(cassette: Cassette) -> FakeOutput:
    """Dispatch the cassette input through FakeGitHub's matching method."""
    fake = FakeGitHub()
    method = cassette.input.command
    args = cassette.input.args

    if method == "create_pr":
        issue = IssueFactory.create(number=int(args[0]))
        pr_info = await fake.create_pr(issue, branch=str(args[1]))
        stdout = f"{pr_info.url}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_issues_by_label":
        # Seed enough issues for the cassette. Seeded shape is captured in
        # the cassette's fixture_repo pairing — the real gh listing returns
        # the same set we pre-seeded against the sandbox.
        fake.add_issue(
            number=1, title="t1", body="b1", labels=[str(args[0])]
        )
        await fake.list_issues_by_label(str(args[0]))
        # stdout shape: gh CLI returns JSON lines — build equivalent payload.
        stdout = '[{"number":1,"title":"t1","body":"b1","updated_at":"<ISO8601>"}]\n'
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "merge_pr":
        fake.add_pr(number=int(args[0]), issue_number=1, branch="b")
        merged = await fake.merge_pr(int(args[0]))
        assert merged, "FakeGitHub.merge_pr unexpectedly returned False"
        stdout = f"merged pull request https://github.com/_/_/pull/{args[0]}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    msg = f"FakeGitHub has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_github_matches_cassette(cassette_path: Path) -> None:
    await replay_cassette(cassette_path, _invoke_fake_github)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
```

- [ ] **Step 3: Run the contract tests**

Run: `PYTHONPATH=src uv run pytest tests/trust/contracts/test_fake_github_contract.py -v`
Expected: PASS for all seeded cassettes. If a cassette fails after recording, inspect the `apply_normalizers` output — the normalizer list on the cassette may need a new entry or the fake's method return shape needs a fixup.

- [ ] **Step 4: Commit**

```bash
git add tests/trust/contracts/test_fake_github_contract.py \
        tests/trust/contracts/cassettes/github/
git commit -m "test(trust): FakeGitHub contract test + seed cassettes"
```

---

## Task 7: `test_fake_git_contract.py` + fixture repo

**Files:**
- Create: `tests/trust/contracts/fixtures/git_sandbox/README.md`
- Create: `tests/trust/contracts/fixtures/git_sandbox/file.txt`
- Create: `tests/trust/contracts/test_fake_git_contract.py`
- Create: `tests/trust/contracts/cassettes/git/worktree_add.yaml`
- Create: `tests/trust/contracts/cassettes/git/commit.yaml`
- Create: `tests/trust/contracts/cassettes/git/rev_parse_head.yaml`

- [ ] **Step 1: Seed the fixture repo contents**

The fixture repo is *not* an initialized git repo on disk (that would confuse the surrounding HydraFlow repo). It's just tracked files that the record-side can `cp -r` to a scratch tmp dir, `git init`, and operate against. Write:

```
tests/trust/contracts/fixtures/git_sandbox/README.md
```

Content:

```
# Git sandbox fixture

Source files copied into a scratch dir by ContractRefreshLoop's recorder.
DO NOT run git commands directly against this directory.
```

```
tests/trust/contracts/fixtures/git_sandbox/file.txt
```

Content (single line):

```
fixture line 1
```

- [ ] **Step 2: Record seed cassettes by running real git against a tmp copy**

Engineer runs:

```bash
SCRATCH=$(mktemp -d)
cp -r tests/trust/contracts/fixtures/git_sandbox/* "$SCRATCH/"
cd "$SCRATCH"
git init -q
git add -A
git -c user.email=x@y -c user.name=x commit -q -m "initial"
git rev-parse HEAD
```

Capture outputs into the three YAML cassettes. For `commit.yaml`:

```yaml
adapter: git
interaction: commit
recorded_at: "2026-04-22T14:00:00Z"
recorder_sha: "__REPLACE_WITH_RECORDER_HEAD_SHA__"
fixture_repo: tests/trust/contracts/fixtures/git_sandbox
input:
  command: commit
  args:
    - "initial"
  stdin: null
  env: {}
output:
  exit_code: 0
  stdout: ""    # FakeGit.commit returns a sha string, not stdout. Encode in the return value instead — the invoker serializes the sha into stdout.
  stderr: ""
normalizers:
  - sha:short
```

The `commit` method on `FakeGit` (see `tests/scenarios/fakes/fake_git.py:48-54`) returns a sha string. The test harness invoker below serializes that sha into `stdout` so the schema shape stays uniform across adapters.

- [ ] **Step 3: Write `test_fake_git_contract.py`**

```python
"""Contract tests: FakeGit output must match recorded git-CLI cassettes."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.fake_git import FakeGit
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "git"


async def _invoke_fake_git(cassette: Cassette) -> FakeOutput:
    fake = FakeGit()
    method = cassette.input.command
    args = cassette.input.args

    # Every method operates on a path in the fake's in-memory worktree map.
    cwd = Path("/sandbox")

    if method == "worktree_add":
        await fake.worktree_add(cwd, branch=str(args[0]), new_branch=True)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "commit":
        sha = await fake.commit(cwd, message=str(args[0]))
        # Emit a normalized git-like confirmation line so the cassette shape
        # matches real `git commit` output after `sha:short` normalizer.
        return FakeOutput(
            exit_code=0,
            stdout=f"[main {sha[:7]}] {args[0]}\n",
            stderr="",
        )

    if method == "rev_parse_head":
        # Seed a commit so rev_parse returns something non-zero.
        await fake.commit(cwd, message="seed")
        sha = await fake.rev_parse(cwd, "HEAD")
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    msg = f"FakeGit has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_git_matches_cassette(cassette_path: Path) -> None:
    await replay_cassette(cassette_path, _invoke_fake_git)


def test_cassette_directory_not_empty() -> None:
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
```

- [ ] **Step 4: Run the contract tests**

Run: `PYTHONPATH=src uv run pytest tests/trust/contracts/test_fake_git_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/trust/contracts/fixtures/git_sandbox/ \
        tests/trust/contracts/test_fake_git_contract.py \
        tests/trust/contracts/cassettes/git/
git commit -m "test(trust): FakeGit contract test + fixture repo + seed cassettes"
```

---

## Task 8: `test_fake_docker_contract.py` + seed cassettes

**Files:**
- Create: `tests/trust/contracts/test_fake_docker_contract.py`
- Create: `tests/trust/contracts/cassettes/docker/run_alpine_echo.yaml`
- Create: `tests/trust/contracts/cassettes/docker/run_alpine_exit_nonzero.yaml`

`FakeDocker.run_agent` (see `tests/scenarios/fakes/fake_docker.py:86-124`) is an async iterator yielding events, not a subprocess that prints to stdout. For the contract test, we materialize the yielded events into a JSON Lines-shaped stdout block so the cassette schema (exit_code/stdout/stderr) still fits.

- [ ] **Step 1: Record two seed cassettes**

For `run_alpine_echo.yaml`, engineer records against real docker:

```bash
docker run --rm alpine:3.19 echo "hello"
# stdout: hello
# exit: 0
```

Translate into cassette:

```yaml
adapter: docker
interaction: run_alpine_echo
recorded_at: "2026-04-22T14:00:00Z"
recorder_sha: "__REPLACE_WITH_RECORDER_HEAD_SHA__"
fixture_repo: alpine:3.19
input:
  command: run_agent
  args:
    - "alpine:3.19"
    - "echo"
    - "hello"
  stdin: null
  env: {}
output:
  exit_code: 0
  stdout: '{"type": "result", "success": true, "exit_code": 0}\n'
  stderr: ""
normalizers: []
```

`run_alpine_exit_nonzero.yaml` exercises the fault-injection path by scripting `fail_next(kind="exit_nonzero")` and running the same container:

```yaml
adapter: docker
interaction: run_alpine_exit_nonzero
recorded_at: "2026-04-22T14:00:00Z"
recorder_sha: "__REPLACE_WITH_RECORDER_HEAD_SHA__"
fixture_repo: alpine:3.19
input:
  command: run_agent_with_fault
  args:
    - "exit_nonzero"
  stdin: null
  env: {}
output:
  exit_code: 1
  stdout: '{"type": "result", "success": false, "exit_code": 1}\n'
  stderr: ""
normalizers: []
```

Note: the real-side recorder for the fault path runs a container that actually exits 1 (e.g. `docker run --rm alpine:3.19 false`) and flattens the result into the same single-line JSON event — the fake's behavior is a simulation of the real exit signal, not a 1:1 replay.

- [ ] **Step 2: Write `test_fake_docker_contract.py`**

```python
"""Contract tests: FakeDocker events must match docker-cli cassettes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.fakes.fake_docker import FakeDocker
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "docker"


async def _collect_events(iterator: Any) -> list[dict[str, Any]]:
    events = []
    async for event in await iterator:
        events.append(event)
    return events


async def _invoke_fake_docker(cassette: Cassette) -> FakeOutput:
    fake = FakeDocker()
    method = cassette.input.command
    args = cassette.input.args

    if method == "run_agent":
        image = args[0]
        cmd = list(args[1:])
        # Script a success event for a fresh container run.
        fake.script_run([{"type": "result", "success": True, "exit_code": 0}])
        events = await _collect_events(
            fake.run_agent(command=[image, *cmd])
        )
        exit_code = events[-1]["exit_code"]
        stdout = "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n"
        return FakeOutput(exit_code=exit_code, stdout=stdout, stderr="")

    if method == "run_agent_with_fault":
        fault = args[0]
        fake.fail_next(kind=fault)  # type: ignore[arg-type]
        events = await _collect_events(fake.run_agent(command=["alpine:3.19"]))
        exit_code = events[-1]["exit_code"]
        stdout = "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n"
        return FakeOutput(exit_code=exit_code, stdout=stdout, stderr="")

    msg = f"FakeDocker has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_docker_matches_cassette(cassette_path: Path) -> None:
    await replay_cassette(cassette_path, _invoke_fake_docker)


def test_cassette_directory_not_empty() -> None:
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
```

- [ ] **Step 3: Run the contract tests**

Run: `PYTHONPATH=src uv run pytest tests/trust/contracts/test_fake_docker_contract.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/trust/contracts/test_fake_docker_contract.py \
        tests/trust/contracts/cassettes/docker/
git commit -m "test(trust): FakeDocker contract test + seed cassettes"
```

---

## Task 9: `test_fake_llm_contract.py` + stream samples

**Files:**
- Create: `tests/trust/contracts/test_fake_llm_contract.py`
- Create: `tests/trust/contracts/claude_streams/stream_001_list_primes.jsonl`
- Create: `tests/trust/contracts/claude_streams/stream_002_with_read_tool.jsonl`
- Create: `tests/trust/contracts/claude_streams/stream_003_with_thinking.jsonl`

Unlike `FakeGitHub`/`FakeGit`/`FakeDocker`, `FakeLLM` is *not* a subprocess stand-in — it returns scripted results via `_ScriptedRunner`. The real dialect we guard here is the `claude ... --output-format stream-json` *wire format* consumed by `src/stream_parser.py:StreamParser`. The cassette side is a raw `.jsonl` of real Claude stream events; the replay side feeds them line-by-line into `StreamParser.parse()` and asserts no crash + at least one non-empty display. This matches spec §4.2 "FakeLLM is different — replay side asserts that `src/stream_parser.py`'s parser consumes every sample without error and emits the expected tool-use / text-block boundaries."

- [ ] **Step 1: Record `stream_001_list_primes.jsonl`**

Engineer runs (requires a logged-in `claude` CLI):

```bash
claude -p "List the first three primes. Use no tools." \
    --output-format stream-json --verbose \
    > tests/trust/contracts/claude_streams/stream_001_list_primes.jsonl
```

Expected contents: a sequence of JSON objects on separate lines — typically a `session` opener, one or more `assistant` events with text blocks, and a final `result` event. Do NOT hand-edit; the file IS the cassette.

- [ ] **Step 2: Record `stream_002_with_read_tool.jsonl`**

A prompt that elicits a tool call:

```bash
claude -p "Read /etc/hostname and tell me what it says. Just use the Read tool once." \
    --output-format stream-json --verbose \
    > tests/trust/contracts/claude_streams/stream_002_with_read_tool.jsonl
```

Exercises the `tool_use` and `tool_result` branches in `_parse_assistant` / `_parse_user` (`src/stream_parser.py:299-347`).

- [ ] **Step 3: Record `stream_003_with_thinking.jsonl`**

If thinking blocks are exposed in the stream for the installed Claude model, a prompt that uses extended thinking. If not available in the current CLI, record a second short non-tool prompt — e.g. `"Say hello and nothing else."` — so we still have three shape-distinct samples. Name the file regardless.

- [ ] **Step 4: Write `test_fake_llm_contract.py`**

```python
"""Contract tests: StreamParser must consume recorded Claude streams cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest

from stream_parser import StreamParser

_STREAM_DIR = Path(__file__).parent / "claude_streams"


def _list_streams() -> list[Path]:
    return sorted(_STREAM_DIR.glob("*.jsonl"))


@pytest.mark.parametrize(
    "stream_path",
    _list_streams(),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
def test_stream_parser_consumes_sample(stream_path: Path) -> None:
    """StreamParser.parse must not raise on any line and must emit ≥1 non-empty display."""
    parser = StreamParser()
    non_empty_displays = 0
    had_result = False
    for raw_line in stream_path.read_text().splitlines():
        if not raw_line.strip():
            continue
        display, result = parser.parse(raw_line)
        if display:
            non_empty_displays += 1
        if result is not None:
            had_result = True
    assert non_empty_displays > 0, (
        f"{stream_path.name}: parser produced no display text — sample is empty or "
        f"parser stopped recognizing assistant/user/result event types."
    )
    assert had_result, (
        f"{stream_path.name}: no final result event — sample is truncated or the "
        f"Claude stream-json schema dropped the result event type."
    )


def test_stream_samples_directory_not_empty() -> None:
    assert _list_streams(), f"{_STREAM_DIR} has no *.jsonl samples; seed at least one."
```

- [ ] **Step 5: Run the contract tests**

Run: `PYTHONPATH=src uv run pytest tests/trust/contracts/test_fake_llm_contract.py -v`
Expected: PASS for all three samples. If a sample fails, fix `StreamParser` (not the sample) — a failing sample IS the signal that the stream-json protocol drifted.

- [ ] **Step 6: Commit**

```bash
git add tests/trust/contracts/test_fake_llm_contract.py \
        tests/trust/contracts/claude_streams/
git commit -m "test(trust): FakeLLM / StreamParser contract test + stream samples"
```

---

## Task 10: `make trust-contracts` target + extend `make trust` + CI

**Files:**
- Modify: `Makefile:218` (new target after scenario-loops)
- Modify: `.github/workflows/rc-promotion-scenario.yml:94` (new job after scenario)

Plan 1 (adversarial) introduces `make trust-adversarial` and `make trust`. Because that plan may land before OR after this one, this task defines `make trust-contracts` idempotently and defines/updates `make trust` to include contracts — overwriting any earlier Plan-1 definition. Whichever plan lands second is responsible for the final merged target definition.

- [ ] **Step 1: Add `trust-contracts` target**

In `Makefile`, immediately after the `scenario-loops` target (line 218, the blank line after `@echo "$(GREEN)Scenario loop tests passed$(RESET)"`), insert:

```makefile
trust-contracts: deps
	@echo "$(BLUE)Running fake contract tests...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/trust/contracts/ -v --timeout=60
	@echo "$(GREEN)Contract tests passed$(RESET)"

trust: trust-adversarial trust-contracts
	@echo "$(GREEN)All trust gates passed$(RESET)"
```

If `trust-adversarial` does not yet exist in the Makefile (Plan 1 hasn't landed), add a placeholder target above `trust-contracts` so `make trust` doesn't error:

```makefile
trust-adversarial: deps
	@echo "$(YELLOW)trust-adversarial not yet implemented — Plan 1 adds this target$(RESET)"
	@echo "$(GREEN)skipping$(RESET)"
```

When Plan 1 lands, it replaces the placeholder with the real adversarial target.

- [ ] **Step 2: Add `trust` job to `rc-promotion-scenario.yml`**

After the existing `scenario-browser` job (line 135, end of file), append:

```yaml

  trust:
    name: Trust Gates
    needs: gate
    if: needs.gate.outputs.should_run == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.gate.outputs.pr_ref }}
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Trust gates (adversarial + contracts)
        run: make trust
```

- [ ] **Step 3: Verify locally**

Run: `make trust-contracts`
Expected: the three contract test modules + the schema + replay harness unit tests all pass. Duration: < 30 seconds on a dev machine (no real `gh`/`git`/`docker` calls — the harness replays against the scenario-ring fakes only).

- [ ] **Step 4: Commit**

```bash
git add Makefile .github/workflows/rc-promotion-scenario.yml
git commit -m "feat(trust): make trust-contracts target + RC workflow wiring"
```

---

## Task 11: `ContractRefreshLoop` skeleton

**Files:**
- Create: `src/contract_refresh_loop.py`

Follow the pattern of `src/repo_wiki_loop.py:129-171` — a `BaseBackgroundLoop` subclass with `worker_name="contract_refresh"`, a `_get_default_interval` reading `config.contract_refresh_interval`, and a skeleton `_do_work` that currently does nothing. Later tasks add the recording, diff, PR, and escalation logic.

- [ ] **Step 1: Write the skeleton**

```python
"""Background worker loop — weekly cassette refresh for fake contract tests.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "ContractRefreshLoop — full caretaker (refresh + auto-repair)".

On each cycle:
1. Re-record cassettes against live gh, git, docker, claude.
2. Diff against committed cassettes. No diff → no-op.
3. Open a refresh PR with the new cassettes.
4. Replay the new cassettes against the scenario fakes.
   - Pass  → PR flows through standard auto-merge path.
   - Fail  → file `fake-drift` companion issue; factory repairs the fake.
5. On stream-parser errors, file `stream-protocol-drift`; factory repairs
   src/stream_parser.py.
6. Per-adapter 3-attempt repair tracker; exhaustion → `hitl-escalation`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.contract_refresh_loop")


@dataclass(frozen=True)
class AdapterPlan:
    """Per-adapter recording configuration."""

    name: str  # "github" | "git" | "docker" | "claude"
    cassette_dir_relpath: str  # under repo_root


ADAPTER_PLANS: tuple[AdapterPlan, ...] = (
    AdapterPlan(name="github", cassette_dir_relpath="tests/trust/contracts/cassettes/github"),
    AdapterPlan(name="git", cassette_dir_relpath="tests/trust/contracts/cassettes/git"),
    AdapterPlan(name="docker", cassette_dir_relpath="tests/trust/contracts/cassettes/docker"),
    AdapterPlan(name="claude", cassette_dir_relpath="tests/trust/contracts/claude_streams"),
)


class ContractRefreshLoop(BaseBackgroundLoop):
    """Weekly refresh of fake-contract cassettes with autonomous repair dispatch."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        prs: PRManager,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="contract_refresh", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.contract_refresh_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # Filled in by Tasks 13–18. Skeleton returns a no-op marker.
        return {"adapters_refreshed": 0, "adapters_drifted": 0}
```

- [ ] **Step 2: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): skeleton BaseBackgroundLoop subclass"
```

---

## Task 12: Unit-test loop construction + tick callability

**Files:**
- Create: `tests/test_contract_refresh_loop.py`

Task 12 establishes the test harness for this loop; Task 21 extends it with the end-to-end drift scenarios. Both tasks share the same file; keep a clean split by marking later tests with `# Added in Task 21`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for ContractRefreshLoop."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from contract_refresh_loop import ContractRefreshLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True) -> tuple[ContractRefreshLoop, asyncio.Event]:
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        contract_refresh_interval=604800,
        max_fake_repair_attempts=3,
    )
    prs = MagicMock()
    state = MagicMock()
    loop = ContractRefreshLoop(
        config=deps.config,
        deps=deps.loop_deps,
        prs=prs,
        state=state,
    )
    return loop, deps.stop_event


class TestContractRefreshLoopConstruction:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _ = _make_loop(tmp_path)
        assert loop._worker_name == "contract_refresh"

    def test_default_interval_is_one_week(self, tmp_path: Path) -> None:
        loop, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == 604800


class TestContractRefreshLoopTick:
    @pytest.mark.asyncio
    async def test_skeleton_tick_returns_zero_adapters(self, tmp_path: Path) -> None:
        loop, _ = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result == {"adapters_refreshed": 0, "adapters_drifted": 0}
```

- [ ] **Step 2: Add `contract_refresh_interval` + `max_fake_repair_attempts` to ConfigFactory**

The tests above reference two unknown keys. Before Task 19 lands them in `src/config.py`, add passthroughs to `tests/helpers.py:ConfigFactory.create` so the test harness compiles. In `tests/helpers.py`, find the ConfigFactory signature and add these two parameters with the same defaults as the real Field will use. (Once Task 19 lands the real config fields, these passthroughs continue to work — they just forward into `HydraFlowConfig`.)

Locate `ConfigFactory.create` (around `tests/helpers.py:209`) and add to the keyword args list:

```python
        contract_refresh_interval: int = 604800,
        max_fake_repair_attempts: int = 3,
```

and wire into the constructed config (after the existing `**kwargs` or equivalent). Because `ConfigFactory` is used widely, the minimum surface edit is just exposing these two parameters and forwarding them.

- [ ] **Step 3: Run the test**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_refresh_loop.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_contract_refresh_loop.py tests/helpers.py
git commit -m "test(contract_refresh_loop): construction + tick callability"
```

---

## Task 13: Recording subroutines — real gh/git/docker/claude

**Files:**
- Modify: `src/contract_refresh_loop.py` (extend the file written in Task 11)

Each `_record_<adapter>` method runs the real CLI against its fixture target and returns `(cassette_slug, new_yaml_bytes)` for one or more cassettes. Failures bubble up as `RuntimeError` — the caller (Task 14) decides whether they're drift or infrastructure bugs.

- [ ] **Step 1: Extend `src/contract_refresh_loop.py`**

After the `_do_work` skeleton, add helpers. The full appended block:

```python
    # --- Recording subroutines (Task 13) ---

    async def _record_github(self) -> dict[str, bytes]:
        """Run `gh` against the contracts sandbox; return {slug: yaml_bytes}."""
        import subprocess

        results: dict[str, bytes] = {}
        sandbox_repo = "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"

        # pr_list: stable read-only op exercises gh output shape.
        proc = await _run_cli(["gh", "pr", "list", "--repo", sandbox_repo, "--json", "number,title,state"])
        results["pr_list"] = _build_yaml_cassette(
            adapter="github",
            interaction="pr_list",
            fixture_repo=sandbox_repo,
            command="list_issues_by_label",  # closest fake-side equivalent
            args=[],
            exit_code=proc["exit_code"],
            stdout=proc["stdout"],
            stderr=proc["stderr"],
            normalizers=["pr_number", "timestamps.ISO8601", "sha:short"],
        )
        return results

    async def _record_git(self) -> dict[str, bytes]:
        """Run `git` against a scratch copy of the fixture sandbox."""
        import shutil
        import tempfile

        results: dict[str, bytes] = {}
        fixture_src = self._config.repo_root / "tests/trust/contracts/fixtures/git_sandbox"
        scratch = Path(tempfile.mkdtemp(prefix="contract_git_"))
        try:
            shutil.copytree(fixture_src, scratch, dirs_exist_ok=True)
            await _run_cli(["git", "-C", str(scratch), "init", "-q"])
            await _run_cli(["git", "-C", str(scratch), "add", "-A"])
            proc = await _run_cli(
                [
                    "git", "-C", str(scratch),
                    "-c", "user.email=contract@refresh.local",
                    "-c", "user.name=contract-refresh",
                    "commit", "-q", "-m", "initial",
                ]
            )
            results["commit"] = _build_yaml_cassette(
                adapter="git",
                interaction="commit",
                fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
                command="commit",
                args=["initial"],
                exit_code=proc["exit_code"],
                stdout=proc["stdout"],
                stderr=proc["stderr"],
                normalizers=["sha:short"],
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return results

    async def _record_docker(self) -> dict[str, bytes]:
        """Run `docker run` against the pinned alpine image."""
        results: dict[str, bytes] = {}
        proc = await _run_cli(["docker", "run", "--rm", "alpine:3.19", "echo", "hello"])
        results["run_alpine_echo"] = _build_yaml_cassette(
            adapter="docker",
            interaction="run_alpine_echo",
            fixture_repo="alpine:3.19",
            command="run_agent",
            args=["alpine:3.19", "echo", "hello"],
            exit_code=proc["exit_code"],
            stdout='{"type": "result", "success": true, "exit_code": 0}\n',  # fake shape
            stderr="",
            normalizers=[],
        )
        return results

    async def _record_claude(self) -> dict[str, bytes]:
        """Run `claude` against the stable prompt; return {slug: jsonl_bytes}."""
        prompt = "List the first three primes. Use no tools."
        proc = await _run_cli(
            ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
        )
        # Claude streams are stored as raw .jsonl, NOT YAML.
        return {"stream_001_list_primes": proc["stdout"].encode("utf-8")}
```

And add these two module-level helpers above `class ContractRefreshLoop`:

```python
async def _run_cli(argv: list[str]) -> dict[str, Any]:
    """Run *argv* as a subprocess; return dict with exit_code, stdout, stderr."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return {
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "stdout": stdout_b.decode("utf-8", errors="replace"),
        "stderr": stderr_b.decode("utf-8", errors="replace"),
    }


def _build_yaml_cassette(
    *,
    adapter: str,
    interaction: str,
    fixture_repo: str,
    command: str,
    args: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    normalizers: list[str],
) -> bytes:
    """Serialize a single cassette to YAML bytes using the canonical schema."""
    import subprocess
    from datetime import UTC, datetime

    import yaml

    recorder_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() or "unknown"

    payload = {
        "adapter": adapter,
        "interaction": interaction,
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "recorder_sha": recorder_sha,
        "fixture_repo": fixture_repo,
        "input": {"command": command, "args": list(args), "stdin": None, "env": {}},
        "output": {"exit_code": exit_code, "stdout": stdout, "stderr": stderr},
        "normalizers": list(normalizers),
    }
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False).encode("utf-8")
```

Add the missing `from pathlib import Path` to the imports if not already present.

- [ ] **Step 2: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): record real gh/git/docker/claude outputs"
```

---

## Task 14: Diff detection against committed cassettes

**Files:**
- Modify: `src/contract_refresh_loop.py`

Compare each newly-recorded cassette byte-wise against the committed copy. No diff → skip. Drift → record the path pair for Task 15's PR.

- [ ] **Step 1: Add `_diff_against_committed` + update `_do_work`**

Append to `ContractRefreshLoop`:

```python
    # --- Diff detection (Task 14) ---

    def _diff_against_committed(
        self, adapter: str, slug: str, new_bytes: bytes
    ) -> bytes | None:
        """Return *new_bytes* if it differs from the committed file, else None."""
        suffix = ".jsonl" if adapter == "claude" else ".yaml"
        plan = next(p for p in ADAPTER_PLANS if p.name == adapter)
        committed_path = (
            self._config.repo_root / plan.cassette_dir_relpath / f"{slug}{suffix}"
        )
        if not committed_path.exists():
            return new_bytes  # brand-new cassette is "drift"
        existing = committed_path.read_bytes()
        if existing == new_bytes:
            return None
        return new_bytes
```

Replace the skeleton `_do_work` with:

```python
    async def _do_work(self) -> dict[str, Any] | None:
        record_fns = {
            "github": self._record_github,
            "git": self._record_git,
            "docker": self._record_docker,
            "claude": self._record_claude,
        }

        drifted: dict[str, dict[str, bytes]] = {}
        refreshed = 0
        for adapter in ("github", "git", "docker", "claude"):
            try:
                recordings = await record_fns[adapter]()
            except Exception:
                logger.exception("contract_refresh: recording %s failed", adapter)
                continue
            per_adapter_drift: dict[str, bytes] = {}
            for slug, new_bytes in recordings.items():
                diff = self._diff_against_committed(adapter, slug, new_bytes)
                if diff is not None:
                    per_adapter_drift[slug] = diff
            if per_adapter_drift:
                drifted[adapter] = per_adapter_drift
                refreshed += len(per_adapter_drift)

        if not drifted:
            return {"adapters_refreshed": 0, "adapters_drifted": 0}

        # PR creation + replay-gate + escalation wired in Tasks 15–18.
        return {"adapters_refreshed": refreshed, "adapters_drifted": len(drifted)}
```

- [ ] **Step 2: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): diff new recordings against committed cassettes"
```

---

## Task 15: Refresh PR via `open_automated_pr_async`

**Files:**
- Modify: `src/contract_refresh_loop.py`

Write the drifted cassettes to their committed paths, then call `open_automated_pr_async` with `auto_merge=True` and `raise_on_failure=False`. The PR title follows the `contract-refresh/YYYY-MM-DD` convention from spec §4.2 step 3.

- [ ] **Step 1: Add `_write_drifted_cassettes` + `_open_refresh_pr`**

```python
    # --- PR creation (Task 15) ---

    def _write_drifted_cassettes(
        self, drifted: dict[str, dict[str, bytes]]
    ) -> list[Path]:
        """Write each drifted cassette to its committed path; return the paths."""
        written: list[Path] = []
        for adapter, slugs in drifted.items():
            plan = next(p for p in ADAPTER_PLANS if p.name == adapter)
            suffix = ".jsonl" if adapter == "claude" else ".yaml"
            adapter_dir = self._config.repo_root / plan.cassette_dir_relpath
            adapter_dir.mkdir(parents=True, exist_ok=True)
            for slug, payload in slugs.items():
                path = adapter_dir / f"{slug}{suffix}"
                path.write_bytes(payload)
                written.append(path)
        return written

    async def _open_refresh_pr(
        self, written: list[Path], drifted: dict[str, dict[str, bytes]]
    ) -> str:
        """Open the contract-refresh PR. Returns branch name."""
        from datetime import UTC, datetime

        from auto_pr import open_automated_pr_async

        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        branch = f"contract-refresh/{stamp}"
        adapters = ", ".join(sorted(drifted.keys()))
        body_lines = [
            "Automated cassette refresh by `ContractRefreshLoop`.",
            "",
            f"Adapters drifted: **{adapters}**.",
            "",
            "Per-adapter slugs:",
        ]
        for adapter, slugs in sorted(drifted.items()):
            body_lines.append(f"- `{adapter}`: " + ", ".join(sorted(slugs.keys())))
        body_lines.append("")
        body_lines.append(
            "Replay gate runs after merge; on replay-side failure a "
            "`fake-drift` issue routes repair through the factory."
        )

        result = await open_automated_pr_async(
            repo_root=self._config.repo_root,
            branch=branch,
            files=written,
            pr_title=f"contract-refresh: {stamp} ({adapters})",
            pr_body="\n".join(body_lines),
            commit_message=f"chore(contracts): refresh cassettes — {adapters}",
            auto_merge=True,
            raise_on_failure=False,
            labels=["contract-refresh", "auto-merge"],
        )
        if result.status != "opened" and result.status != "merged":
            logger.warning(
                "contract_refresh: PR creation returned status=%s error=%s",
                result.status, getattr(result, "error", None),
            )
        return branch
```

- [ ] **Step 2: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): open refresh PR for drifted cassettes"
```

---

## Task 16: Replay-gate post-refresh + file `fake-drift` companion issue

**Files:**
- Modify: `src/contract_refresh_loop.py`

Invoke the pytest replay suite programmatically against the freshly-written cassettes via `pytest.main`. If the exit code is 0, the PR auto-merges normally — cassette-only drift. If non-zero, a fake diverged: file a `hydraflow-find` + `fake-drift` issue via `PRManager.create_issue`.

- [ ] **Step 1: Add `_run_replay_gate` + `_file_fake_drift_issue`**

```python
    # --- Replay gate + drift routing (Task 16) ---

    async def _run_replay_gate(self, adapters: list[str]) -> set[str]:
        """Run contract replay for each adapter; return set of adapters that failed."""
        import asyncio

        failed: set[str] = set()
        for adapter in adapters:
            test_module = f"tests/trust/contracts/test_fake_{adapter}_contract.py"
            if adapter == "claude":
                test_module = "tests/trust/contracts/test_fake_llm_contract.py"
            proc = await asyncio.create_subprocess_exec(
                "uv", "run", "pytest", test_module, "-v", "--timeout=60",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._config.repo_root),
                env={**self._config_env(), "PYTHONPATH": "src"},
            )
            stdout_b, stderr_b = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "contract_refresh: replay failed for %s — fake diverged\n%s\n%s",
                    adapter,
                    stdout_b.decode(errors="replace"),
                    stderr_b.decode(errors="replace"),
                )
                failed.add(adapter)
        return failed

    def _config_env(self) -> dict[str, str]:
        import os
        return {**os.environ}

    async def _file_fake_drift_issue(self, adapter: str, refresh_branch: str) -> int:
        """File a hydraflow-find issue so the factory dispatches the implementer."""
        title = f"Fake drift: {adapter} fake diverged from refreshed cassette"
        body = (
            f"`ContractRefreshLoop` refreshed the `{adapter}` cassettes on branch "
            f"`{refresh_branch}`, and the replay-side contract test now fails. "
            f"The fake in `tests/scenarios/fakes/fake_{adapter}.py` "
            f"needs to match the updated cassette.\n\n"
            f"**Repair path.** Check out the refresh branch, run\n"
            f"```\nPYTHONPATH=src uv run pytest tests/trust/contracts/test_fake_{adapter}_contract.py -v\n```\n"
            f"to see the divergence, then adjust the fake and land a fix PR on `staging`.\n\n"
            f"Escalation: after {self._config.max_fake_repair_attempts} failed attempts, "
            f"this issue will be relabeled `hitl-escalation`, `fake-repair-stuck`."
        )
        return await self._prs.create_issue(
            title=title,
            body=body,
            labels=["hydraflow-find", "fake-drift", f"adapter-{adapter}"],
        )
```

- [ ] **Step 2: Wire into `_do_work`**

Replace the last three lines of `_do_work` (from Task 14) with:

```python
        written = self._write_drifted_cassettes(drifted)
        refresh_branch = await self._open_refresh_pr(written, drifted)

        failed_adapters = await self._run_replay_gate(sorted(drifted.keys()))
        drift_issues: dict[str, int] = {}
        for adapter in failed_adapters:
            if self._exhausted(adapter):
                continue  # Task 18 handles escalation
            issue_num = await self._file_fake_drift_issue(adapter, refresh_branch)
            drift_issues[adapter] = issue_num

        return {
            "adapters_refreshed": refreshed,
            "adapters_drifted": len(drifted),
            "fakes_diverged": len(failed_adapters),
            "drift_issues_filed": list(drift_issues.values()),
        }
```

`_exhausted` is stubbed to `return False` for now; Task 18 implements the real budget check.

Add the stub:

```python
    def _exhausted(self, adapter: str) -> bool:
        """Per-adapter retry-budget check. Filled in by Task 18."""
        _ = adapter
        return False
```

- [ ] **Step 3: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): replay gate + fake-drift issue filing"
```

---

## Task 17: Stream-protocol drift handling

**Files:**
- Modify: `src/contract_refresh_loop.py`

If the freshly-recorded `claude` stream causes `StreamParser` to raise, the drift is in `src/stream_parser.py`, not in a fake. File `stream-protocol-drift` (not `fake-drift`) so the factory routes the repair to the parser.

- [ ] **Step 1: Add `_parser_accepts_stream` + branch `_file_stream_protocol_drift_issue`**

```python
    # --- Stream-protocol drift (Task 17) ---

    def _parser_accepts_stream(self, jsonl_bytes: bytes) -> bool:
        """Feed every line through StreamParser; return False on any raise."""
        from stream_parser import StreamParser

        parser = StreamParser()
        try:
            for raw_line in jsonl_bytes.decode("utf-8", errors="replace").splitlines():
                if not raw_line.strip():
                    continue
                parser.parse(raw_line)
        except Exception:
            logger.exception("contract_refresh: StreamParser raised on fresh sample")
            return False
        return True

    async def _file_stream_protocol_drift_issue(self, slug: str) -> int:
        title = f"Stream-protocol drift: StreamParser failed on {slug}"
        body = (
            f"`ContractRefreshLoop` re-recorded `{slug}.jsonl` from the `claude` "
            f"CLI, and `src/stream_parser.py:StreamParser.parse` raised on one or "
            f"more lines. The Claude stream-json schema has drifted.\n\n"
            f"**Repair path.** Inspect the new sample committed on the contract "
            f"refresh branch, extend `StreamParser` to handle the new event shape, "
            f"and land a fix PR on `staging`.\n\n"
            f"Escalation: after {self._config.max_fake_repair_attempts} failed "
            f"attempts, this issue will be relabeled `hitl-escalation`, "
            f"`stream-parser-stuck`."
        )
        return await self._prs.create_issue(
            title=title,
            body=body,
            labels=["hydraflow-find", "stream-protocol-drift"],
        )
```

- [ ] **Step 2: Wire into `_do_work`**

Inside the loop that runs `record_fns` (in `_do_work`), immediately after successful recording for `adapter == "claude"`, pre-gate each `claude` sample. Replace the `claude` branch of the per-adapter block with:

```python
            if adapter == "claude":
                bad_slugs = [
                    s for s, b in recordings.items() if not self._parser_accepts_stream(b)
                ]
                for slug in bad_slugs:
                    if not self._exhausted("claude"):
                        await self._file_stream_protocol_drift_issue(slug)
                # Still pass the drifted samples through the normal write/PR
                # path — the committed sample updates so retries see the new
                # shape once the parser fix lands.
```

- [ ] **Step 3: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): stream-protocol drift detection + issue filing"
```

---

## Task 18: Per-adapter 3-attempt escalation tracker

**Files:**
- Modify: `src/contract_refresh_loop.py`

Track per-adapter repair attempts in `StateTracker` via a small typed dict. Each time we file a `fake-drift` or `stream-protocol-drift` issue, increment the counter. When the count exceeds `config.max_fake_repair_attempts`, skip filing further issues for that adapter and instead relabel the latest open one to `hitl-escalation` + the appropriate per-class label.

- [ ] **Step 1: Add a state helper**

At the top of `src/contract_refresh_loop.py`, after `ADAPTER_PLANS`, add:

```python
_STATE_KEY_PREFIX = "contract_refresh.repair_attempts"


def _state_key(adapter: str) -> str:
    return f"{_STATE_KEY_PREFIX}.{adapter}"
```

Then extend the class with real budget tracking. Replace the stub `_exhausted` from Task 16:

```python
    def _exhausted(self, adapter: str) -> bool:
        attempts = self._get_attempts(adapter)
        return attempts >= self._config.max_fake_repair_attempts

    def _get_attempts(self, adapter: str) -> int:
        # StateTracker exposes generic get/set via to_dict / record_outcome
        # family. For a simple counter, route through the BackgroundWorkerState
        # details dict keyed on the loop's worker_name.
        existing = self._state.get_bg_worker_states().get(self._worker_name)
        if existing is None:
            return 0
        details = existing.details or {}
        return int(details.get(_state_key(adapter), 0))

    def _increment_attempts(self, adapter: str) -> int:
        from models import BackgroundWorkerState

        states = self._state.get_bg_worker_states()
        current = states.get(self._worker_name)
        details: dict[str, Any] = dict(current.details) if current and current.details else {}
        attempts = int(details.get(_state_key(adapter), 0)) + 1
        details[_state_key(adapter)] = attempts
        new_state = BackgroundWorkerState(
            name=self._worker_name,
            last_run=current.last_run if current else None,
            status=current.status if current else "ok",
            details=details,
        )
        self._state.set_bg_worker_state(self._worker_name, new_state)
        return attempts

    def _reset_attempts(self, adapter: str) -> None:
        from models import BackgroundWorkerState

        states = self._state.get_bg_worker_states()
        current = states.get(self._worker_name)
        if current is None:
            return
        details = dict(current.details) if current.details else {}
        details.pop(_state_key(adapter), None)
        self._state.set_bg_worker_state(
            self._worker_name,
            BackgroundWorkerState(
                name=self._worker_name,
                last_run=current.last_run,
                status=current.status,
                details=details,
            ),
        )
```

- [ ] **Step 2: Escalate when exhausted**

Add:

```python
    async def _escalate(self, adapter: str, *, stream: bool) -> None:
        """Relabel the most recent open drift issue to hitl-escalation."""
        label = "stream-parser-stuck" if stream else "fake-repair-stuck"
        search_label = "stream-protocol-drift" if stream else "fake-drift"
        open_issues = await self._prs.list_issues_by_label(search_label)
        # Pick the newest open issue for this adapter.
        target: dict[str, Any] | None = None
        for iss in open_issues:
            if stream or (
                f"adapter-{adapter}" in " ".join(
                    (iss.get("labels", []) if isinstance(iss.get("labels"), list) else [])
                )
            ):
                target = iss
                break
        if target is None:
            logger.warning(
                "contract_refresh: no open %s issue found to escalate for %s",
                search_label, adapter,
            )
            return
        issue_num = int(target["number"])
        await self._prs.add_labels(issue_num, ["hitl-escalation", label])
        logger.warning(
            "contract_refresh: escalated %s issue #%d to hitl-escalation/%s",
            search_label, issue_num, label,
        )
```

- [ ] **Step 3: Wire escalation into `_do_work`**

In `_do_work`, where Task 16 currently filters via `_exhausted`, extend the branch:

```python
        for adapter in failed_adapters:
            if self._exhausted(adapter):
                await self._escalate(adapter, stream=False)
                continue
            self._increment_attempts(adapter)
            issue_num = await self._file_fake_drift_issue(adapter, refresh_branch)
            drift_issues[adapter] = issue_num
```

And inside the `claude` branch from Task 17:

```python
                for slug in bad_slugs:
                    if self._exhausted("claude"):
                        await self._escalate("claude", stream=True)
                        continue
                    self._increment_attempts("claude")
                    await self._file_stream_protocol_drift_issue(slug)
```

- [ ] **Step 4: Commit**

```bash
git add src/contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): per-adapter 3-attempt escalation tracker"
```

---

## Task 19a: Five-checkpoint wiring — `service_registry.py`

**Files:**
- Modify: `src/service_registry.py:13-85` (imports)
- Modify: `src/service_registry.py:145-170` (dataclass fields)
- Modify: `src/service_registry.py:788-813` (loop instantiation)
- Modify: `src/service_registry.py:815-873` (ServiceRegistry kwargs)

- [ ] **Step 1: Add the import**

Insert near `from code_grooming_loop import CodeGroomingLoop  # noqa: TCH001` (line 22) — alphabetical placement:

```python
from contract_refresh_loop import ContractRefreshLoop
```

- [ ] **Step 2: Add the dataclass field**

Inside the `ServiceRegistry` dataclass, in the "Background loops" block (currently ending at line 168 with `retrospective_loop: RetrospectiveLoop`), add below that line:

```python
    contract_refresh_loop: ContractRefreshLoop
```

- [ ] **Step 3: Instantiate the loop**

After the `retrospective_loop = RetrospectiveLoop(...)` block ending at line 813, add:

```python
    contract_refresh_loop = ContractRefreshLoop(
        config=config,
        deps=loop_deps,
        prs=prs,
        state=state,
    )
```

- [ ] **Step 4: Pass into the `ServiceRegistry(...)` kwargs**

In the final `return ServiceRegistry(...)` call (currently ending at line 872 `retrospective_queue=retrospective_queue,`), add above the closing paren:

```python
        contract_refresh_loop=contract_refresh_loop,
```

- [ ] **Step 5: Commit**

```bash
git add src/service_registry.py
git commit -m "feat(contract_refresh_loop): wire into ServiceRegistry"
```

---

## Task 19b: Five-checkpoint wiring — `orchestrator.py`

**Files:**
- Modify: `src/orchestrator.py:138-159` (bg_loop_registry)
- Modify: `src/orchestrator.py:878-910` (loop_factories)

- [ ] **Step 1: Add to `bg_loop_registry` dict**

In the `bg_loop_registry` dict (lines 138-159), after the `"retrospective": svc.retrospective_loop,` line, add:

```python
            "contract_refresh": svc.contract_refresh_loop,
```

- [ ] **Step 2: Add to `loop_factories` list**

In the `loop_factories` list (lines 878-910), after the line `("retrospective", self._svc.retrospective_loop.run),` add:

```python
            ("contract_refresh", self._svc.contract_refresh_loop.run),
```

- [ ] **Step 3: Commit**

```bash
git add src/orchestrator.py
git commit -m "feat(contract_refresh_loop): register in orchestrator bg_loop_registry + loop_factories"
```

---

## Task 19c: Five-checkpoint wiring — `ui/src/constants.js`

**Files:**
- Modify: `src/ui/src/constants.js:252` (EDITABLE_INTERVAL_WORKERS)
- Modify: `src/ui/src/constants.js:273` (SYSTEM_WORKER_INTERVALS)
- Modify: `src/ui/src/constants.js:293-313` (BACKGROUND_WORKERS)

- [ ] **Step 1: Add to `EDITABLE_INTERVAL_WORKERS`**

Replace line 252:

```javascript
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'pr_unsticker', 'pipeline_poller', 'report_issue', 'worktree_gc', 'adr_reviewer', 'epic_sweeper', 'dependabot_merge', 'staging_promotion', 'stale_issue', 'security_patch', 'ci_monitor', 'code_grooming', 'sentry_ingest', 'retrospective', 'contract_refresh'])
```

- [ ] **Step 2: Add default interval**

In `SYSTEM_WORKER_INTERVALS` (lines 259-274), after `retrospective: 1800,` add:

```javascript
  contract_refresh: 604800,
```

- [ ] **Step 3: Add to `BACKGROUND_WORKERS` array**

Inside the `BACKGROUND_WORKERS` array (lines 293-313), before the closing `]`, append:

```javascript
  { key: 'contract_refresh', label: 'Contract Refresh', description: 'Weekly refresh of fake-contract cassettes (gh, git, docker, claude). Files fake-drift or stream-protocol-drift issues when fakes diverge from live services.', color: theme.cyan, group: 'repo_health', tags: ['quality'] },
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/src/constants.js
git commit -m "feat(contract_refresh_loop): wire into UI BACKGROUND_WORKERS"
```

---

## Task 19d: Five-checkpoint wiring — `_INTERVAL_BOUNDS`

**Files:**
- Modify: `src/dashboard_routes/_common.py:32-56`

- [ ] **Step 1: Add the bound**

After line 55 (`"retrospective": (60, 86400),`) and before the closing `}` on line 56, add:

```python
    "contract_refresh": (86400, 2419200),
```

Bounds: 1 day minimum (catches a stuck loop fast in dev), 4 weeks maximum (Plan 2 may bump default to monthly per §9 open question 1).

- [ ] **Step 2: Commit**

```bash
git add src/dashboard_routes/_common.py
git commit -m "feat(contract_refresh_loop): add interval bounds"
```

---

## Task 19e: Five-checkpoint wiring — `config.py`

**Files:**
- Modify: `src/config.py:74-175` (_ENV_INT_OVERRIDES)
- Modify: `src/config.py:1065-1099` (new Field declarations after code_grooming_interval)

- [ ] **Step 1: Add `_ENV_INT_OVERRIDES` entries**

After line 174 (`("retrospective_interval", "HYDRAFLOW_RETROSPECTIVE_INTERVAL", 1800),`) and before the closing `]` on line 175, add:

```python
    ("contract_refresh_interval", "HYDRAFLOW_CONTRACT_REFRESH_INTERVAL", 604800),
    ("max_fake_repair_attempts", "HYDRAFLOW_MAX_FAKE_REPAIR_ATTEMPTS", 3),
```

- [ ] **Step 2: Add the `Field` declarations**

After the `code_grooming_interval` Field (ending at line 1070) and before the `# Repo wiki` comment on line 1072, add:

```python

    # Contract refresh
    contract_refresh_interval: int = Field(
        default=604800,
        ge=86400,
        le=2419200,
        description="Seconds between ContractRefreshLoop cycles (default 7 days)",
    )
    max_fake_repair_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Max per-adapter attempts before ContractRefreshLoop escalates a "
            "fake-drift or stream-protocol-drift issue to hitl-escalation."
        ),
    )
```

- [ ] **Step 3: Verify config loads**

Run: `PYTHONPATH=src uv run python -c "from config import HydraFlowConfig; c = HydraFlowConfig(); print(c.contract_refresh_interval, c.max_fake_repair_attempts)"`
Expected: `604800 3`.

- [ ] **Step 4: Commit**

```bash
git add src/config.py
git commit -m "feat(contract_refresh_loop): add contract_refresh_interval + max_fake_repair_attempts config"
```

---

## Task 20: Per-loop telemetry emission (§4.11 point 3)

**Files:**
- Modify: `src/contract_refresh_loop.py` (wrap `_run_cli` in Task 13's helper block)
- Modify: `tests/test_contract_refresh_loop.py` (new unit test class)

Spec §4.11 point 3 requires every new trust loop to emit telemetry to `src/trace_collector.py` on every subprocess invocation, tagged with the action shape `{"kind": "loop", "loop": "ContractRefreshLoop"}`, so the per-loop cost dashboard and per-issue waterfall view surface the loop as a line item. The loop itself does NOT call the LLM — the dispatched implementer does, and those calls are tagged separately by the standard pipeline via `src/prompt_telemetry.py` (no action in this plan; §4.2 wiring section explicitly excludes the loop from LLM telemetry).

This task adds inline emission in `_run_cli` (chosen over the mixin route from spec §4.11 point 3 guidance — inline is cheaper to land, and there's only one subprocess helper in this loop). The guard passes an `enabled: bool` flag into `_run_cli` (sourced from `deps.enabled_cb("contract_refresh")` at the call site — matches the existing BaseBackgroundLoop enabled convention per `src/base_background_loop.py:275`) so a killed loop contributes zero entries. An internal `_emit_subprocess_trace` hook wraps the emission so unit tests can monkeypatch one symbol.

- [ ] **Step 1: Write the failing unit test first (TDD)**

Append to `tests/test_contract_refresh_loop.py`:

```python
# --- Added in Task 20 ---


class TestContractRefreshLoopTelemetry:
    """§4.11 point 3: every subprocess invocation emits a trace tagged
    {"kind": "loop", "loop": "ContractRefreshLoop"}. When the loop is
    disabled, no emissions happen."""

    @pytest.mark.asyncio
    async def test_subprocess_invocation_emits_trace(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A `_run_cli` invocation triggers exactly one trace emission
        with the loop-action shape."""
        from contract_refresh_loop import _run_cli
        from tests.helpers import make_bg_loop_deps

        deps = make_bg_loop_deps(
            tmp_path,
            enabled=True,
            contract_refresh_interval=604800,
            max_fake_repair_attempts=3,
        )

        emissions: list[dict[str, Any]] = []

        def fake_emit(action: dict[str, Any]) -> None:
            emissions.append(action)

        monkeypatch.setattr(
            "contract_refresh_loop._emit_subprocess_trace", fake_emit
        )

        # _run_cli is a module-level helper; smallest non-destructive call:
        # `true` returns exit 0 with no output on POSIX.
        result = await _run_cli(["true"], enabled=True)

        assert result["exit_code"] == 0
        assert len(emissions) == 1
        assert emissions[0]["kind"] == "loop"
        assert emissions[0]["loop"] == "ContractRefreshLoop"
        assert emissions[0]["argv"] == ["true"]
        assert emissions[0]["exit_code"] == 0
        assert "duration_ms" in emissions[0]

    @pytest.mark.asyncio
    async def test_no_emission_when_loop_disabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the loop is disabled (enabled_cb returns False), `_run_cli`
        skips emission so a killed loop contributes zero cost-dashboard entries."""
        from contract_refresh_loop import _run_cli

        emissions: list[dict[str, Any]] = []

        def fake_emit(action: dict[str, Any]) -> None:
            emissions.append(action)

        monkeypatch.setattr(
            "contract_refresh_loop._emit_subprocess_trace", fake_emit
        )

        result = await _run_cli(["true"], enabled=False)

        assert result["exit_code"] == 0
        assert emissions == []
```

Run: `PYTHONPATH=src uv run pytest tests/test_contract_refresh_loop.py::TestContractRefreshLoopTelemetry -v`
Expected: both tests FAIL with `TypeError: _run_cli() got an unexpected keyword argument 'enabled'` (the helper in Task 13 has no `enabled` param yet).

- [ ] **Step 2: Extend `_run_cli` + add `_emit_subprocess_trace` in `src/contract_refresh_loop.py`**

Replace the `_run_cli` helper from Task 13 with the instrumented version, and add the emission helper above it:

```python
def _emit_subprocess_trace(action: dict[str, Any]) -> None:
    """Emit a subprocess action to trace_collector for the per-loop cost dashboard.

    Thin wrapper so unit tests can monkeypatch one symbol. Failures are
    logged and swallowed — telemetry MUST NOT crash the loop (matches the
    fail-safe semantics in src/trace_collector.py).
    """
    try:
        from trace_collector import record_loop_action  # noqa: PLC0415

        record_loop_action(action)
    except Exception:  # noqa: BLE001
        logger.warning("trace_collector emission failed", exc_info=True)


async def _run_cli(
    argv: list[str],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Run *argv* as a subprocess; return dict with exit_code, stdout, stderr.

    When *enabled* is true, emits a `{"kind": "loop", "loop":
    "ContractRefreshLoop"}` action to the trace collector per spec §4.11
    point 3. When the loop is disabled (enabled_cb returned False),
    emission is skipped so a paused loop contributes zero cost-dashboard
    entries.
    """
    import asyncio
    import time

    started_at = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    duration_ms = int((time.monotonic() - started_at) * 1000)
    exit_code = proc.returncode if proc.returncode is not None else -1

    result = {
        "exit_code": exit_code,
        "stdout": stdout_b.decode("utf-8", errors="replace"),
        "stderr": stderr_b.decode("utf-8", errors="replace"),
    }

    # Telemetry: gate on *enabled* so a killed loop emits nothing. §4.11
    # point 3 — action shape is load-bearing; the cost dashboard groups by
    # `loop`.
    if enabled:
        _emit_subprocess_trace(
            {
                "kind": "loop",
                "loop": "ContractRefreshLoop",
                "argv": list(argv),
                "exit_code": exit_code,
                "duration_ms": duration_ms,
            }
        )

    return result
```

Update every call site inside `_record_github`, `_record_git`, `_record_docker`, `_record_claude` (added in Task 13) to pass `enabled=self._enabled_cb(self._worker_name)`:

```python
        proc = await _run_cli([...], enabled=self._enabled_cb(self._worker_name))
```

(`self._enabled_cb` is the callback stashed by `BaseBackgroundLoop.__init__` at `src/base_background_loop.py:84` — already available on the loop instance.)

- [ ] **Step 3: Add `record_loop_action` to `src/trace_collector.py`**

Append a module-level helper (not a `TraceCollector` method — loop actions are one-shot, no accumulation):

```python
def record_loop_action(action: dict[str, Any]) -> None:
    """Record a per-loop subprocess/LLM action for the cost dashboard.

    Actions follow spec §4.11 point 3 shape:
    `{"kind": "loop", "loop": "<LoopClassName>", ...}`. Persisted via the
    existing SubprocessTrace JSON sink so the diagnostics waterfall and
    `/api/diagnostics/loops/cost` endpoints (§4.11 point 5) can aggregate.
    """
    try:
        # Delegates to the shared event-stream sink used by the diagnostics
        # router; see src/diagnostics_routes.py for the read side.
        from events import get_event_bus  # noqa: PLC0415

        bus = get_event_bus()
        if bus is not None:
            bus.publish("loop_action", action)
    except Exception:  # noqa: BLE001
        logger.warning("record_loop_action failed", exc_info=True)
```

- [ ] **Step 4: Run the telemetry tests — expect PASS**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_refresh_loop.py::TestContractRefreshLoopTelemetry -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the full loop test file — nothing else broke**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_refresh_loop.py -v`
Expected: all previous tests (construction + Task 13/14/15/16/17/18 coverage) still PASS alongside the two new telemetry tests.

- [ ] **Step 6: Commit**

```bash
git add src/contract_refresh_loop.py src/trace_collector.py tests/test_contract_refresh_loop.py
git commit -m "feat(contract_refresh_loop): emit per-loop subprocess telemetry (§4.11)"
```

---

## Task 21: Integration test — end-to-end mocked drift

**Files:**
- Modify: `tests/test_contract_refresh_loop.py`

Extend the test file written in Task 12 with two end-to-end scenarios: one where an injected cassette-only drift results in a refresh PR that passes the replay gate; one where an injected fake-drift results in a `fake-drift` issue being filed.

- [ ] **Step 1: Add the cassette-only-drift scenario**

Append to `tests/test_contract_refresh_loop.py`:

```python
# --- Added in Task 21 ---


class TestContractRefreshLoopEndToEnd:
    @pytest.mark.asyncio
    async def test_cassette_only_drift_opens_pr_no_issue_filed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When recorded bytes differ but the replay gate still passes, only
        the refresh PR gets opened — no `fake-drift` issue."""
        from contract_refresh_loop import ContractRefreshLoop
        from tests.helpers import make_bg_loop_deps

        deps = make_bg_loop_deps(
            tmp_path,
            enabled=True,
            contract_refresh_interval=604800,
            max_fake_repair_attempts=3,
        )
        prs = MagicMock()
        prs.create_issue = MagicMock(
            side_effect=lambda **_kw: (_ for _ in ()).throw(
                AssertionError("should not file an issue on cassette-only drift")
            )
        )
        state = MagicMock()
        state.get_bg_worker_states = MagicMock(return_value={})
        state.set_bg_worker_state = MagicMock()

        loop = ContractRefreshLoop(
            config=deps.config, deps=deps.loop_deps, prs=prs, state=state
        )

        # Stub recording to return one new cassette for git.
        async def fake_record_git() -> dict[str, bytes]:
            return {"commit": b"adapter: git\ninteraction: commit\n...drifted...\n"}

        async def fake_record_empty() -> dict[str, bytes]:
            return {}

        monkeypatch.setattr(loop, "_record_github", fake_record_empty)
        monkeypatch.setattr(loop, "_record_git", fake_record_git)
        monkeypatch.setattr(loop, "_record_docker", fake_record_empty)
        monkeypatch.setattr(loop, "_record_claude", fake_record_empty)

        # Stub the PR opener — just return success.
        async def fake_open_pr(*_a, **_kw) -> str:
            return "contract-refresh/2026-04-22"

        monkeypatch.setattr(loop, "_open_refresh_pr", fake_open_pr)

        async def fake_replay_pass(_adapters: list[str]) -> set[str]:
            return set()  # no failures

        monkeypatch.setattr(loop, "_run_replay_gate", fake_replay_pass)
        # Avoid touching disk.
        monkeypatch.setattr(loop, "_write_drifted_cassettes", lambda _d: [])

        result = await loop._do_work()

        assert result["adapters_drifted"] == 1
        assert result["fakes_diverged"] == 0
        assert result["drift_issues_filed"] == []

    @pytest.mark.asyncio
    async def test_fake_drift_files_companion_issue(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Replay-gate failure for an adapter triggers a `fake-drift` issue."""
        from contract_refresh_loop import ContractRefreshLoop
        from tests.helpers import make_bg_loop_deps

        deps = make_bg_loop_deps(
            tmp_path,
            enabled=True,
            contract_refresh_interval=604800,
            max_fake_repair_attempts=3,
        )

        async def _async_create_issue(**_kw: Any) -> int:
            return 777

        prs = MagicMock()
        prs.create_issue = _async_create_issue
        state = MagicMock()
        state.get_bg_worker_states = MagicMock(return_value={})
        state.set_bg_worker_state = MagicMock()

        loop = ContractRefreshLoop(
            config=deps.config, deps=deps.loop_deps, prs=prs, state=state
        )

        async def fake_record_git() -> dict[str, bytes]:
            return {"commit": b"adapter: git\ninteraction: commit\n...drifted...\n"}

        async def fake_record_empty() -> dict[str, bytes]:
            return {}

        monkeypatch.setattr(loop, "_record_github", fake_record_empty)
        monkeypatch.setattr(loop, "_record_git", fake_record_git)
        monkeypatch.setattr(loop, "_record_docker", fake_record_empty)
        monkeypatch.setattr(loop, "_record_claude", fake_record_empty)

        async def fake_open_pr(*_a, **_kw) -> str:
            return "contract-refresh/2026-04-22"

        monkeypatch.setattr(loop, "_open_refresh_pr", fake_open_pr)
        monkeypatch.setattr(loop, "_write_drifted_cassettes", lambda _d: [])

        async def fake_replay_fail(_adapters: list[str]) -> set[str]:
            return {"git"}  # git fake diverged

        monkeypatch.setattr(loop, "_run_replay_gate", fake_replay_fail)

        result = await loop._do_work()

        assert result["fakes_diverged"] == 1
        assert result["drift_issues_filed"] == [777]
```

- [ ] **Step 2: Run all tests in the file**

Run: `PYTHONPATH=src uv run pytest tests/test_contract_refresh_loop.py -v`
Expected: both construction tests + both end-to-end tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract_refresh_loop.py
git commit -m "test(contract_refresh_loop): end-to-end cassette-only + fake-drift scenarios"
```

---

## Task 22: Extend `test_loop_wiring_completeness.py`

**Files:**
- Verify: `tests/test_loop_wiring_completeness.py` (no edit needed — auto-discovery should pick up the new loop)

The wiring test uses regex auto-discovery (lines 49-68). Task 19a–19e must all land before this passes. No code change here — this task is a verification checkpoint.

- [ ] **Step 1: Run the wiring completeness tests**

Run: `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
Expected: all four tests (`test_all_loops_in_registry`, `test_all_loops_in_service_registry`, `test_all_loops_in_constants_js`, `test_all_loops_in_interval_bounds`, `test_all_registry_loops_in_factories`) PASS. If `contract_refresh` is missing from any of the four checkpoint files, the corresponding sub-task (19a–19d) is incomplete — fix and re-run.

- [ ] **Step 2: No commit needed**

This task is a pass/fail gate, not a change-producing step. If everything passes, advance to Task 23.

---

## Task 23: MockWorld scenario — ContractRefreshLoop end-to-end (§7)

**Files:**
- Create: `tests/scenarios/test_contract_refresh_scenario.py`

Spec §7 "MockWorld scenarios (integration-side) — required" mandates that every new loop land with a `tests/scenarios/` scenario exercising its pipeline behavior end-to-end using stateful fakes. Task 21 covers the unit-level loop behavior against mocked internals; this task covers the full-pipeline wiring: `FakeClock` advances past the interval, `MockWorld.run_pipeline()` ticks the loop, the loop drives `FakeGitHub`/`FakeGit`/`FakeDocker` through the recording → diff → PR → replay → (optional) `fake-drift` dispatch → (optional) `hitl-escalation` path, and the world's final state reflects the expected labels/PRs/issues.

Three scenarios land in this single file, matching the three spec branches:

1. **Cassette-only drift (happy path)** — recording drifts but replay against the refreshed cassettes still passes; a refresh PR opens against `staging` on `contract-refresh/YYYY-MM-DD` and auto-merges.
2. **Fake diverged** — replay fails against refreshed cassettes; a companion `hydraflow-find` issue with label `fake-drift` is filed and the factory dispatches an implementer against `tests/scenarios/fakes/`.
3. **Repair stuck → escalation** — 3 consecutive `fake-drift` failures exhaust the per-adapter budget; the issue is labeled `hitl-escalation` + `fake-repair-stuck` and no further refresh PRs open for that adapter.

- [ ] **Step 1: Write the failing scenarios first (TDD)**

Create `tests/scenarios/test_contract_refresh_scenario.py`:

```python
"""MockWorld scenario — ContractRefreshLoop end-to-end (§7 required).

Seeds MockWorld with a pre-existing cassette under
`tests/trust/contracts/cassettes/`, a scripted FakeGitHub/FakeGit/FakeDocker
that yields *new* output on recording (simulating real-service drift), and
a FakeClock advanced past `contract_refresh_interval`. Asserts the world's
final state matches the spec's three branches: cassette-only drift,
fake-drift dispatch, and 3-attempt escalation.

This complements `tests/test_contract_refresh_loop.py` (unit-level, mocked
internals) by exercising the full factory dispatch path: loop → PR manager
→ issue labels → implementer dispatch → state transitions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


# ---------------------------------------------------------------------------
# Fixtures shared across the three scenarios
# ---------------------------------------------------------------------------


def _seed_committed_cassette(world: MockWorld) -> Path:
    """Drop one pre-existing cassette under tests/trust/contracts/cassettes/git.

    The scenario world mirrors the repo tree; the loop's diff detection
    compares against the on-disk committed copy.
    """
    cassette_dir = world.repo_root / "tests/trust/contracts/cassettes/git"
    cassette_dir.mkdir(parents=True, exist_ok=True)
    cassette_path = cassette_dir / "commit.yaml"
    cassette_path.write_text(
        "adapter: git\n"
        "interaction: commit\n"
        "recorded_at: '2026-04-15T00:00:00Z'\n"
        "recorder_sha: abc1234\n"
        "fixture_repo: tests/trust/contracts/fixtures/git_sandbox\n"
        "input:\n"
        "  command: commit\n"
        "  args: [initial]\n"
        "  stdin: null\n"
        "  env: {}\n"
        "output:\n"
        "  exit_code: 0\n"
        "  stdout: ''\n"
        "  stderr: ''\n"
        "normalizers: [sha:short]\n"
    )
    return cassette_path


# ---------------------------------------------------------------------------
# Scenario 1: cassette-only drift → happy-path auto-merge, no issue filed
# ---------------------------------------------------------------------------


class TestContractRefreshCassetteOnlyDriftScenario:
    """Real-service drift with fakes still in sync → refresh PR opens and
    auto-merges; no `fake-drift` issue is filed."""

    async def test_cassette_only_drift_opens_pr_auto_merges(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        _seed_committed_cassette(world)

        # Scripted fake CLIs that yield *new* bytes on recording, simulating
        # upstream service drift.
        world.scripted_subprocess.set_response(
            ["git", "-C", "*", "commit", "*"],
            exit_code=0,
            stdout="[main abc9999] initial\n drifted shape\n",
            stderr="",
        )
        world.scripted_subprocess.set_response(
            ["gh", "pr", "list", "*"], exit_code=0, stdout="[]", stderr=""
        )
        world.scripted_subprocess.set_response(
            ["docker", "run", "*"], exit_code=0, stdout="hello\n", stderr=""
        )

        # Replay gate: refreshed cassettes still pass against fakes.
        _seed_ports(world, contract_replay_gate=_replay_pass_stub())

        # FakeClock past contract_refresh_interval (604800s = 7 days).
        world.clock.advance(seconds=604801)

        await world.run_pipeline()

        # Assertions on final world state:
        # 1. A PR opened against `staging` on a `contract-refresh/YYYY-MM-DD` branch.
        refresh_prs = [
            pr for pr in world.github.prs.values()
            if pr["base"] == "staging" and pr["head"].startswith("contract-refresh/")
        ]
        assert len(refresh_prs) == 1, f"expected 1 refresh PR, got {refresh_prs}"
        # 2. Cassette file on the PR branch contains the refreshed bytes.
        assert "abc9999" in refresh_prs[0]["diff"]
        # 3. PR auto-merged (cassette-only drift → standard happy path).
        assert refresh_prs[0]["state"] == "merged"
        # 4. No `fake-drift` issue filed.
        drift_issues = [
            i for i in world.github.issues.values()
            if "fake-drift" in i["labels"]
        ]
        assert drift_issues == []


# ---------------------------------------------------------------------------
# Scenario 2: fake-drift → companion issue filed + implementer dispatched
# ---------------------------------------------------------------------------


class TestContractRefreshFakeDriftScenario:
    """Replay fails against refreshed cassettes → `fake-drift` issue filed
    and factory dispatches an implementer against tests/scenarios/fakes/."""

    async def test_fake_drift_files_issue_and_dispatches_implementer(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        _seed_committed_cassette(world)

        world.scripted_subprocess.set_response(
            ["git", "-C", "*", "commit", "*"],
            exit_code=0,
            stdout="[main abc9999] initial\n drifted shape\n",
            stderr="",
        )
        world.scripted_subprocess.set_response(
            ["gh", "pr", "list", "*"], exit_code=0, stdout="[]", stderr=""
        )
        world.scripted_subprocess.set_response(
            ["docker", "run", "*"], exit_code=0, stdout="hello\n", stderr=""
        )

        # Replay gate REPORTS git-fake divergence.
        _seed_ports(world, contract_replay_gate=_replay_fail_stub(adapters={"git"}))

        world.clock.advance(seconds=604801)

        await world.run_pipeline()

        # 1. `fake-drift` issue filed, naming the adapter.
        drift_issues = [
            i for i in world.github.issues.values()
            if "fake-drift" in i["labels"]
        ]
        assert len(drift_issues) == 1
        assert "git" in drift_issues[0]["title"].lower()
        # 2. Implementer was dispatched against the fakes tree.
        implementer_calls = world.factory.implementer_dispatches
        assert any(
            "tests/scenarios/fakes/" in call["target_path"]
            for call in implementer_calls
        )
        # 3. Refresh PR still opened (atomic-branch strategy per §4.2) — the
        #    fake fix lands on the same branch before merge.
        refresh_prs = [
            pr for pr in world.github.prs.values()
            if pr["head"].startswith("contract-refresh/")
        ]
        assert len(refresh_prs) == 1


# ---------------------------------------------------------------------------
# Scenario 3: 3 consecutive fake-repair failures → hitl-escalation
# ---------------------------------------------------------------------------


class TestContractRefreshRepairStuckEscalation:
    """Per-adapter 3-attempt exhaustion → issue labeled `hitl-escalation` +
    `fake-repair-stuck`; loop stops opening new refresh PRs for that adapter."""

    async def test_three_consecutive_repair_failures_escalate(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        _seed_committed_cassette(world)

        world.scripted_subprocess.set_response(
            ["git", "-C", "*", "commit", "*"],
            exit_code=0,
            stdout="[main abc9999] initial\n drifted shape\n",
            stderr="",
        )
        world.scripted_subprocess.set_response(
            ["gh", "pr", "list", "*"], exit_code=0, stdout="[]", stderr=""
        )
        world.scripted_subprocess.set_response(
            ["docker", "run", "*"], exit_code=0, stdout="hello\n", stderr=""
        )

        # Replay gate fails for `git` on every attempt.
        _seed_ports(world, contract_replay_gate=_replay_fail_stub(adapters={"git"}))

        # Pre-load state with 2 prior consecutive failures for the `git`
        # adapter (set in Task 18's escalation tracker).
        world.state.set_bg_worker_state(
            "contract_refresh",
            {"contract_refresh.repair_attempts.git": 2},
        )

        world.clock.advance(seconds=604801)

        await world.run_pipeline()

        # 1. Issue labeled both `hitl-escalation` and `fake-repair-stuck`.
        escalated = [
            i for i in world.github.issues.values()
            if "hitl-escalation" in i["labels"]
            and "fake-repair-stuck" in i["labels"]
        ]
        assert len(escalated) == 1

        # 2. Second tick: another interval elapses → loop does NOT open a
        #    new refresh PR for `git` while escalation is open.
        world.clock.advance(seconds=604801)
        prs_before = len(world.github.prs)
        await world.run_pipeline()
        prs_after = len(world.github.prs)
        assert prs_after == prs_before, "loop must pause for escalated adapter"


# ---------------------------------------------------------------------------
# Helper stubs — replay gate pass/fail scripting
# ---------------------------------------------------------------------------


def _replay_pass_stub():
    from unittest.mock import AsyncMock

    gate = AsyncMock()
    gate.run.return_value = set()  # no failures
    return gate


def _replay_fail_stub(*, adapters: set[str]):
    from unittest.mock import AsyncMock

    gate = AsyncMock()
    gate.run.return_value = adapters
    return gate
```

Run: `PYTHONPATH=src uv run pytest tests/scenarios/test_contract_refresh_scenario.py -v`
Expected: all three scenarios FAIL — `MockWorld` has no `scripted_subprocess` response registrar keyed by the shell argv patterns above, and `world.factory.implementer_dispatches` is not yet exposed. Those are real integration gaps; surface them here, don't paper over.

- [ ] **Step 2: Extend `MockWorld` where gaps surface**

For any missing MockWorld capabilities the failing tests reveal, extend `tests/scenarios/fakes/mock_world.py` (or the specific fake module) with the minimum surface the scenario requires. Do NOT add fields the scenario doesn't use. If `scripted_subprocess` exists under a different name, update the scenario to match; if it truly doesn't exist, add a thin recorder keyed by argv glob patterns.

Budget: 30 minutes. If the gap is larger, file a `hydraflow-find` issue with label `mockworld-gap` and skip the affected scenario with `pytest.skip(reason=...)` pointing to the issue — do not block this PR on a MockWorld overhaul.

- [ ] **Step 3: Re-run — expect PASS**

Run: `PYTHONPATH=src uv run pytest tests/scenarios/test_contract_refresh_scenario.py -v`
Expected: all three scenarios PASS (or skip-with-issue per Step 2's budget).

- [ ] **Step 4: Run `make scenario` to confirm no regressions**

Run: `make scenario`
Expected: the full scenario ring (including the three new scenarios) passes. No existing scenario should turn red — if one does, it's a genuine regression caused by the MockWorld extensions in Step 2; revert and rescope.

- [ ] **Step 5: Commit**

```bash
git add tests/scenarios/test_contract_refresh_scenario.py tests/scenarios/fakes/mock_world.py
git commit -m "test(scenarios): ContractRefreshLoop end-to-end MockWorld scenarios (§7)"
```

If Step 2 did not touch `mock_world.py`, drop that path from the `git add`.

---

## Task 24: Final quality gate + PR description

**Files:** none (final verification + commit prep).

- [ ] **Step 1: Run `make trust-contracts`**

Run: `make trust-contracts`
Expected: all schema tests, replay-harness tests, and contract tests for all four adapters PASS.

- [ ] **Step 2: Run `make quality`**

Run: `make quality`
Expected: `lint-check`, `typecheck`, `tests`, and `scenario` all green.

- [ ] **Step 3: Confirm loop wiring completeness + scenario integration**

Run: `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py tests/test_contract_refresh_loop.py tests/test_contract_cassette_schema.py tests/test_contract_replay_harness.py tests/scenarios/test_contract_refresh_scenario.py -v`
Expected: every test PASSES.

- [ ] **Step 4: Open the PR**

PR title: `feat(trust): fake contract tests + ContractRefreshLoop (§4.2)`

PR body (HEREDOC template):

```markdown
## Summary

Ships §4.2 of the trust-architecture hardening spec: two-sided contract
tests for `FakeGitHub`, `FakeGit`, `FakeDocker`, and the `StreamParser`
→ `claude` stream-json path, plus a `ContractRefreshLoop` caretaker
that auto-refreshes cassettes weekly, opens a refresh PR, runs the
replay gate, and files `fake-drift` / `stream-protocol-drift` issues
when a fake or parser diverges.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
Plan: `docs/superpowers/plans/2026-04-22-fake-contract-tests.md`

## Design decisions

- **Sandbox repo:** `T-rav-Hydra-Ops/hydraflow-contracts-sandbox`
  (one-time manual setup; see Task 0 in plan).
- **Retry budget field:** new `max_fake_repair_attempts` (default 3).
  Not overloaded onto `max_issue_attempts` — `fake-drift` is a distinct
  repair class.
- **Stream sample prompt:** `"List the first three primes. Use no tools."`
  Plus two shape-distinct samples (tool-use + thinking/hello).

## Changes

- `tests/trust/contracts/` tree, schema, replay harness
- Three contract test modules (github, git, docker) + stream test module
- `src/contract_refresh_loop.py` with full autonomous flow per §3.2
- Five-checkpoint wiring for `contract_refresh` loop
- Per-loop telemetry emission via `trace_collector.record_loop_action` (§4.11 point 3)
- MockWorld scenario covering cassette-only drift, fake-drift dispatch, and 3-attempt escalation (§7)
- `make trust-contracts` target + RC workflow `trust` job

## Test plan

- [x] `make trust-contracts` green
- [x] `make quality` green (includes `make scenario`)
- [x] `tests/test_loop_wiring_completeness.py` green
- [x] `tests/scenarios/test_contract_refresh_scenario.py` green (3 scenarios)
- [x] `tests/test_contract_refresh_loop.py::TestContractRefreshLoopTelemetry` green
- [x] Manual sandbox-repo setup run by operator (Task 0)
```

- [ ] **Step 5: Final commit**

No code changes here. The PR is created from the commits made in Tasks 1–23.

---

## Self-Review Checklist

- **Spec coverage.** Every row in the §4.2 spec-requirement map (top of this plan) has an explicit task.
- **Placeholder scan.** No `TBD`, `TODO`, `...`, `implement later` outside of deliberate `__REPLACE_WITH_*` record-time tokens in example YAML (those are recording instructions, not plan placeholders).
- **Type consistency.**
  - `FakeOutput` shape: `exit_code: int, stdout: str, stderr: str` — consistent across Tasks 4, 5, 6, 7, 8.
  - `Cassette.input.command` is the *fake method name*, not a shell command — consistent across Tasks 4, 6, 7, 8, 13.
  - `max_fake_repair_attempts` (config), `_STATE_KEY_PREFIX = "contract_refresh.repair_attempts"` (state) — consistent across Tasks 16, 18.
  - `worker_name="contract_refresh"` everywhere (Tasks 11, 19a, 19b, 19c, 19d, 22).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-fake-contract-tests.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Especially suited to Tasks 6/7/8/9, which each involve an operator running real CLI commands to seed cassettes; batching 2–4 at a time per CLAUDE.md memory.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Task 0 (sandbox repo) must complete before Task 13 can run. Tasks 19a–19e and 22 must all complete before Task 24's wiring test passes. Task 20 (telemetry) must land before Task 21 (integration test) so the instrumented `_run_cli` signature is stable. Task 23 (MockWorld scenario) depends on Tasks 11–19 being fully wired through the factory.
