"""PreflightContext — what the auto-agent knows when it starts a pre-flight.

Spec §3.2. Pure data-gathering with graceful degradation: any source that
fails returns empty/None rather than raising.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from models import EscalationContext
from preflight.audit import PreflightAuditEntry
from sentry.reverse_lookup import SentryEvent

logger = logging.getLogger("hydraflow.preflight.context")


@dataclass(frozen=True)
class IssueComment:
    author: str
    body: str
    created_at: str  # ISO 8601


@dataclass(frozen=True)
class CommitRef:
    sha: str
    title: str
    author: str
    date: str  # ISO 8601


@dataclass(frozen=True)
class PreflightContext:
    issue_number: int
    issue_body: str
    issue_comments: list[IssueComment]
    sub_label: str
    escalation_context: EscalationContext | None
    wiki_excerpts: str
    sentry_events: list[SentryEvent]
    recent_commits: list[CommitRef]
    sublabel_extras: dict[str, Any] = field(default_factory=dict)
    prior_attempts: list[PreflightAuditEntry] = field(default_factory=list)


class _ContextPRSink(Protocol):
    async def get_issue(self, number: int) -> dict[str, Any]: ...
    async def list_issue_comments(self, number: int) -> list[dict[str, Any]]: ...


class _WikiSink(Protocol):
    def query(self, repo_slug: str, keywords: list[str], **kwargs: Any) -> str: ...


async def gather_context(
    *,
    issue_number: int,
    issue_body: str,
    sub_label: str,
    pr_port: _ContextPRSink,
    wiki_store: _WikiSink | None,
    state: Any,  # StateTracker (avoid circular import)
    audit_store: Any,  # PreflightAuditStore
    repo_slug: str,
    sentry_lookup: Any | None = None,  # callable(text) -> Awaitable[list[SentryEvent]]
    git_log_fn: Any | None = None,  # callable(files, since_days) -> list[CommitRef]
) -> PreflightContext:
    """Gather everything PreflightAgent needs to act."""
    # Comments — degrade gracefully
    try:
        raw_comments = await pr_port.list_issue_comments(issue_number)
        comments = [
            IssueComment(
                author=str(c.get("user", {}).get("login", "?")),
                body=str(c.get("body", "")),
                created_at=str(c.get("created_at", "")),
            )
            for c in raw_comments[-10:]
        ]
    except Exception as exc:
        logger.warning("Issue comments fetch failed for #%d: %s", issue_number, exc)
        comments = []

    # Escalation context — may legitimately be None for caretaker-loop escalations
    escalation_context: EscalationContext | None
    try:
        escalation_context = state.get_escalation_context(issue_number)
    except Exception as exc:
        logger.warning("Escalation context read failed for #%d: %s", issue_number, exc)
        escalation_context = None

    # Wiki — keyword extraction is naive on purpose; the wiki layer does its own ranking
    wiki_excerpts = ""
    if wiki_store is not None:
        try:
            keywords = _extract_keywords(issue_body)
            wiki_excerpts = wiki_store.query(
                repo_slug, keywords=keywords, max_chars=15_000
            )
        except Exception as exc:
            logger.warning("Wiki query failed for #%d: %s", issue_number, exc)

    # Sentry — degrade to []
    sentry_events: list[SentryEvent] = []
    if sentry_lookup is not None:
        try:
            sentry_events = await sentry_lookup(issue_body)
        except Exception as exc:
            logger.warning(
                "Sentry reverse-lookup failed for #%d: %s", issue_number, exc
            )

    # Recent commits
    recent_commits: list[CommitRef] = []
    if git_log_fn is not None:
        try:
            files = _files_mentioned(issue_body)
            recent_commits = git_log_fn(files, 7) if files else []
        except Exception as exc:
            logger.warning("Recent-commits read failed for #%d: %s", issue_number, exc)

    # Prior attempts
    try:
        prior_attempts = audit_store.entries_for_issue(issue_number)
    except Exception as exc:
        logger.warning("Audit read failed for #%d: %s", issue_number, exc)
        prior_attempts = []

    return PreflightContext(
        issue_number=issue_number,
        issue_body=issue_body,
        issue_comments=comments,
        sub_label=sub_label,
        escalation_context=escalation_context,
        wiki_excerpts=wiki_excerpts,
        sentry_events=sentry_events,
        recent_commits=recent_commits,
        sublabel_extras={},  # populated per-sublabel in later iteration
        prior_attempts=prior_attempts,
    )


def _extract_keywords(body: str) -> list[str]:
    """Naive keyword extraction — uppercase identifiers + first 5 unique nouns."""

    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", body)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= 10:
            break
    return out


def _files_mentioned(body: str) -> list[str]:
    """Extract file-like tokens (paths with / and an extension)."""

    return re.findall(r"\b[\w./_-]+\.[a-z]{1,5}\b", body)[:10]
