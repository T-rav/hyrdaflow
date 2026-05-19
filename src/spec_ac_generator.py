"""SpecACGenerator — drafts acceptance criteria from a plan, pre-implementation.

Sibling of (not a refactor of) ``src/acceptance_criteria.py``. That module
judges AC against real merged code and diffs; this one drafts AC against the
plan text alone, before any code exists. They run at different points in the
pipeline with different inputs and different prompts; the duplication is
intentional.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from exception_classify import reraise_on_credit_or_bug
from src.adversarial_agents import AgentLike

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
Read this plan and draft acceptance criteria for the feature it describes.
Each criterion must be:
  - OBSERVABLE: a tester can determine pass/fail by reading test output
  - CONCRETE: names specific inputs, behaviors, and outputs (no "etc.")
  - INDEPENDENT: does not depend on internal implementation choices

Output strict JSON: {"acceptance_criteria": ["...", "..."]}
"""


@dataclass
class SpecACGenerator:
    """Drafts acceptance criteria from a plan, before any code is written."""

    agent: AgentLike

    async def draft(self, plan_text: str) -> list[str]:
        user_msg = f"## Plan\n{plan_text}\n"
        try:
            raw = await self.agent.run(_SYSTEM_PROMPT, user_msg)
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("SpecACGenerator JSON parse failure: %s", exc)
            return []
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("SpecACGenerator agent failure: %s", exc)
            return []

        return [str(ac) for ac in data.get("acceptance_criteria", [])]
