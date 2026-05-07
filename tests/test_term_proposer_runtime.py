"""Tests for the production adapters wiring TermProposerLoop."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from term_proposer_runtime import ClaudeCLIClient, OpenAutoPRBotPRPort


class FakeRunner:
    def __init__(self, *, returncode: int, stdout: str, stderr: str = "") -> None:
        self._result = subprocess.CompletedProcess(
            args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr
        )
        self.calls: list[dict] = []

    async def run_simple(
        self, cmd, *, input=None, timeout=None, **_
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, "input": input, "timeout": timeout})
        return self._result


class TestClaudeCLIClient:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self) -> None:
        runner = FakeRunner(returncode=0, stdout='{"foo": "bar", "n": 1}')
        client = ClaudeCLIClient(runner=runner)
        out = await client.complete_structured(prompt="hi", schema={})
        assert out == {"foo": "bar", "n": 1}

    @pytest.mark.asyncio
    async def test_extracts_json_from_markdown_fence(self) -> None:
        runner = FakeRunner(
            returncode=0,
            stdout='Here is the result:\n```json\n{"k": "v"}\n```\nDone.',
        )
        client = ClaudeCLIClient(runner=runner)
        out = await client.complete_structured(prompt="hi", schema={})
        assert out == {"k": "v"}

    @pytest.mark.asyncio
    async def test_raises_on_nonzero_returncode(self) -> None:
        runner = FakeRunner(returncode=1, stdout="", stderr="boom")
        client = ClaudeCLIClient(runner=runner)
        with pytest.raises(RuntimeError, match="claude CLI failed"):
            await client.complete_structured(prompt="hi", schema={})

    @pytest.mark.asyncio
    async def test_raises_when_no_json_in_output(self) -> None:
        runner = FakeRunner(returncode=0, stdout="just prose, no json here")
        client = ClaudeCLIClient(runner=runner)
        with pytest.raises(RuntimeError, match="no JSON object"):
            await client.complete_structured(prompt="hi", schema={})


class TestOpenAutoPRBotPRPort:
    @pytest.mark.asyncio
    async def test_writes_files_and_returns_pr_number(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from auto_pr import AutoPrResult

        captured: dict = {}

        async def fake_open_automated_pr_async(**kwargs):
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/T-rav/hydraflow/pull/4242",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr(
            "auto_pr.open_automated_pr_async", fake_open_automated_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path, gh_token="ghs_x")
        files = {
            "docs/wiki/terms/foo-loop.md": "---\nname: FooLoop\n---\n# def\n",
            "docs/wiki/terms/bar-runner.md": "---\nname: BarRunner\n---\n# def\n",
        }
        pr_number = await port.open_bot_pr(
            branch="ul-proposer/abc123",
            title="feat(ul): batch",
            body="body",
            labels=["hydraflow-ul-proposed"],
            files=files,
        )

        assert pr_number == 4242
        # Files written
        assert (tmp_path / "docs/wiki/terms/foo-loop.md").read_text().startswith("---")
        assert (tmp_path / "docs/wiki/terms/bar-runner.md").exists()
        # auto_pr called with the right args
        assert captured["branch"] == "ul-proposer/abc123"
        assert captured["pr_title"] == "feat(ul): batch"
        assert captured["labels"] == ["hydraflow-ul-proposed"]
        assert captured["auto_merge"] is False  # DependabotMergeLoop handles merge
        assert captured["base"] == "main"
        assert len(captured["files"]) == 2

    @pytest.mark.asyncio
    async def test_raises_on_open_failure(self, tmp_path: Path, monkeypatch) -> None:
        from auto_pr import AutoPrResult

        async def fake_open_automated_pr_async(**kwargs):
            return AutoPrResult(
                status="failed", pr_url=None, branch=kwargs["branch"], error="auth"
            )

        monkeypatch.setattr(
            "auto_pr.open_automated_pr_async", fake_open_automated_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path)
        with pytest.raises(RuntimeError, match="status='failed'"):
            await port.open_bot_pr(
                branch="x", title="x", body="x", labels=[], files={"foo.md": "x"}
            )
