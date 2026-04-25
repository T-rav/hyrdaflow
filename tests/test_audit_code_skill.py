"""Structural guards for the hf.audit-code skill file (#6427).

These tests enforce that the skill prompt matches the expectations of
``src/code_grooming_loop.py`` — specifically, that it launches the
expected set of audit agents and that the new Agent 5 (convention drift)
reads the canonical avoided-patterns doc at runtime instead of
hardcoding rules into the prompt.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_FILE = REPO_ROOT / ".claude" / "commands" / "hf.audit-code.md"


def _read_skill() -> str:
    assert SKILL_FILE.exists(), f"{SKILL_FILE} missing"
    return SKILL_FILE.read_text(encoding="utf-8")


class TestAuditCodeSkillStructure:
    def test_skill_file_exists(self) -> None:
        assert SKILL_FILE.exists()

    def test_fanout_declares_five_agents(self) -> None:
        content = _read_skill()
        # The orchestration step must enumerate all five agents.
        for agent in (
            "Agent 1: Dead code",
            "Agent 2: Method size",
            "Agent 3: Error handling",
            "Agent 4: Type safety",
            "Agent 5: Convention drift",
        ):
            assert agent in content, f"missing fanout entry: {agent}"

    def test_each_agent_has_its_own_section(self) -> None:
        content = _read_skill()
        for heading in (
            "## Agent 1: Dead Code",
            "## Agent 2: Method Size",
            "## Agent 3: Error Handling",
            "## Agent 4: Type Safety",
            "## Agent 5: Convention Drift",
        ):
            assert heading in content, f"missing section: {heading}"


class TestAgent5ConventionDrift:
    def test_agent5_reads_avoided_patterns_doc_at_runtime(self) -> None:
        """Agent 5 must read docs/wiki/gotchas.md, not hardcode rules."""
        content = _read_skill()
        # The Agent 5 body must mention reading the canonical doc.
        agent5_start = content.find("## Agent 5:")
        assert agent5_start != -1
        agent5_body = content[agent5_start:]
        assert "docs/wiki/gotchas.md" in agent5_body, (
            "Agent 5 must reference docs/wiki/gotchas.md as the "
            "runtime source of rules. Do not hardcode patterns in the prompt."
        )

    def test_agent5_lists_over_engineering_categories(self) -> None:
        content = _read_skill()
        agent5_start = content.find("## Agent 5:")
        agent5_body = content[agent5_start:]
        # The over-engineering sweep must cover the documented categories.
        for category in (
            "Single-use helpers",
            "Speculative abstractions",
            "Defensive handling",
            "Backwards-compat shims",
            "Feature-flag rot",
        ):
            assert category in agent5_body, (
                f"Agent 5 must sweep for over-engineering category: {category}"
            )

    def test_agent5_emits_json_schema_compatible_with_parser(self) -> None:
        """Findings must be emitted in the schema code_grooming_loop parses."""
        content = _read_skill()
        agent5_start = content.find("## Agent 5:")
        agent5_body = content[agent5_start:]
        # The _FINDING_RE in code_grooming_loop.py parses objects with
        # "id" and "severity" keys. Agent 5 must match that schema.
        assert '"id"' in agent5_body
        assert '"severity"' in agent5_body

    def test_agent5_references_avoided_patterns_doc_as_source_of_truth(self) -> None:
        """The keep-in-sync principle should be stated explicitly."""
        content = _read_skill()
        agent5_start = content.find("## Agent 5:")
        agent5_body = content[agent5_start:]
        # We phrase this as "reads ... at runtime" in the prompt.
        assert "at runtime" in agent5_body or "runtime" in agent5_body
