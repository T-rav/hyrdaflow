"""Core types for the audit pipeline.

Kept deliberately small: `CheckSpec` is the declarative row parsed from the
ADR; `Finding` is the result of running one check; `CheckContext` is the
execution environment handed to each check function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    BEHAVIORAL = "BEHAVIORAL"
    CULTURAL = "CULTURAL"


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NA = "NA"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass(frozen=True)
class CheckSpec:
    """A single row from an ADR-0044 check table."""

    check_id: str
    severity: Severity
    source: str
    what: str
    remediation: str
    principle: str  # e.g. "P1"


@dataclass
class Finding:
    """The result of running one check."""

    check_id: str
    status: Status
    severity: Severity
    principle: str
    source: str
    what: str
    remediation: str
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "severity": self.severity.value,
            "principle": self.principle,
            "source": self.source,
            "what": self.what,
            "remediation": self.remediation,
            "message": self.message,
        }


@dataclass
class CheckContext:
    """Execution context passed to every check function.

    Checks read from `root` (the target repo). They do not mutate anything.
    """

    root: Path
    is_orchestration_repo: bool = False
    has_ui: bool = False
    extras: dict = field(default_factory=dict)
