"""Synthetic fixture — Port substitution by positional arg, no spec=.

Detector should flag both call sites.
"""

from unittest.mock import AsyncMock, MagicMock

from src.ports import IssueStorePort, PRPort


def make_pr() -> PRPort:
    return AsyncMock(PRPort)  # FAIL — positional Port without spec=


def make_store() -> IssueStorePort:
    return MagicMock(IssueStorePort)  # FAIL — positional Port without spec=
