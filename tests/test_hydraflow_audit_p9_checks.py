"""Tests for P9 (persistence + data layout) check functions."""

from __future__ import annotations

from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p9_persistence  # noqa: F401
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


# --- data_root field + override ------------------------------------------


def test_data_root_field_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "config.py",
        "from pathlib import Path\nfrom pydantic import Field\n\nclass C:\n    data_root: Path = Field(default=Path('.data'))\n",
    )
    assert _run("P9.1", _ctx(tmp_path)).status is Status.PASS


def test_data_root_field_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "config.py", "class C: pass\n")
    assert _run("P9.1", _ctx(tmp_path)).status is Status.FAIL


def test_env_override_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "config.py",
        "import os\npath = os.environ.get('PROJ_DATA_ROOT', '.data')\n",
    )
    assert _run("P9.2", _ctx(tmp_path)).status is Status.PASS


def test_env_override_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "config.py", "path = '.data'\n")
    assert _run("P9.2", _ctx(tmp_path)).status is Status.FAIL


def test_repo_slug_scoping_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "paths.py",
        "def root(data_root, repo_slug):\n    return data_root / repo_slug\n",
    )
    assert _run("P9.3", _ctx(tmp_path)).status is Status.PASS


def test_repo_slug_scoping_missing_warns(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "paths.py",
        "def root(data_root):\n    return data_root / 'x'\n",
    )
    assert _run("P9.3", _ctx(tmp_path)).status is Status.WARN


# --- State abstractions --------------------------------------------------


def test_state_tracker_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "state.py",
        "class StateTracker:\n    def write(self, data): ...\n",
    )
    assert _run("P9.4", _ctx(tmp_path)).status is Status.PASS


def test_state_tracker_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P9.4", _ctx(tmp_path)).status is Status.FAIL


def test_dedup_store_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "dedup_store.py",
        "class DedupStore:\n    def has(self, key): ...\n",
    )
    assert _run("P9.5", _ctx(tmp_path)).status is Status.PASS


def test_dedup_store_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P9.5", _ctx(tmp_path)).status is Status.FAIL


# --- Atomic writes -------------------------------------------------------


def test_os_replace_counts_as_atomic(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "w.py",
        "import os\ndef write():\n    os.replace('tmp', 'final')\n",
    )
    assert _run("P9.6", _ctx(tmp_path)).status is Status.PASS


def test_non_atomic_writes_fail(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "w.py", "def write():\n    open('x', 'w').write('x')\n")
    assert _run("P9.6", _ctx(tmp_path)).status is Status.FAIL


# --- Gitignore + write paths --------------------------------------------


def test_gitignore_contains_data_root(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", ".hydraflow/\n")
    assert _run("P9.7", _ctx(tmp_path)).status is Status.PASS


def test_gitignore_missing_data_root_warns(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "*.pyc\n")
    assert _run("P9.7", _ctx(tmp_path)).status is Status.WARN


def test_opens_outside_data_root_warn(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "bad.py",
        "def f():\n    with open('output.txt', 'w') as fh:\n        fh.write('x')\n",
    )
    assert _run("P9.8", _ctx(tmp_path)).status is Status.WARN


def test_opens_inside_data_root_pass(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "good.py",
        "def f(data_root):\n    with open(data_root / 'x', 'w') as fh:\n        fh.write('x')\n",
    )
    assert _run("P9.8", _ctx(tmp_path)).status is Status.PASS
