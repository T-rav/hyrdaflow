"""One-shot canary trace — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md.

Monkey-patches ``base_runner.stream_claude_process`` to capture every ``prompt=``
argument with call-site traceback, drives the triage runner against a synthetic
canary issue, and writes the captured prompts to
``tests/fixtures/prompts/canary-trace.jsonl``.

Scope is deliberately tiny — one runner, one canary issue, at least one captured
prompt. The goal is to prove the tracing mechanism works and seed the coverage
assertion; the eval gate (sub-project 2) extends the canary to a real target repo.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromptInterceptor:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, prompt: str, cmd: list[str] | None = None) -> None:
        call_site = "".join(traceback.format_stack(limit=12))
        self.entries.append(
            {
                "prompt": prompt,
                "cmd": list(cmd) if cmd is not None else [],
                "call_site": call_site,
            }
        )

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for entry in self.entries:
                f.write(json.dumps(entry) + "\n")


def install(interceptor: PromptInterceptor) -> None:
    """Replace ``base_runner.stream_claude_process`` with a recording stub.

    The stub captures the prompt, then returns a canned transcript that keeps
    the triage runner's downstream parser happy (valid JSON matching the schema).
    """
    import base_runner  # noqa: PLC0415

    _CANNED_TRIAGE_JSON = (
        '{"ready": true, "reasons": [], "issue_type": "feature", '
        '"clarity_score": 9, "needs_discovery": false, "enrichment": ""}'
    )

    async def recording_stub(*, cmd: list[str], prompt: str, **_kwargs: Any) -> str:
        interceptor.record(prompt=prompt, cmd=cmd)
        return _CANNED_TRIAGE_JSON

    base_runner.stream_claude_process = recording_stub  # type: ignore[assignment]


def main() -> None:  # pragma: no cover — driver is exercised manually
    import asyncio

    from config import HydraFlowConfig  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from models import Task  # noqa: PLC0415
    from state import StateTracker  # noqa: PLC0415
    from triage import TriageRunner  # noqa: PLC0415

    interceptor = PromptInterceptor()
    install(interceptor)

    config = HydraFlowConfig(dry_run=False)
    event_bus = EventBus()
    state = StateTracker(path=Path("/tmp/_prompt_audit_canary_state.json"))

    # TriageRunner signature may require more args — adapt if needed.
    runner = TriageRunner(config=config, event_bus=event_bus, state=state)

    canary_issue = Task(
        id=99999,
        title="[canary] audit probe: retry transient S3 upload failures",
        body=(
            "Intermittent 503s from S3 during upload cause job failures. "
            "Expected: retry up to 3 times with exponential backoff. "
            "Observed: first failure kills the job. Affected: src/upload.py."
        ),
        tags=["bug"],
        comments=[],
    )

    asyncio.run(runner.evaluate(canary_issue))

    out = Path("tests/fixtures/prompts/canary-trace.jsonl")
    interceptor.dump(out)
    print(f"wrote {len(interceptor.entries)} entries to {out}")


if __name__ == "__main__":
    main()
