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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from knowledge_metrics import metrics as _metrics
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


class GeneralizationCheck(BaseModel):
    same_principle: bool = False
    generalized_title: str = ""
    generalized_body: str = ""
    confidence: Literal["high", "medium", "low"] = "low"


class CorroborationDecision(BaseModel):
    """Outcome of ``WikiCompiler.dedup_or_corroborate``.

    When ``should_corroborate`` is True, the caller should bump
    ``canonical_path``'s ``corroborations`` counter instead of writing
    the new entry as a sibling. ``canonical_path`` is carried directly
    because ``WikiEntry.id`` is a ULID while filenames use a separate
    per-topic sequential prefix — there's no reliable id → path map.
    """

    should_corroborate: bool = False
    canonical_title: str = ""
    canonical_id: str = ""
    canonical_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


class ADRDraftDecision(BaseModel):
    two_plus_issues: bool = False
    in_tribal: bool = False
    architectural: bool = False
    load_bearing: bool = False
    draft_ok: bool = False
    reason: str = ""


if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore
    from tribal_wiki import TribalWikiStore

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

## Voice and structure (load-bearing — do not skip)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

Required shape for each entry:

- Open with a one-sentence rule statement (no narrative ramp-up).
- Follow with a short example (inline code, file path, or 2-3 bullet
  points) showing the rule in use. If the rule is purely conceptual,
  skip the example.
- Close with a `**Why:**` line in one sentence, naming the failure mode
  or constraint the rule prevents.

Hard length budget per entry:

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone (avoid generic labels like "Notes",
  "Findings", "Background").
- `content`: ≤ 150 words. If the source material exceeds this, **split
  into multiple entries** rather than producing a single long blob.

Anti-patterns to avoid:

- Long single-paragraph dumps with no structure.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Output format

Return a JSON array of compiled entries. Each entry must be a JSON object with these fields:
- "title": string (short, descriptive — see length budget above)
- "content": string (rule + example + Why; see structure above)
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

_GENERALIZATION_PROMPT = """\
You are a technical knowledge librarian comparing two wiki entries from
different repositories, both on topic **{topic}**. Decide whether they
encode the **same underlying principle** (not merely the same keywords).

## Entry A (repo: {repo_a})

title: {title_a}
content:
{content_a}

## Entry B (repo: {repo_b})

title: {title_b}
content:
{content_b}

## Instructions

Return a JSON object with these keys:
- same_principle: bool — true only if both entries advise the same rule in
  a way that would generalize across any Python project
- generalized_title: str — if same_principle is true, a short neutral title
- generalized_body: str — if same_principle is true, merged content that drops
  repo-specific details
- confidence: "high" | "medium" | "low" — how sure you are

Return ONLY the JSON object, no other text.

Example outputs:
  {{"same_principle": false, "generalized_title": "", "generalized_body": "", "confidence": "low"}}
  {{"same_principle": true, "generalized_title": "Pytest async mode", "generalized_body": "Configure pytest-asyncio with mode=auto.", "confidence": "high"}}
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

## Voice and structure (load-bearing — do not skip)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

Required shape for each entry:

- Open with a one-sentence rule statement (no narrative ramp-up).
- Follow with a short example (inline code, file path, or 2-3 bullet
  points) showing the rule in use. If the rule is purely conceptual,
  skip the example.
- Close with a `**Why:**` line in one sentence, naming the failure mode
  or constraint the rule prevents.

Hard length budget per entry:

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone (avoid generic labels like "Notes",
  "Findings", "Background", or "{source_type} from #{issue_number}").
- `content`: ≤ 150 words. If the source material exceeds this, **emit
  multiple entries** rather than producing a single long blob.

Anti-patterns to avoid:

- Long single-paragraph dumps with no structure.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Output format

Return a JSON array of entries. Each entry must be:
- "title": string (≤ 80 chars, descriptive — see length budget above)
- "content": string (rule + example + Why; ≤ 150 words)
- "source_type": "{source_type}"
- "source_issue": {issue_number}

Return ONLY the JSON array, no other text.
"""


