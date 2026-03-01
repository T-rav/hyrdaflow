"""Embed HydraFlow assets into a Python module for distribution."""

from __future__ import annotations

import argparse
import base64
import tempfile
from pathlib import Path
from textwrap import wrap

from scripts.bundle_assets import bundle_assets


def _generate_module(output: Path, root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "assets.tar.gz"
        bundle_assets(archive_path, root)
        encoded = base64.b64encode(archive_path.read_bytes()).decode("ascii")

    wrapped = "\n".join(wrap(encoded, width=76))
    content = (
        '"""Embedded HydraFlow assets archive (base64-encoded tar.gz)."""\n\n'
        "from __future__ import annotations\n\n"
        'ASSET_ARCHIVE_B64 = """\n'
        f"{wrapped}\n"
        '"""\n'
    )
    output.write_text(content)
    print(f"Embedded assets → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed .claude/.codex/.githooks assets into a Python module."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/hf_cli/embedded_assets.py"),
        help="Path to write the embedded module",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing asset directories",
    )
    args = parser.parse_args()
    _generate_module(args.output, args.root)


if __name__ == "__main__":
    main()
