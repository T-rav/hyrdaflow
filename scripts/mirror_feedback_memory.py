"""Mirror a single `feedback_*.md` memory into the in-repo backlog.

Usage:
    uv run python scripts/mirror_feedback_memory.py <path-to-feedback-memory>

Reads `<path>` (a `feedback_*.md` file from Claude's session-memory directory),
applies redaction, and writes the corresponding mirror under
`<git-root>/docs/wiki/memory-feedback/<slug>.md`.

Used by the `.claude/hooks/hf.mirror-feedback-memory.sh` PostToolUse hook to
auto-sync mirrors whenever Claude saves a feedback memory. See ADR-0057.

Exits 0 on success. On error, prints to stderr and exits non-zero — the hook
treats this as a warning (it does NOT block the originating Write).
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

_MIRROR_SUBPATH = ("docs", "wiki", "memory-feedback")
_ALLOWED_EMAIL_SUFFIXES: tuple[str, ...] = (
    "@anthropic.com",
    "@hydraflow.local",
    "@example.com",
)
_FRONT_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def redact(body: str) -> str:
    """Apply redaction rules to memory body text.

    - Replace any occurrence of `$HOME` (the absolute home path) with `~`.
    - Replace email addresses outside the allowlist with `<email>`.
    - Preserve everything else verbatim (rule + Why + How to apply prose).

    Resolves `Path.home()` lazily so changes to the `HOME` env var (e.g. in
    test fixtures) are honored.
    """
    body = body.replace(str(Path.home()), "~")

    def _sub(m: re.Match[str]) -> str:
        addr = m.group(0)
        return (
            addr
            if any(addr.endswith(suf) for suf in _ALLOWED_EMAIL_SUFFIXES)
            else "<email>"
        )

    return _EMAIL_RE.sub(_sub, body)


def _parse_frontmatter_lenient(block: str) -> dict[str, object]:
    """Parse simple `key: value` frontmatter without strict YAML rules.

    Source memory files sometimes have values that begin with backticks or
    other characters YAML rejects. We only need a flat mapping of top-level
    scalar fields (`name`, `description`, `type`, `originSessionId`), so a
    line-based parse is both sufficient and more tolerant.
    """
    out: dict[str, object] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = _FRONT_KEY_RE.match(line)
        if not m:
            try:
                loaded = yaml.safe_load(block) or {}
                if isinstance(loaded, dict):
                    return {str(k): v for k, v in loaded.items()}
            except yaml.YAMLError:
                pass
            return out
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def parse_source(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front = _parse_frontmatter_lenient(text[4:end])
    body = text[end + 4 :].lstrip("\n")
    return front, body


def slug_from_filename(name: str) -> str:
    """`feedback_subagent_batch_size.md` → `feedback-subagent-batch-size`."""
    base = name.removesuffix(".md")
    return base.replace("_", "-")


def render_mirror(memory_path: Path) -> str:
    """Build the mirror file content for `memory_path`. Pure function."""
    front, body = parse_source(memory_path)
    front.pop("originSessionId", None)
    slug = slug_from_filename(memory_path.name)
    new_front: dict[str, object] = {
        "source": memory_path.name,
        "name": front.get("name", slug),
        "description": front.get("description", ""),
        "status": "pending",
        "issue": None,
        "promoted_in": None,
        "wontfix_reason": None,
        "created": datetime.fromtimestamp(memory_path.stat().st_mtime)
        .date()
        .isoformat(),
    }
    front_yaml = yaml.safe_dump(
        new_front,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    ).rstrip()
    return f"---\n{front_yaml}\n---\n\n{redact(body).rstrip()}\n"


def mirror_one(memory_path: Path, repo_root: Path) -> Path:
    """Write the redacted mirror for `memory_path` under `repo_root`. Returns target path.

    Idempotent: overwrites any existing mirror with the same slug.
    """
    target_dir = repo_root.joinpath(*_MIRROR_SUBPATH)
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = slug_from_filename(memory_path.name)
    target = target_dir / f"{slug}.md"
    target.write_text(render_mirror(memory_path))
    return target


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` looking for `.git/`. Returns repo root or None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out.stdout.strip())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: mirror_feedback_memory.py <memory-file-path>", file=sys.stderr)
        return 2
    memory_path = Path(argv[1]).expanduser().resolve()
    if not memory_path.exists():
        print(f"memory file does not exist: {memory_path}", file=sys.stderr)
        return 1
    if not memory_path.name.startswith("feedback_") or not memory_path.name.endswith(
        ".md"
    ):
        # Not a feedback memory — silently skip (hook fires on every Write).
        return 0
    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        print(
            "not in a git repo; skipping mirror (cwd has no toplevel)",
            file=sys.stderr,
        )
        return 0
    target = mirror_one(memory_path, repo_root)
    print(
        f"mirrored {memory_path.name} → {target.relative_to(repo_root)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
