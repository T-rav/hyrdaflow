"""Opt-in gating for eval tests.

Collection still happens by default (so the suite counts + lints
normally), but every test in ``tests/evals/`` is skipped unless
``--run-evals`` is passed or ``HYDRAFLOW_RUN_EVALS=1`` is set.

Rationale: evals call real LLMs, need creds, and are expensive. They
exist to answer "which model tier is right for this task" — operators
run them on-demand, not on every PR.
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-evals",
        action="store_true",
        default=False,
        help="Run LLM-backed eval tests in tests/evals/ (otherwise skipped).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption("--run-evals"):
        return
    if os.environ.get("HYDRAFLOW_RUN_EVALS", "").strip() in {"1", "true", "yes"}:
        return
    skip_marker = pytest.mark.skip(
        reason="eval tests skipped by default — pass --run-evals or set HYDRAFLOW_RUN_EVALS=1"
    )
    for item in items:
        if "tests/evals/" in str(item.fspath):
            item.add_marker(skip_marker)
