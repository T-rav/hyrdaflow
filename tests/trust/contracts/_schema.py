"""Back-compat shim — cassette schema moved to ``src/contracts/_schema.py``.

Production code (``src/contract_diff.py``, ``src/contract_refresh_loop.py``)
must not require ``tests/`` to be on ``sys.path``: the deployed container
ships ``src/`` only. The schema was therefore relocated to
``src/contracts/_schema.py`` (mirrors PR A's ``_factories`` move).

Existing test-side call sites continue to work via this re-export.
"""

from __future__ import annotations

from contracts._schema import (  # noqa: F401
    NORMALIZERS,
    Cassette,
    CassetteInput,
    CassetteOutput,
    apply_normalizers,
    dump_cassette,
    load_cassette,
)