_ADR_DRAFT_JUDGE_PROMPT = """\
You are a technical knowledge librarian evaluating whether a pattern rises to
ADR-worthy architectural status. Review the proposed ADR draft below and
answer two questions strictly:

1. **architectural**: does it change a system-level invariant (loop topology,
   state machine, persistence layout, promotion flow, module boundary)?
   Operational tips, style conventions, and per-phase workflows are NOT
   architectural.
2. **load_bearing**: if this decision were reversed tomorrow, would multiple
   components need to change?

## Proposed ADR

title: {title}
context: {context}
decision: {decision}
consequences: {consequences}

Return ONLY a JSON object:
  {{"architectural": <bool>, "load_bearing": <bool>, "reason": "<1 sentence>"}}
"""


# ---------------------------------------------------------------------------
# ADR draft suggestion parser
# ---------------------------------------------------------------------------

_ADR_DRAFT_HEADER_RE = re.compile(r"^ADR_DRAFT_SUGGESTION:\s*$", re.MULTILINE)


def parse_adr_draft_suggestion(transcript: str) -> dict | None:
    """Parse an ADR_DRAFT_SUGGESTION block from a transcript.

    Returns a dict with keys: title, context, decision, consequences,
    evidence_issues (list[int]), evidence_wiki_entries (list[str]).
    Returns None when no block is found or parsing fails.
    """
    header = _ADR_DRAFT_HEADER_RE.search(transcript)
    if header is None:
        return None

    tail = transcript[header.end() :]
    fields: dict[str, Any] = {
        "title": "",
        "context": "",
        "decision": "",
        "consequences": "",
        "evidence_issues": [],
        "evidence_wiki_entries": [],
    }
    current_key: str | None = None
    in_evidence = False
    for line in tail.split("\n"):
        if not line.strip():
            if current_key in {"title"}:
                current_key = None
            continue
        stripped = line.rstrip()
        # Field heading like "title: Foo"
        m = re.match(
            r"^(title|context|decision|consequences|evidence):\s*(.*)$", stripped
        )
        if m:
            key = m.group(1)
            rest = m.group(2).strip()
            if key == "evidence":
                in_evidence = True
                current_key = None
                continue
            in_evidence = False
            current_key = key
            fields[key] = rest
            continue

        if in_evidence:
            sm = re.match(r"^\s*-\s*issue:\s*(\d+)\s*$", stripped)
            if sm:
                fields["evidence_issues"].append(int(sm.group(1)))
                continue
            sm = re.match(r"^\s*-\s*wiki_entry:\s*([0-9A-Z]{26})\s*$", stripped)
            if sm:
                fields["evidence_wiki_entries"].append(sm.group(1))
                continue
            # End of evidence list (non-bullet line that isn't indented)
            if not line.startswith((" ", "\t")):
                in_evidence = False

        if current_key and line.startswith("  "):
            fields[current_key] = (fields[current_key] + " " + stripped.strip()).strip()

    if not fields["title"]:
        return None
    return fields


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

    @staticmethod
    def _parse_generalization_output(raw: str) -> GeneralizationCheck:
        """Parse generalization-check LLM output. Never raises."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return GeneralizationCheck()
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return GeneralizationCheck()
        if not isinstance(obj, dict):
            return GeneralizationCheck()
        try:
            return GeneralizationCheck.model_validate(obj)
        except Exception:  # noqa: BLE001
            return GeneralizationCheck()

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

    async def detect_contradictions(
        self,
        *,
        new_entry: WikiEntry,
        siblings: list[WikiEntry],
        repo: str,
    ) -> ContradictionCheck:
        """Ask the LLM which siblings (if any) the new entry contradicts.

        ``siblings`` must already be filtered to ``current`` entries on the
        same topic. Returns an empty ContradictionCheck on LLM failure or if
        siblings is empty — never raises.
        """
        if not siblings:
            return ContradictionCheck()

        siblings_text = "\n\n".join(
            f"id: {s.id}\ntitle: {s.title}\ncontent:\n{s.content}" for s in siblings
        )
        prompt = _CONTRADICTION_PROMPT.format(
            topic=new_entry.topic or "unknown",
            repo=repo,
            new_title=new_entry.title,
            new_content=new_entry.content,
            siblings_text=siblings_text,
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return ContradictionCheck()
        return self._parse_contradiction_output(raw)

    async def generalize_pair(
        self,
        *,
        entry_a: WikiEntry,
        entry_b: WikiEntry,
        topic: str,
    ) -> GeneralizationCheck:
        """Ask the LLM whether two entries encode the same principle.

        Returns an empty GeneralizationCheck on LLM failure — never raises.
        Caller decides whether to act on ``same_principle`` given
        ``confidence``.
        """
        prompt = _GENERALIZATION_PROMPT.format(
            topic=topic,
            repo_a=entry_a.source_repo or "unknown",
            title_a=entry_a.title,
            content_a=entry_a.content,
            repo_b=entry_b.source_repo or "unknown",
            title_b=entry_b.title,
            content_b=entry_b.content,
        )
        raw = await self._call_model(prompt)
        if raw is None:
            return GeneralizationCheck()
        return self._parse_generalization_output(raw)

    async def dedup_or_corroborate(
        self,
        *,
        repo_slug: str,
        entry: WikiEntry,
        existing_entries: list[tuple[WikiEntry, Path]],
        topic: str,
        min_confidence: Literal["medium", "high"] = "medium",
    ) -> CorroborationDecision:
        """Use ``generalize_pair`` to decide whether ``entry`` is a
        re-discovery of an existing active entry.

        ``existing_entries`` carries ``(WikiEntry, Path)`` tuples so the
        path travels with the entry — the caller then bumps the
        canonical's ``corroborations`` counter without re-walking the
        topic directory. Stops at the first confident match: we don't
        need to rank matches, just detect one.

        Returns an empty decision (``should_corroborate=False``) when
        there are no existing entries, or no match hits the confidence
        floor.
        """
        del repo_slug  # carried for symmetry with other compiler methods
        if not existing_entries:
            return CorroborationDecision()
        acceptable = {"high"} if min_confidence == "high" else {"high", "medium"}
        for existing, existing_path in existing_entries:
            check = await self.generalize_pair(
                entry_a=entry, entry_b=existing, topic=topic
            )
            if check.same_principle and check.confidence in acceptable:
                return CorroborationDecision(
                    should_corroborate=True,
                    canonical_title=existing.title,
                    canonical_id=existing.id,
                    canonical_path=existing_path,
                )
        return CorroborationDecision()

    async def judge_adr_draft(
        self,
        *,
        suggestion: dict,
        tribal: TribalWikiStore,
    ) -> ADRDraftDecision:
        """Evaluate the 4 gates for an ADR_DRAFT_SUGGESTION."""
        _metrics.increment("adr_drafts_judged")
        decision = ADRDraftDecision()

        # Gate 1 — evidence list has ≥2 distinct issues
        issues = suggestion.get("evidence_issues", [])
        decision.two_plus_issues = len(set(issues)) >= 2
        if not decision.two_plus_issues:
            decision.reason = "needs ≥2 distinct issues as evidence"
            return decision

        # Gate 2 — at least one cited wiki entry lives in tribal
        wiki_ids = suggestion.get("evidence_wiki_entries", [])
        if not wiki_ids:
            decision.reason = "no tribal wiki entry cited"
            return decision
        from repo_wiki import DEFAULT_TOPICS  # noqa: PLC0415

        tribal_ids: set[str] = set()
        tribal_repo_dir = tribal.repo_dir()
        for topic_name in DEFAULT_TOPICS:
            topic_path = tribal_repo_dir / f"{topic_name}.md"
            if topic_path.exists():
                for entry in tribal.load_topic_entries(topic_path):
                    tribal_ids.add(entry.id)
        decision.in_tribal = any(wid in tribal_ids for wid in wiki_ids)
        if not decision.in_tribal:
            decision.reason = "referenced wiki entry not present in tribal store"
            return decision

        # Gates 3 + 4 (LLM)
        prompt = _ADR_DRAFT_JUDGE_PROMPT.format(
            title=suggestion.get("title", ""),
            context=suggestion.get("context", ""),
            decision=suggestion.get("decision", ""),
            consequences=suggestion.get("consequences", ""),
        )
        raw = await self._call_model(prompt)
        if raw is None:
            decision.reason = "llm unavailable"
            return decision
        parsed = self._parse_adr_judge_output(raw)
        decision.architectural = bool(parsed.get("architectural", False))
        decision.load_bearing = bool(parsed.get("load_bearing", False))
        decision.reason = str(parsed.get("reason", ""))

        decision.draft_ok = (
            decision.two_plus_issues
            and decision.in_tribal
            and decision.architectural
            and decision.load_bearing
        )
        return decision

    @staticmethod
    def _parse_adr_judge_output(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {}
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return obj if isinstance(obj, dict) else {}

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
