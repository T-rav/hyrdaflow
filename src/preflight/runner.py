"""AutoAgentRunner — prompt rendering for auto-agent invocations.

Spec §3.3, §10 (decision: subclass HITLRunner with prompt-envelope override).
This module owns prompt rendering; spawning happens in PreflightAgent (agent.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).parent.parent.parent / "prompts" / "auto_agent"


def render_prompt(
    *,
    sub_label: str,
    persona: str,
    issue_number: int,
    repo_slug: str,
    worktree_path: str,
    issue_body: str,
    issue_comments_block: str,
    escalation_context_block: str,
    wiki_excerpts_block: str,
    sentry_events_block: str,
    recent_commits_block: str,
    prior_attempts_block: str,
    prompt_template: str | None = None,
) -> str:
    """Load the sub-label prompt file (or _default.md) + envelope, render.

    Args:
        prompt_template: When provided, overrides the sub-label-derived file
            lookup. The W1 playbook registry (ADR-0063) uses this to drive
            prompt selection from the playbook bundle rather than the raw
            sub-label string — letting a sub-label without its own prompt
            file route to a specialist persona + the ``_default`` template,
            or vice versa.
    """
    template_stem = prompt_template if prompt_template is not None else sub_label
    prompt_path = _PROMPT_DIR / f"{template_stem}.md"
    if not prompt_path.exists():
        prompt_path = _PROMPT_DIR / "_default.md"

    content = prompt_path.read_text(encoding="utf-8")

    # Inline the envelope partial — simple {{> _envelope.md}} substitution.
    envelope_path = _PROMPT_DIR / "_envelope.md"
    envelope = envelope_path.read_text(encoding="utf-8")
    content = content.replace("{{> _envelope.md}}", envelope)

    # Substitute fields
    return content.format(
        persona=persona,
        issue_number=issue_number,
        sub_label=sub_label,
        repo_slug=repo_slug,
        worktree_path=worktree_path,
        issue_body=issue_body,
        issue_comments_block=issue_comments_block,
        escalation_context_block=escalation_context_block,
        wiki_excerpts_block=wiki_excerpts_block,
        sentry_events_block=sentry_events_block,
        recent_commits_block=recent_commits_block,
        prior_attempts_block=prior_attempts_block,
    )


def render_blocks(
    *,
    issue_comments: list,
    escalation_context: Any | None,
    wiki_excerpts: str,
    sentry_events: list,
    recent_commits: list,
    prior_attempts: list,
) -> dict[str, str]:
    """Render the structured-block strings injected into the prompt."""
    return {
        "issue_comments_block": _render_comments(issue_comments),
        "escalation_context_block": _render_escalation_context(escalation_context),
        "wiki_excerpts_block": wiki_excerpts or "(no relevant wiki entries found)",
        "sentry_events_block": _render_sentry(sentry_events),
        "recent_commits_block": _render_commits(recent_commits),
        "prior_attempts_block": _render_prior_attempts(prior_attempts),
    }


def _render_comments(comments: list) -> str:
    if not comments:
        return "(no comments)"
    return "\n\n".join(
        f"- {c.author} ({c.created_at}): {c.body[:500]}" for c in comments
    )


def _render_escalation_context(ctx: Any | None) -> str:
    if ctx is None:
        return (
            "(no structured escalation context — operate from the issue body, "
            "sub-label, wiki, sentry, and recent commits)"
        )
    # EscalationContext is Pydantic — render its dict form
    try:
        return "```\n" + ctx.model_dump_json(indent=2) + "\n```"
    except AttributeError:
        return f"```\n{ctx!r}\n```"


def _render_sentry(events: list) -> str:
    if not events:
        return "(no recent Sentry events match)"
    return "\n".join(
        f"- {e.title} ({e.event_count} events, {e.user_count} users) — {e.permalink}"
        for e in events
    )


def _render_commits(commits: list) -> str:
    if not commits:
        return "(no recent commits to mentioned files)"
    return "\n".join(f"- {c.sha[:8]} {c.title} — {c.author} {c.date}" for c in commits)


def _render_prior_attempts(attempts: list) -> str:
    if not attempts:
        return "(no prior attempts on this issue — this is attempt 1)"
    out = []
    for a in attempts:
        out.append(
            f"### Attempt {a.attempt_n} ({a.ts}) → {a.status}\n"
            f"**Diagnosis:** {a.diagnosis}\n"
            f"**LLM summary:** {a.llm_summary}"
        )
    return "\n\n".join(out)


_TAG_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)


def parse_agent_response(text: str) -> dict[str, str | None]:
    """Parse <status>...</status> + <pr_url>...</pr_url> + <diagnosis>...</diagnosis>."""
    tags = {m.group(1): m.group(2).strip() for m in _TAG_RE.finditer(text)}
    return {
        "status": tags.get("status", "needs_human"),
        "pr_url": tags.get("pr_url") or None,
        "diagnosis": tags.get("diagnosis", text.strip()),
    }
