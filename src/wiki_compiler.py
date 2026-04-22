"""LLM-driven wiki compilation — synthesize, cross-reference, deduplicate.

This is the "librarian" from Karpathy's LLM Knowledge Base pattern.
Instead of mechanically dumping entries, the compiler uses an LLM to:

1. **Synthesize** — merge redundant entries into consolidated insights
2. **Cross-reference** — add backlinks between related entries across topics
3. **Deduplicate** — identify and merge entries covering the same concept
4. **Resolve contradictions** — flag or resolve conflicting entries

Called periodically by RepoWikiLoop and optionally after large ingests.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from repo_wiki import WikiEntry

_SYNTHESIS_ID_RE = re.compile(r"^(\d+)-")


# ---------------------------------------------------------------------------
# Contradiction-check models
# ---------------------------------------------------------------------------


class ContradictedEntry(BaseModel):
    id: str = Field(description="ULID of the sibling entry that is contradicted")
    reason: str = Field(description="One-sentence explanation")


class ContradictionCheck(BaseModel):
    contradicts: list[ContradictedEntry] = Field(default_factory=list)


if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore

logger = logging.getLogger("hydraflow.wiki_compiler")

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_COMPILE_TOPIC_PROMPT = """\
You are a technical knowledge librarian maintaining a per-repository wiki.

Below are all current entries in the **{topic}** topic for repository **{repo}**.
Your job is to compile them into a clean, deduplicated set of entries.

## Current entries

{entries_text}

## Instructions

1. **Merge duplicates**: If multiple entries cover the same concept, merge them into one
   consolidated entry. Keep the most informative content from each.
2. **Cross-reference**: If an entry relates to entries in other topics ({other_topics}),
   add a brief note like "See also: [topic] — [entry title]".
3. **Resolve contradictions**: If entries contradict each other, keep the more recent one
   and note the resolution.
4. **Remove stale content**: If an entry's insight has been superseded by a newer one, drop it.
5. **Preserve source attribution**: Keep source_issue and source_type from the original entries.

## Output format

Return a JSON array of compiled entries. Each entry must be a JSON object with these fields:
- "title": string (short, descriptive)
- "content": string (the compiled insight, with cross-references)
- "source_type": string (plan, implement, review, hitl, or "compiled")
- "source_issue": number or null
- "stale": false

Return ONLY the JSON array, no other text.
"""

_CONTRADICTION_PROMPT = """\
You are a technical knowledge librarian. A new wiki entry has been written to the
**{topic}** topic of repository **{repo}**. Identify which existing sibling entries
(if any) it contradicts — meaning the new entry's advice is incompatible with an
existing entry's advice, not merely different in emphasis.

## New entry

title: {new_title}
content:
{new_content}

## Existing sibling entries (current only)

{siblings_text}

## Instructions

Return a JSON object with one key, "contradicts", mapping to an array of
{{"id": <sibling_id>, "reason": <one-sentence>}} objects.

Only include a sibling if the new entry **directly contradicts** it — e.g.,
"use X" vs "never use X", or "Python 3.11 minimum" vs "Python 3.10 minimum".
Do NOT include siblings that are merely related or complementary.

Return ONLY the JSON object, no other text.

Example valid outputs:
  {{"contradicts": []}}
  {{"contradicts": [{{"id":"01HQ...","reason":"new entry says X, this one said not-X"}}]}}
"""

_SYNTHESIZE_INGEST_PROMPT = """\
You are a technical knowledge librarian. A {source_type} phase just completed for \
issue #{issue_number} in repository {repo}.

## Raw phase output

{raw_text}

## Instructions

Extract 1-5 durable knowledge entries from this output. Focus on:
- Architecture decisions or patterns discovered
- Gotchas, pitfalls, or edge cases encountered
- Testing strategies or conventions learned
- Dependency quirks or version constraints found
- Reusable patterns or anti-patterns identified

Skip ephemeral details (specific variable names, one-off debugging steps).
Each entry should be a standalone insight useful for future work on this repo.

## Output format

Return a JSON array of entries. Each entry must be:
- "title": string (10 words max, descriptive)
- "content": string (2-5 sentences, self-contained insight)
- "source_type": "{source_type}"
- "source_issue": {issue_number}

