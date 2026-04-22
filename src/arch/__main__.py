"""Entry point for arch.subprocess_entry."""

from __future__ import annotations

import sys

from arch.subprocess_entry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
