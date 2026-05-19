"""PreflightRunner prompt-rendering tests."""

from __future__ import annotations

from preflight.runner import (
    parse_agent_response,
    render_prompt,
)


def test_persona_and_fields_substituted() -> None:
    out = render_prompt(
        sub_label="flaky-test-stuck",
        persona="Travis",
        issue_number=42,
        repo_slug="acme/widget",
        worktree_path="/tmp/wt",
        issue_body="body",
        issue_comments_block="(no comments)",
        escalation_context_block="(none)",
        wiki_excerpts_block="(no wiki)",
        sentry_events_block="(no sentry)",
        recent_commits_block="(no commits)",
        prior_attempts_block="(none)",
    )
    assert "You are Travis" in out
    assert "#42" in out
    assert "acme/widget" in out
    assert "{{> _envelope.md}}" not in out  # envelope was inlined


def test_default_fallback_for_unknown_sub_label() -> None:
    out = render_prompt(
        sub_label="totally-made-up-label",
        persona="x",
        issue_number=1,
        repo_slug="r/s",
        worktree_path="/tmp",
        issue_body="b",
        issue_comments_block="x",
        escalation_context_block="x",
        wiki_excerpts_block="x",
        sentry_events_block="x",
        recent_commits_block="x",
        prior_attempts_block="x",
    )
    assert "Default Playbook" in out


def test_explicit_prompt_template_overrides_sub_label_lookup() -> None:
    """ADR-0063 W1: PreflightPlaybook.prompt_template lets the registry pick
    a prompt file independent of the sub-label string. Sub-label
    ``my-custom-stuck`` with template ``plan-stuck`` must render plan-stuck.md.
    """
    out = render_prompt(
        sub_label="my-custom-stuck",
        persona="x",
        issue_number=1,
        repo_slug="r/s",
        worktree_path="/tmp",
        issue_body="b",
        issue_comments_block="x",
        escalation_context_block="x",
        wiki_excerpts_block="x",
        sentry_events_block="x",
        recent_commits_block="x",
        prior_attempts_block="x",
        prompt_template="plan-stuck",
    )
    assert "plan-stuck Playbook" in out


def test_explicit_default_template_renders_default_even_for_known_sub_label() -> None:
    """A playbook that points at ``_default`` renders the generic prompt even
    when a same-named prompt file exists (e.g. for sub-labels whose specialist
    persona is enough and no custom file is justified)."""
    out = render_prompt(
        sub_label="flaky-test-stuck",  # has its own .md file
        persona="x",
        issue_number=1,
        repo_slug="r/s",
        worktree_path="/tmp",
        issue_body="b",
        issue_comments_block="x",
        escalation_context_block="x",
        wiki_excerpts_block="x",
        sentry_events_block="x",
        recent_commits_block="x",
        prior_attempts_block="x",
        prompt_template="_default",
    )
    assert "Default Playbook" in out


def test_parse_agent_response_resolved() -> None:
    out = parse_agent_response(
        "<status>resolved</status><pr_url>https://x</pr_url><diagnosis>did it</diagnosis>"
    )
    assert out["status"] == "resolved"
    assert out["pr_url"] == "https://x"


def test_parse_agent_response_needs_human() -> None:
    out = parse_agent_response(
        "<status>needs_human</status><diagnosis>nope</diagnosis>"
    )
    assert out["status"] == "needs_human"
    assert out["pr_url"] is None
