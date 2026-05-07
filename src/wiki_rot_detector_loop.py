"""WikiRotDetectorLoop — weekly wiki cite freshness detector (spec §4.9).

Walks every ``RepoWikiStore``-registered repo, extracts cited code
references from each wiki entry via three patterns (``path.py:symbol``,
dotted ``src.module.Class``, and bare identifiers inside ``python``
fences — hints only), and verifies each hard cite against:

- **HydraFlow-self** (``config.repo_root``) via AST introspection —
  catches re-exports and ``__init__.py`` re-bindings that grep misses.
- **Managed repos** via grep over wiki markdown mirrors only — full
  AST verification across every managed repo is out of scope for v1
  and noted below as a follow-up.

For each broken cite the loop files a ``hydraflow-find`` + ``wiki-rot``
issue through :class:`PRManager` with a fuzzy-match suggestion (via
:func:`difflib.get_close_matches`) when the containing module exists.
After 3 unresolved attempts per ``(slug, cite)`` subject the loop
escalates to ``hitl-escalation`` + ``wiki-rot-stuck``. Dedup keys and
attempt counters clear on escalation close per spec §3.2.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="wiki_rot_detector"``
— **no ``wiki_rot_detector_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult
from wiki_rot_citations import (
    Cite,
    extract_cites,
    extract_fenced_hints,
    fuzzy_suggest,
    verify_cite_ast,
    verify_cite_grep,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from repo_wiki import RepoWikiStore
    from state import StateTracker

logger = logging.getLogger("hydraflow.wiki_rot_detector_loop")

_MAX_ATTEMPTS = 3
_EXCERPT_CHARS = 500
_ISSUE_LABELS_FIND: tuple[str, ...] = ("hydraflow-find", "wiki-rot")
_ISSUE_LABELS_ESCALATE: tuple[
    str, ...
] = ()  # replaced by config-driven labels; kept for import compat


class WikiRotDetectorLoop(BaseBackgroundLoop):
    """Detects broken code cites in per-repo wikis (spec §4.9)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="wiki_rot_detector",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._wiki = wiki_store

    def _get_default_interval(self) -> int:
        return self._config.wiki_rot_detector_interval

    # -- main tick ---------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Scan every repo wiki, file an issue per broken cite, escalate
        repeat offenders.  Guarded by the kill-switch at the top so a
        mid-tick flip takes effect on the next cycle.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        import time  # noqa: PLC0415

        t0 = time.perf_counter()

        await self._reconcile_closed_escalations()

        self_slug = self._config.repo or ""
        repos = list(self._wiki.list_repos())
        if repos and self_slug and self_slug not in repos:
            # Ensure we always scan HydraFlow-self when the wiki has at
            # least one seeded repo (cite extraction yields 0 otherwise).
            repos.insert(0, self_slug)

        scanned = 0
        filed = 0
        escalated = 0
        for slug in repos:
            try:
                result = await self._tick_repo(slug, self_slug)
            except Exception:  # noqa: BLE001
                logger.exception("wiki_rot_detector: slug=%s failed", slug)
                continue
            scanned += 1
            filed += result["filed"]
            escalated += result["escalated"]

        status = "fired" if filed or escalated else "noop"
        self._emit_trace(t0, scanned=scanned, filed=filed, escalated=escalated)
        return {
            "status": status,
            "repos_scanned": scanned,
            "issues_filed": filed,
            "escalations": escalated,
        }

    def _emit_trace(
        self,
        t0: float,
        *,
        scanned: int,
        filed: int,
        escalated: int,
    ) -> None:
        """Best-effort subprocess trace via lazy-imported ``trace_collector``.

        Uses the module's real signature
        ``(loop, command, exit_code, duration_ms, stderr_excerpt)``.
        Import failure, missing attr, or an emit exception all no-op —
        tick telemetry never fails the loop (§12.2 sibling lock).
        """
        import time  # noqa: PLC0415

        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        if emit_loop_subprocess_trace is None:  # patched to None in tests
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        try:
            emit_loop_subprocess_trace(
                loop=self._worker_name,
                command=["gh", "issue", "list", "--label", "wiki-rot-stuck"],
                exit_code=0,
                duration_ms=duration_ms,
                stderr_excerpt=(
                    f"scanned={scanned} filed={filed} escalated={escalated}"
                ),
            )
        except Exception:  # noqa: BLE001
            logger.debug("trace emission failed", exc_info=True)

    async def _tick_repo(
        self,
        slug: str,
        self_slug: str,
    ) -> dict[str, int]:
        """Scan one repo's wiki entries, verify cites, file issues, and
        escalate repeat offenders.

        Returns counts ``{"filed": n, "escalated": n}``.  Failures on
        a single entry are logged and skipped — the tick never aborts
        mid-repo.
        """
        filed = 0
        escalated = 0

        entries = self._load_wiki_entries(slug)
        if not entries:
            return {"filed": 0, "escalated": 0}

        is_self = slug == self_slug and bool(self_slug)
        repo_root = Path(self._config.repo_root)
        dedup_seen = self._dedup.get()

        for title, body, entry_path in entries:
            cites = extract_cites(body)
            hints = extract_fenced_hints(body)
            for cite in cites:
                broken, suggestion = self._check_cite(cite, repo_root, is_self)
                if not broken:
                    continue
                subject = f"{slug}:{cite.raw}"
                dedup_key = f"wiki_rot_detector:{subject}"
                if dedup_key in dedup_seen:
                    continue

                filed += 1
                await self._file_find(
                    slug=slug,
                    entry_title=title,
                    entry_path=str(entry_path),
                    body=body,
                    cite=cite,
                    suggestion=suggestion,
                    hints=hints,
                )
                dedup_seen.add(dedup_key)

                attempts = self._state.inc_wiki_rot_attempts(subject)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        slug=slug,
                        cite=cite,
                        attempts=attempts,
                    )
                    escalated += 1

        self._dedup.set_all(dedup_seen)
        return {"filed": filed, "escalated": escalated}

    # -- helpers -----------------------------------------------------------

    def _load_wiki_entries(
        self,
        slug: str,
    ) -> list[tuple[str, str, Path]]:
        """Return ``[(title, body, path), ...]`` for every markdown entry
        in the repo's wiki — supports both the legacy topic-file layout
        and the Phase 3 per-entry layout.  Title defaults to the file
        stem when no ``# Heading`` is present.
        """
        try:
            repo_dir = self._wiki.repo_dir(slug)
        except Exception:  # noqa: BLE001
            logger.debug("wiki.repo_dir(%s) failed", slug, exc_info=True)
            return []
        if not repo_dir.is_dir():
            return []

        out: list[tuple[str, str, Path]] = []
        for md_path in sorted(repo_dir.rglob("*.md")):
            if md_path.name in {"index.md", "log.md"}:
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = _first_heading(text) or md_path.stem
            out.append((title, text, md_path))
        return out

    def _check_cite(
        self,
        cite: Cite,
        repo_root: Path,
        is_self: bool,
    ) -> tuple[bool, str | None]:
        """Verify *cite* and emit a fuzzy suggestion when plausible.

        Returns ``(broken, suggestion)``.  ``broken`` is ``True`` when
        the cite does not resolve; ``suggestion`` is a close-match
        symbol name from the same module, or ``None`` when no close
        match exists / the module itself is missing.
        """
        if cite.style == "fenced_hint":
            return (False, None)  # hints never trigger fires

        module_path = cite.module_as_path()

        if is_self:
            ok, symbols = verify_cite_ast(repo_root, module_path, cite.symbol)
            if ok:
                return (False, None)
            suggestion: str | None = None
            if symbols:
                # Prefer a fuzzy close-match; fall back to the first
                # defined symbol so operators always have *some* anchor
                # pointing into the real module.
                suggestion = fuzzy_suggest(cite.symbol, symbols) or symbols[0]
            return (True, suggestion)

        # Managed repo — grep wiki markdown mirrors only (AST verification
        # against unchecked-out managed-repo sources is out of scope v1).
        ok = verify_cite_grep(repo_root, module_path, cite.symbol)
        return (not ok, None)

    async def _file_find(
        self,
        *,
        slug: str,
        entry_title: str,
        entry_path: str,
        body: str,
        cite: Cite,
        suggestion: str | None,
        hints: list[Cite],
    ) -> None:
        title = f"Wiki rot: {entry_title} cites missing {cite.raw}"
        excerpt = _excerpt_around(body, cite.raw, _EXCERPT_CHARS)
        lines: list[str] = [
            "**Automated detection — WikiRotDetectorLoop (spec §4.9).**",
            "",
            f"- Repo: `{slug}`",
            f"- Entry: `{entry_path}` — *{entry_title}*",
            f"- Broken cite: `{cite.raw}` ({cite.style})",
        ]
        if suggestion:
            lines.append(f"- Did you mean: {suggestion}?")
        if hints:
            hint_names = ", ".join(sorted({h.symbol for h in hints})[:10])
            lines.append(f"- Fenced-code hints (context only): {hint_names}")
        lines += [
            "",
            "### Entry excerpt",
            "",
            "```markdown",
            excerpt,
            "```",
            "",
            "Repair path: implementer updates the cite or removes the "
            "stale entry; the caretaker wiki loop compiles the patch "
            "through the standard review + auto-merge flow.",
        ]
        body_out = "\n".join(lines)
        await self._pr.create_issue(
            title,
            body_out,
            list(_ISSUE_LABELS_FIND),
        )

    async def _file_escalation(
        self,
        *,
        slug: str,
        cite: Cite,
        attempts: int,
    ) -> None:
        title = f"Wiki rot stuck: {slug} cites missing {cite.raw}"
        body = (
            "**Escalation — WikiRotDetectorLoop (spec §4.9 / §3.2).**\n\n"
            f"- Repo: `{slug}`\n"
            f"- Broken cite: `{cite.raw}`\n"
            f"- Attempts: `{attempts}` ≥ `{_MAX_ATTEMPTS}` — repair loop "
            "has not closed the finding within the retry budget.\n\n"
            "Human: resolve the cite or remove the wiki entry, then "
            "close this issue. The dedup key + attempt counter clear "
            "automatically on close (spec §3.2).\n"
        )
        await self._pr.create_issue(
            title,
            body,
            [
                self._config.hitl_escalation_label[0],
                self._config.wiki_rot_stuck_label[0],
            ],
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Poll closed ``wiki-rot-stuck`` escalations and clear the
        matching dedup key + attempt counter.  Called at the top of
        every tick; close-to-clear latency is bounded by the loop
        interval (spec §3.2).
        """
        try:
            closed = await self._gh_closed_escalations()
        except Exception:  # noqa: BLE001
            logger.debug("reconcile: gh list failed", exc_info=True)
            return

        if not closed:
            return

        current = self._dedup.get()
        to_clear: set[str] = set()
        for issue in closed:
            subject = _parse_escalation_subject(
                str(issue.get("title", "")),
                str(issue.get("body", "")),
            )
            if subject is None:
                continue
            key = f"wiki_rot_detector:{subject}"
            if key in current:
                to_clear.add(key)
            self._state.clear_wiki_rot_attempts(subject)

        if to_clear:
            remaining = current - to_clear
            self._dedup.set_all(remaining)

    async def _gh_closed_escalations(self) -> list[dict[str, Any]]:
        """Return the list of closed ``hitl-escalation`` +
        ``wiki-rot-stuck`` issues authored by this bot.

        Shells out to ``gh issue list`` to avoid a PRManager dependency
        on a rarely-used endpoint.  JSON parse / non-zero exit → empty
        list (tolerant — reconciliation is best-effort).
        """
        import asyncio  # noqa: PLC0415
        import json  # noqa: PLC0415
        import subprocess  # noqa: PLC0415

        cmd = [
            "gh",
            "issue",
            "list",
            "--state",
            "closed",
            "--label",
            self._config.hitl_escalation_label[0],
            "--label",
            self._config.wiki_rot_stuck_label[0],
            "--author",
            "@me",
            "--json",
            "number,title,body",
            "--limit",
            "50",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except (OSError, FileNotFoundError):
            return []
        if proc.returncode != 0:
            return []
        try:
            data = json.loads(stdout or b"[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []


# -- module helpers --------------------------------------------------------


def _parse_escalation_subject(title: str, body: str) -> str | None:
    """Extract ``{slug}:{cite}`` from an escalation issue.

    Title format: ``Wiki rot stuck: {slug} cites missing {cite}``.
    ``{slug}`` is parsed directly from the title (everything between
    ``stuck: `` and `` cites missing ``); falls back to a ``Repo: `` line
    in the body on malformed titles.
    """
    prefix = "Wiki rot stuck: "
    anchor = " cites missing "
    if not title.startswith(prefix) or anchor not in title:
        return None
    slug_plus_tail = title[len(prefix) :]
    slug, _, cite = slug_plus_tail.partition(anchor)
    slug = slug.strip()
    cite = cite.strip()
    if not slug or not cite:
        # Fallback: ``Repo: `slug`` in body.
        for line in body.splitlines():
            if line.strip().startswith("- Repo:") or line.strip().startswith("Repo:"):
                slug = line.split("`")[1] if "`" in line else slug
                break
    if not slug or not cite:
        return None
    return f"{slug}:{cite}"


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _excerpt_around(body: str, needle: str, limit: int) -> str:
    """Return a ≤*limit*-char window centered on *needle* — or the head
    of *body* if *needle* is near the top / absent.
    """
    if len(body) <= limit:
        return body
    idx = body.find(needle)
    if idx < 0:
        return body[:limit]
    start = max(0, idx - limit // 2)
    end = min(len(body), start + limit)
    return body[start:end]
