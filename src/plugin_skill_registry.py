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

    Returns an empty list if ``cache_root`` is missing. Skills with malformed
    frontmatter are skipped with a warning. The ``using-superpowers``
    meta-skill is always excluded.
    """
    root = cache_root or _DEFAULT_CACHE_ROOT
    if not root.is_dir():
        return []

    allowlist = set(plugins)
    skills: list[PluginSkill] = []

    for marketplace_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
            if plugin_dir.name not in allowlist:
                continue
            skills.extend(_discover_plugin(plugin_dir))

    return skills


def _discover_plugin(plugin_dir: Path) -> list[PluginSkill]:
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return []

    out: list[PluginSkill] = []
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
    convention and are joined with spaces.
    """
    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            value = line[len(key) + 1 :].strip()
            j = i + 1
            while j < len(lines) and lines[j].startswith(("  ", "\t")):
                value = f"{value} {lines[j].strip()}"
                j += 1
            return value or None
    return None


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
        'Invoke a skill with `Skill({skill: "plugin:name"})` when its '
        "description matches your current task.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.qualified_name}** — {skill.description}")
    lines.append("")
    return "\n".join(lines)
