"""Tests for the shape runner — multi-agent product direction generator."""

from __future__ import annotations

from shape_runner import _SHAPE_END, _SHAPE_START, ShapeRunner


class TestExtractResult:
    """Tests for ShapeRunner._extract_result."""

    def test_extracts_valid_directions(self) -> None:
        runner = ShapeRunner.__new__(ShapeRunner)
        transcript = f"""{_SHAPE_START}

```json
{{
  "issue_number": 42,
  "directions": [
    {{
      "name": "Privacy-First",
      "approach": "Build a self-hosted scheduling tool",
      "tradeoffs": "More setup, less reach",
      "effort": "high",
      "risk": "medium",
      "differentiator": "No data leaves user's server"
    }},
    {{
      "name": "Group Focus",
      "approach": "Solve multi-party scheduling",
      "tradeoffs": "Narrower market, deeper value",
      "effort": "medium",
      "risk": "low",
      "differentiator": "Best-in-class group scheduling"
    }}
  ],
  "recommendation": "Go with Group Focus for faster time to market"
}}
```

{_SHAPE_END}"""

        result = runner._extract_result(transcript, 42)

        assert result is not None
        assert result.issue_number == 42
        assert len(result.directions) == 2
        assert result.directions[0].name == "Privacy-First"
        assert result.directions[1].effort == "medium"
        assert "Group Focus" in result.recommendation

    def test_returns_none_without_markers(self) -> None:
        runner = ShapeRunner.__new__(ShapeRunner)
        result = runner._extract_result("No markers", 42)
        assert result is None

    def test_returns_none_with_invalid_json(self) -> None:
        runner = ShapeRunner.__new__(ShapeRunner)
        transcript = f"{_SHAPE_START}\n```json\n{{bad}}\n```\n{_SHAPE_END}"
        result = runner._extract_result(transcript, 42)
        assert result is None


class TestBuildPrompt:
    """Tests for ShapeRunner._build_prompt."""

    def test_prompt_includes_issue_and_perspectives(self) -> None:
        from unittest.mock import MagicMock

        runner = ShapeRunner.__new__(ShapeRunner)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "Scheduling tool"

        prompt = runner._build_advocate_prompt(task)

        assert "Build a better Calendly" in prompt
        assert "User Advocate" in prompt
        assert "Technical Realist" in prompt
        assert "Market Strategist" in prompt
        assert "Scope Hawk" in prompt

    def test_prompt_includes_research_brief_when_provided(self) -> None:
        from unittest.mock import MagicMock

        runner = ShapeRunner.__new__(ShapeRunner)
        task = MagicMock()
        task.id = 42
        task.title = "Test"
        task.body = "Test body"

        prompt = runner._build_advocate_prompt(
            task, research_brief="Calendly has 10M users"
        )

        assert "Calendly has 10M users" in prompt
        assert "Discovery Research Brief" in prompt

    def test_prompt_omits_research_section_when_empty(self) -> None:
        from unittest.mock import MagicMock

        runner = ShapeRunner.__new__(ShapeRunner)
        task = MagicMock()
        task.id = 42
        task.title = "Test"
        task.body = "Test body"

        prompt = runner._build_advocate_prompt(task, research_brief="")

        assert "Discovery Research Brief" not in prompt


class TestCriticPrompt:
    """Tests for ShapeRunner._build_critic_prompt."""

    def test_critic_prompt_includes_advocate_directions(self) -> None:
        from unittest.mock import MagicMock

        from models import ProductDirection, ShapeResult

        runner = ShapeRunner.__new__(ShapeRunner)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "Scheduling tool"

        advocate_result = ShapeResult(
            issue_number=42,
            directions=[
                ProductDirection(
                    name="Privacy-First",
                    approach="Self-hosted",
                    tradeoffs="More setup",
                    effort="high",
                    risk="medium",
                    differentiator="No data leaves server",
                ),
            ],
            recommendation="Go with Privacy-First",
        )

        prompt = runner._build_critic_prompt(task, advocate_result)

        assert "CRITIC" in prompt
        assert "Privacy-First" in prompt
        assert "Go with Privacy-First" in prompt
        assert "CHALLENGE" in prompt
        assert "Kill weak directions" in prompt


class TestFormatOptionsHtml:
    """Tests for ShapePhase.format_options_html."""

    def test_html_contains_directions(self) -> None:
        from unittest.mock import MagicMock

        from models import ProductDirection, ShapeResult
        from shape_phase import ShapePhase

        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"

        result = ShapeResult(
            issue_number=42,
            directions=[
                ProductDirection(
                    name="Simple",
                    approach="Keep it simple",
                    tradeoffs="Less features",
                    effort="low",
                    risk="low",
                ),
                ProductDirection(
                    name="Complex",
                    approach="Full featured",
                    tradeoffs="More work",
                    effort="high",
                    risk="high",
                    differentiator="Market leader",
                ),
            ],
            recommendation="Go with Simple",
        )

        html = ShapePhase.format_options_html(task, result)

        assert "<!DOCTYPE html>" in html
        assert "Simple" in html
        assert "Complex" in html
        assert "Market leader" in html
        assert "Go with Simple" in html
        assert "#3fb950" in html  # low effort/risk color (green)
        assert "#f85149" in html  # high effort/risk color (red)
