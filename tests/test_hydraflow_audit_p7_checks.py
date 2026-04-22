"""Tests for P7 (Observability + wiki) check functions."""

from __future__ import annotations

from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p7_observability  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- Sentry gatekeeper ---------------------------------------------------


def test_bug_types_detected_in_server_py(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "server.py",
        "import sentry_sdk\n\n_BUG_TYPES = (TypeError, KeyError)\n\nsentry_sdk.init(dsn='')\n",
    )
    assert _run("P7.1", _ctx(tmp_path)).status is Status.PASS


def test_bug_types_absent_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "server.py", "import sentry_sdk\nsentry_sdk.init(dsn='')\n"
    )
    assert _run("P7.1", _ctx(tmp_path)).status is Status.FAIL


def test_before_send_wired_to_filter(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "server.py",
        (
            "import sentry_sdk\n\n"
            "_BUG_TYPES = (TypeError,)\n\n"
            "def before_send(e, h): ...\n\n"
            "sentry_sdk.init(dsn='', before_send=before_send)\n"
        ),
    )
    assert _run("P7.2", _ctx(tmp_path)).status is Status.PASS


def test_before_send_missing_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "server.py",
        "import sentry_sdk\n_BUG_TYPES = (TypeError,)\nsentry_sdk.init(dsn='')\n",
    )
    assert _run("P7.2", _ctx(tmp_path)).status is Status.FAIL


# --- Repo wiki -----------------------------------------------------------


def test_repo_wiki_dir_exists(tmp_path: Path) -> None:
    (tmp_path / "repo_wiki").mkdir()
    assert _run("P7.3", _ctx(tmp_path)).status is Status.PASS


def test_repo_wiki_missing_fails(tmp_path: Path) -> None:
    assert _run("P7.3", _ctx(tmp_path)).status is Status.FAIL


def test_wiki_three_layers_pass(tmp_path: Path) -> None:
    wiki = tmp_path / "repo_wiki" / "slug"
    wiki.mkdir(parents=True)
    (wiki / "index.json").write_text("{}", encoding="utf-8")
    (wiki / "_log.jsonl").write_text("", encoding="utf-8")
    (wiki / "topic-a.md").write_text("# A", encoding="utf-8")
    assert _run("P7.3a", _ctx(tmp_path)).status is Status.PASS


def test_wiki_missing_layers_warn(tmp_path: Path) -> None:
    wiki = tmp_path / "repo_wiki" / "slug"
    wiki.mkdir(parents=True)
    (wiki / "topic-a.md").write_text("# A", encoding="utf-8")
    assert _run("P7.3a", _ctx(tmp_path)).status is Status.WARN


def test_wiki_store_ops_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "repo_wiki.py",
        "class RepoWikiStore:\n    def ingest(self): ...\n    def query(self): ...\n    def lint(self): ...\n",
    )
    assert _run("P7.3b", _ctx(tmp_path)).status is Status.PASS


def test_wiki_store_missing_op_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "repo_wiki.py",
        "class RepoWikiStore:\n    def ingest(self): ...\n",
    )
    result = _run("P7.3b", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "query" in result.message


def test_runner_injects_wiki_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "base_runner.py",
        "class BaseRunner:\n    def _inject_repo_wiki(self, prompt): return prompt\n",
    )
    assert _run("P7.3c", _ctx(tmp_path)).status is Status.PASS


def test_runner_injection_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "base_runner.py", "class BaseRunner: ...\n")
    assert _run("P7.3c", _ctx(tmp_path)).status is Status.FAIL


# --- Logging discipline --------------------------------------------------


def test_bare_except_pass_warns(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "bad.py",
        "def f():\n    try:\n        x = 1\n    except:\n        pass\n",
    )
    assert _run("P7.4", _ctx(tmp_path)).status is Status.WARN


def test_clean_try_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "good.py",
        "def f():\n    try:\n        x = 1\n    except ValueError:\n        x = 0\n",
    )
    assert _run("P7.4", _ctx(tmp_path)).status is Status.PASS


def test_bare_value_logger_error_warns(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "bad.py",
        "import logging\nlogger = logging.getLogger()\ndef f(e):\n    logger.error(e)\n",
    )
    assert _run("P7.5", _ctx(tmp_path)).status is Status.WARN


def test_format_string_logger_error_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "good.py",
        'import logging\nlogger = logging.getLogger()\ndef f(e):\n    logger.error("failed: %s", e)\n',
    )
    assert _run("P7.5", _ctx(tmp_path)).status is Status.PASS


# --- Self-instrumentation ------------------------------------------------


def test_audit_self_instrumentation_passes_with_filter(tmp_path: Path) -> None:
    _write(
        tmp_path / "scripts" / "hydraflow_audit" / "observability.py",
        "_BUG_TYPES = (TypeError,)\ndef _before_send(e, h): ...\n",
    )
    assert _run("P7.6", _ctx(tmp_path)).status is Status.PASS


def test_audit_self_instrumentation_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "hydraflow_audit" / "observability.py", "# stub\n")
    assert _run("P7.6", _ctx(tmp_path)).status is Status.FAIL


def test_observability_port_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "ports.py",
        "from typing import Protocol\n\nclass ObservabilityPort(Protocol):\n    def emit(self, event): ...\n",
    )
    assert _run("P7.7", _ctx(tmp_path)).status is Status.PASS


def test_observability_port_absent_warns(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "ports.py",
        "from typing import Protocol\n\nclass VCSPort(Protocol): ...\n",
    )
    assert _run("P7.7", _ctx(tmp_path)).status is Status.WARN
