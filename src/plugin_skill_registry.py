"""Discover and format installed Claude Code plugin skills for factory prompts.

Scans ``~/.claude/plugins/cache/<marketplace>/<plugin>/skills/<skill>/SKILL.md``
for frontmatter (``name`` + ``description``), builds a list of
:class:`PluginSkill`, and formats them as a ``## Available Skills`` section
injected into factory phase prompts.

See ``docs/superpowers/specs/2026-04-18-dynamic-plugin-skill-registry-design.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hydraflow.plugin_skill_registry")

_DEFAULT_CACHE_ROOT = Path.home() / ".claude" / "plugins" / "cache"

# Meta-skills that route to other skills — excluded from factory prompts
# because the factory advertises skills directly.
_EXCLUDED_SKILL_NAMES: frozenset[str] = frozenset({"using-superpowers"})

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_KEY_PREFIX_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")

DEFAULT_MARKETPLACE = "claude-plugins-official"


def parse_plugin_spec(spec: str) -> tuple[str, str]:
    """Parse a plugin spec into ``(name, marketplace)``.

    Accepts ``"name"`` (default marketplace) or ``"name@marketplace"``.
    Raises :class:`ValueError` on empty, double-``@``, or empty halves.
    """
    cleaned = spec.strip()
    if not cleaned:
        raise ValueError(f"Empty plugin spec: {spec!r}")
    parts = [p.strip() for p in cleaned.split("@")]
    if len(parts) == 1:
        return parts[0], DEFAULT_MARKETPLACE
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    raise ValueError(f"Malformed plugin spec: {spec!r}")


@dataclass(frozen=True)
class PluginSkill:
    """A Claude Code skill discovered from an installed plugin."""

    plugin: str
    name: str
    description: str

    @property
    def qualified_name(self) -> str:
        return f"{self.plugin}:{self.name}"


def discover_plugin_skills(
    plugins: list[str],
    cache_root: Path | None = None,
) -> list[PluginSkill]:
    """Discover skills from allowlisted plugins under ``cache_root``.

    Results are cached in memory keyed by ``(frozenset(plugins), resolved_root)``
    so repeated calls within a process do not re-scan the filesystem. Tests
    must call :func:`clear_plugin_skill_cache` between cases to avoid leakage.

    Returns an empty list if ``cache_root`` is missing. Skills with malformed
    frontmatter are skipped with a warning. The ``using-superpowers``
    meta-skill is always excluded.
    """
    root = cache_root or _DEFAULT_CACHE_ROOT
    key = (frozenset(plugins), root)
    cached = _skill_cache.get(key)
    if cached is not None:
        return list(cached)

    if not root.is_dir():
        _skill_cache[key] = ()
        return []

    allowlist = set(plugins)
    skills: list[PluginSkill] = []

    for marketplace_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
            if plugin_dir.name not in allowlist:
                continue
            skills.extend(_discover_plugin(plugin_dir))

    _skill_cache[key] = tuple(skills)
    return skills


def _discover_plugin(plugin_dir: Path) -> list[PluginSkill]:
    """Scan a plugin directory for skills.

    The cache layout is ``<marketplace>/<plugin>/<version_or_hash>/skills/<skill>/SKILL.md``.
    A single plugin can have multiple sibling version directories (e.g. a semver
    tag and an ``unknown`` alias). We scan all of them and dedupe by skill name,
    keeping the first occurrence in sorted directory order.
    """
    out: list[PluginSkill] = []
    seen: set[str] = set()

    for version_dir in sorted(p for p in plugin_dir.iterdir() if p.is_dir()):
        skills_dir = version_dir / "skills"
        if not skills_dir.is_dir():
            continue
        for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            if skill_dir.name in _EXCLUDED_SKILL_NAMES:
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            parsed = _parse_skill_md(skill_md)
            if parsed is None:
                logger.warning(
                    "Skipping %s — malformed or missing frontmatter",
                    skill_md,
                )
                continue
            name, description = parsed
            if name in seen:
                continue
            seen.add(name)
            out.append(
                PluginSkill(plugin=plugin_dir.name, name=name, description=description)
            )
    return out


def _parse_skill_md(path: Path) -> tuple[str, str] | None:
    """Return (name, description) parsed from SKILL.md frontmatter.

    Returns ``None`` if the file can't be read, has no frontmatter, or is
    missing either the ``name`` or ``description`` key.
    """
    try:
        text = path.read_text()
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    name = _extract_key(match.group(1), "name")
    description = _extract_key(match.group(1), "description")
    if not name or not description:
        return None
    return name, description


def _extract_key(frontmatter: str, key: str) -> str | None:
    """Extract a top-level key value from simple YAML frontmatter.

    Intentionally does NOT depend on a YAML library — SKILL.md frontmatter is
    always flat key/value pairs. Multi-line values use the folded-on-next-line
    convention and are joined with spaces. Prefix-match collisions are avoided
    by requiring an exact key match via ``_KEY_PREFIX_RE``.
    """
    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        match = _KEY_PREFIX_RE.match(line)
        if match is None or match.group(1) != key:
            continue
        value = match.group(2).strip()
        j = i + 1
        while j < len(lines) and lines[j].startswith(("  ", "\t")):
            value = f"{value} {lines[j].strip()}"
            j += 1
        return value or None
    return None


# ---------------------------------------------------------------------------
# Discovery cache — keyed by (frozenset(plugins), resolved cache root).
# Cleared via clear_plugin_skill_cache() in tests.
# ---------------------------------------------------------------------------

_skill_cache: dict[tuple[frozenset[str], Path], tuple[PluginSkill, ...]] = {}


def clear_plugin_skill_cache() -> None:
    """Clear the in-memory discovery cache. Intended for tests."""
    _skill_cache.clear()


def format_plugin_skills_for_prompt(skills: list[PluginSkill]) -> str:
    """Format discovered skills as a prompt section for a factory agent.

    Returns an empty string when ``skills`` is empty so callers can
    unconditionally concatenate the result.
    """
    if not skills:
        return ""
    lines = [
        "## Available Skills",
        "",
        "You have these Claude Code skills available via the `Skill` tool. "
        "Invoke one by calling the `Skill` tool with its qualified name "
        '(e.g. `skill: "superpowers:brainstorming"`) when its description '
        "matches your current task.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.qualified_name}** — {skill.description}")
    lines.append("")
    return "\n".join(lines)