Return ONLY the JSON array, no other text.
"""


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class WikiCompiler:
    """LLM-powered wiki compilation and synthesis."""

    @staticmethod
    def _parse_contradiction_output(raw: str) -> ContradictionCheck:
        """Parse contradiction-check LLM output. Never raises."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return ContradictionCheck()

        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return ContradictionCheck()

        if not isinstance(obj, dict) or "contradicts" not in obj:
            return ContradictionCheck()

        try:
            return ContradictionCheck.model_validate(obj)
        except Exception:  # noqa: BLE001
            return ContradictionCheck()

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: SubprocessRunner,
        credentials: Credentials | None = None,
    ) -> None:
        self._config = config
        self._runner = runner
        if credentials is None:
            from config import Credentials as _Creds  # noqa: PLC0415

            credentials = _Creds()
        self._credentials = credentials

    async def compile_topic(
        self,
        store: RepoWikiStore,
        repo: str,
        topic: str,
        other_topics: list[str] | None = None,
    ) -> int:
        """Compile all entries in a single topic using the LLM.

        Reads current entries, asks the LLM to synthesize/deduplicate,
        then writes the compiled entries back.  Returns the number of
        entries after compilation (0 on failure).
        """
        from repo_wiki import DEFAULT_TOPICS  # noqa: PLC0415

        repo_dir = store._repo_dir(repo)
        topic_path = repo_dir / f"{topic}.md"
        entries = store._load_topic_entries(topic_path)

        if len(entries) < 2:
            return len(entries)  # nothing to compile

        entries_text = "\n\n".join(
            f"### {e.title}\n{e.content}\n"
            f"Source: #{e.source_issue or 'N/A'} ({e.source_type})\n"
            f"Created: {e.created_at}"
            for e in entries
        )

        if other_topics is None:
            other_topics = [t for t in DEFAULT_TOPICS if t != topic]

        prompt = _COMPILE_TOPIC_PROMPT.format(
            topic=topic,
            repo=repo,
            entries_text=entries_text,
            other_topics=", ".join(other_topics),
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return len(entries)

        compiled = self._parse_entries(raw)
        if not compiled:
            logger.warning(
                "Wiki compile for %s/%s produced no valid entries — keeping originals",
                repo,
                topic,
            )
            return len(entries)

        store._write_topic_page(topic_path, topic, compiled)
        store._rebuild_index(repo)
        store._append_log(
            repo,
            "compile",
            {
                "topic": topic,
                "before": len(entries),
                "after": len(compiled),
            },
        )

        logger.info(
            "Wiki compile %s/%s: %d entries → %d",
            repo,
            topic,
            len(entries),
            len(compiled),
        )
        return len(compiled)

    async def compile_topic_tracked(
        self,
        tracked_root: Path,
        repo: str,
        topic: str,
        *,
        other_topics: list[str] | None = None,
    ) -> int:
        """Tracked-layout counterpart of ``compile_topic``.

        Reads ``status: active`` per-entry files in
        ``{tracked_root}/{repo}/{topic}/*.md``, asks the LLM to
        synthesize / deduplicate, then:

        - Writes each compiled entry as a new per-entry file with
          ``source_phase: synthesis`` under a ``synthesis-<timestamp>``
          suffix so the filename doesn't collide with issue-tagged
          entries.
        - Flips every input entry's ``status`` to ``superseded`` with a
          ``superseded_by`` pointer to the first synthesis id (operators
          looking at a superseded entry can find the replacement).

        Returns the number of compiled entries written (0 if the LLM
        call failed or the topic had fewer than 2 active entries).

        The stale-flag path already writes to the tracked layout (Phase
        7), so combining this method with ``_maybe_open_maintenance_pr``
        lets ``RepoWikiLoop`` emit complete maintenance PRs without
        needing a separate synthesis sub-loop.
        """
        from repo_wiki import (  # noqa: PLC0415
            DEFAULT_TOPICS,
            _load_tracked_active_entries,
            _mark_tracked_entry_superseded,
            _write_tracked_synthesis_entry,
        )

        topic_dir = tracked_root / repo / topic
        active_entries = _load_tracked_active_entries(topic_dir)
        if len(active_entries) < 2:
            return 0

        entries_text = "\n\n".join(
            f"### {e['title']}\n{e['body']}\n"
            f"Source: #{e['source_issue'] or 'N/A'} ({e['source_phase']})\n"
            f"Created: {e['created_at']}"
            for e in active_entries
        )

        if other_topics is None:
            other_topics = [t for t in DEFAULT_TOPICS if t != topic]

        prompt = _COMPILE_TOPIC_PROMPT.format(
            topic=topic,
            repo=repo,
            entries_text=entries_text,
            other_topics=", ".join(other_topics),
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return 0

        compiled = self._parse_entries(raw)
        if not compiled:
            logger.warning(
                "Wiki compile_tracked for %s/%s produced no valid entries — "
                "keeping originals",
                repo,
                topic,
            )
            return 0

        superseded_ids = [e["id"] for e in active_entries]
        synthesis_paths: list[Path] = []
        for entry in compiled:
            path = _write_tracked_synthesis_entry(
                topic_dir,
                entry=entry,
                topic=topic,
                supersedes=superseded_ids,
            )
            synthesis_paths.append(path)

        if synthesis_paths:
            m = _SYNTHESIS_ID_RE.match(synthesis_paths[0].name)
            primary_id = m.group(1) if m else "unknown"
            for entry in active_entries:
                _mark_tracked_entry_superseded(
                    Path(entry["path"]), superseded_by=primary_id
                )

        logger.info(
            "Wiki compile_tracked %s/%s: %d active → %d synthesis",
            repo,
            topic,
            len(active_entries),
            len(compiled),
        )
        return len(compiled)

    async def synthesize_ingest(
        self,
        repo: str,
        issue_number: int,
        source_type: str,
        raw_text: str,
    ) -> list[WikiEntry]:
        """Use the LLM to extract knowledge entries from raw phase output.

        Instead of mechanical section parsing, the LLM identifies durable
        insights and produces structured entries.  Returns an empty list
        on failure.
        """
        if not raw_text or len(raw_text) < 100:
            return []

        # Cap input to avoid token limits
        truncated = raw_text[:20_000]

        prompt = _SYNTHESIZE_INGEST_PROMPT.format(
            source_type=source_type,
            issue_number=issue_number,
            repo=repo,
            raw_text=truncated,
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return []

        entries = self._parse_entries(raw)
        logger.info(
            "Wiki synthesize %s #%d (%s): %d entries extracted",
            repo,
            issue_number,
            source_type,
            len(entries),
        )
        return entries

    async def _call_model(self, prompt: str) -> str | None:
        """Call the configured CLI backend for wiki compilation.

        Never raises — all errors are logged and swallowed.
        """
        from agent_cli import build_lightweight_command  # noqa: PLC0415
        from subprocess_util import make_clean_env  # noqa: PLC0415

        tool = self._config.wiki_compilation_tool
        model = self._config.wiki_compilation_model
        cmd, cmd_input = build_lightweight_command(
            tool=tool, model=model, prompt=prompt
        )
        env = make_clean_env(self._credentials.gh_token)

        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self._config.wiki_compilation_timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "Wiki compilation model failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:200],
                )
                return None
            return result.stdout if result.stdout else None
        except TimeoutError:
            logger.warning("Wiki compilation model timed out")
            return None
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            logger.warning("Wiki compilation model unavailable: %s", exc)
            return None

    @staticmethod
    def _parse_entries(raw: str) -> list[WikiEntry]:
        """Parse LLM output into WikiEntry objects.

        Tolerant of markdown fences and extra text around the JSON array.
        """
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            # Remove first and last lines (fences)
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        # Find the JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Wiki compiler output has no JSON array")
            return []

        try:
            items = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Wiki compiler output is not valid JSON")
            return []

        entries: list[WikiEntry] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(
                    WikiEntry(
                        title=item.get("title", "Untitled"),
                        content=item.get("content", ""),
                        source_type=item.get("source_type", "compiled"),
                        source_issue=item.get("source_issue"),
                        stale=item.get("stale", False),
                    )
                )
            except Exception:  # noqa: BLE001
                logger.warning("Skipping invalid entry from compiler output")

        return entries
