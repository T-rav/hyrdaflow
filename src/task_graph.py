"""Task Graph parsing and extraction — structured phases from plan documents."""

from __future__ import annotations

import re

from pydantic import BaseModel


class TaskGraphPhase(BaseModel):
    """A single phase in a Task Graph plan."""

    id: str  # "P1"
    name: str  # "P1 — Data Model"
    files: list[str]
    tests: list[str]  # behavioral specs
    depends_on: list[str]


# Regex for task graph phase headers: ### P1 — Name or ### P1 - Name
_TASK_GRAPH_PHASE_RE = re.compile(r"^###\s+P(\d+)\s*[\u2014\-]+\s*(.+)$", re.MULTILINE)


def has_task_graph(text: str) -> bool:
    """Return True if *text* contains a Task Graph section header."""
    return bool(re.search(r"## Task Graph\b", text, re.IGNORECASE))


def extract_phases(body: str) -> list[TaskGraphPhase]:
    """Extract structured phases from a Task Graph section body.

    Returns a list of :class:`TaskGraphPhase` instances.
    """
    headers = list(_TASK_GRAPH_PHASE_RE.finditer(body))
    if not headers:
        return []

    phases: list[TaskGraphPhase] = []
    for i, match in enumerate(headers):
        phase_num = match.group(1)
        phase_name = match.group(2).strip()
        # Extract body between this header and the next (or end)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        section = body[start:end]

        # Extract **Files:** content
        files_match = re.search(
            r"\*\*Files:\*\*\s*(.+?)(?=\n\*\*|\Z)", section, re.DOTALL
        )
        files: list[str] = []
        if files_match:
            files = re.findall(
                r"[\w\-]+(?:/[\w\-]+)+\.?[\w]*|[\w\-]+\.[\w]+",
                files_match.group(1),
            )

        # Extract **Tests:** content (behavioral specs)
        tests_match = re.search(
            r"\*\*Tests:\*\*\s*(.+?)(?=\n\*\*|\Z)", section, re.DOTALL
        )
        tests: list[str] = []
        if tests_match:
            # Extract bullet-point items
            test_items = re.findall(
                r"^\s*[-*]\s+(.+)$", tests_match.group(1), re.MULTILINE
            )
            tests = [t.strip() for t in test_items if t.strip()]

        # Extract **Depends on:** content
        depends_match = re.search(
            r"\*\*Depends on:\*\*\s*(.+?)(?=\n\*\*|\n###|\Z)", section, re.DOTALL
        )
        depends_on: list[str] = []
        if depends_match:
            dep_text = depends_match.group(1).strip().lower()
            if dep_text not in ("none", "(none)", "-", "n/a", ""):
                depends_on = re.findall(r"P(\d+)", depends_match.group(1))
                depends_on = [f"P{d}" for d in depends_on]

        phases.append(
            TaskGraphPhase(
                id=f"P{phase_num}",
                name=f"P{phase_num} — {phase_name}",
                files=files,
                tests=tests,
                depends_on=depends_on,
            )
        )

    return phases


def extract_impl_step_texts(body: str) -> list[str]:
    """Extract step text from an Implementation Steps section body."""
    list_steps = re.findall(
        r"^\s*(?:\d+[\.\)]|[-*+]|\[[ xX]\])\s+(.+)$",
        body,
        re.MULTILINE,
    )
    heading_steps = re.findall(
        r"^\s*#{2,6}\s*(?:Step\s*\d+[:\.\-]?\s+(.+)|\d+[\.\)]\s+(.+))$",
        body,
        re.MULTILINE | re.IGNORECASE,
    )
    impl_step_texts = [s.strip() for s in list_steps]
    impl_step_texts.extend((s1 or s2).strip() for s1, s2 in heading_steps)
    return [s for s in impl_step_texts if s]
