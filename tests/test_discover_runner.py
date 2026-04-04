"""Tests for the discover runner — product research agent."""

from __future__ import annotations

from discover_runner import _DISCOVER_END, _DISCOVER_START, DiscoverRunner


class TestExtractResult:
    """Tests for DiscoverRunner._extract_result."""

    def test_extracts_valid_json(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"""Some preamble text.

{_DISCOVER_START}

```json
{{
  "issue_number": 42,
  "research_brief": "Calendly dominates scheduling but lacks group features.",
  "competitors": ["Calendly — market leader", "Cal.com — open source"],
  "user_needs": ["Group scheduling", "Privacy-first approach"],
  "opportunities": ["Open source alternative with group focus"]
}}
```

{_DISCOVER_END}

Some trailing text."""

        result = runner._extract_result(transcript, 42)

        assert result is not None
        assert result.issue_number == 42
        assert "Calendly dominates" in result.research_brief
        assert len(result.competitors) == 2
        assert len(result.user_needs) == 2
        assert len(result.opportunities) == 1

    def test_returns_none_without_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        result = runner._extract_result("No markers here", 42)
        assert result is None

    def test_returns_none_with_invalid_json(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"{_DISCOVER_START}\n```json\n{{invalid}}\n```\n{_DISCOVER_END}"
        result = runner._extract_result(transcript, 42)
        assert result is None


class TestExtractRawBrief:
    """Tests for DiscoverRunner._extract_raw_brief."""

    def test_extracts_text_between_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"{_DISCOVER_START}\nSome raw research text.\n{_DISCOVER_END}"
        result = runner._extract_raw_brief(transcript)
        assert result == "Some raw research text."

    def test_returns_empty_without_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        result = runner._extract_raw_brief("No markers")
        assert result == ""


class TestBuildPrompt:
    """Tests for DiscoverRunner._build_prompt."""

    def test_prompt_includes_issue_details(self) -> None:
        from unittest.mock import MagicMock

        runner = DiscoverRunner.__new__(DiscoverRunner)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "I want a scheduling tool"

        prompt = runner._build_prompt(task)

        assert "Build a better Calendly" in prompt
        assert "I want a scheduling tool" in prompt
        assert "DISCOVER_START" in prompt
        assert "DISCOVER_END" in prompt
        assert "competitors" in prompt.lower()
        assert "needs" in prompt.lower()
