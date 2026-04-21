"""Tests for scripts/trace_canary_prompts.py — PromptInterceptor."""

from __future__ import annotations

import json

from scripts.trace_canary_prompts import PromptInterceptor


def test_interceptor_records_prompt_with_call_site():
    interceptor = PromptInterceptor()
    interceptor.record(prompt="Classify the issue.", cmd=["claude", "-p"])
    entries = interceptor.entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry["prompt"] == "Classify the issue."
    assert entry["cmd"] == ["claude", "-p"]
    assert "call_site" in entry and entry["call_site"]


def test_interceptor_dumps_jsonl(tmp_path):
    interceptor = PromptInterceptor()
    interceptor.record(prompt="hi", cmd=["claude"])
    out = tmp_path / "trace.jsonl"
    interceptor.dump(out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["prompt"] == "hi"
