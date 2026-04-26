"""Strict Port↔Fake signature conformance (spec §3.3).

Existing test test_port_conformance.py uses isinstance() against the
runtime-checkable Protocol — passes when method names match, but
Python's structural subtyping does NOT compare signatures. C2/C3 from
PR #8439 (``remove_labels`` plural typo, nonexistent
``list_issue_comments``) slipped through.

This test fills the Port↔Fake gap: for every (Port, Fake) pair, every
public Port method must have a Fake method with the same name AND the
same kwarg signature. tests/test_ports.py already covers Port↔Adapter
signature parity for IssueStorePort↔IssueStore (the real adapter).

Compatibility rule for ``**kwargs`` / ``*args`` absorb patterns
---------------------------------------------------------------
Fakes legitimately use ``**_kw`` or ``*_args`` to absorb extra kwargs
that phases pass but the Fake doesn't need to track.  A Fake with a
``**kwargs`` catch-all is considered compatible with any Port method
whose unmatched named params are all covered by that catch-all.
Similarly a ``*args`` catch-all absorbs unmatched positional params.
This allows intentional test-convenience patterns without false failures.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_workspace import FakeWorkspace
from tests.scenarios.ports import PRPort, WorkspacePort

# Hand-maintained Port↔Fake pair list. Add new pairs as Fakes are
# introduced. (Auto-discovery via convention ``Fake<PortStem>`` is YAGNI
# at this scale; ~3 pairs total.)
_PORT_FAKE_PAIRS: list[tuple[type, type]] = [
    (PRPort, FakeGitHub),
    (WorkspacePort, FakeWorkspace),
    # IssueStorePort: no Fake; covered separately by tests/test_ports.py
    # against the real IssueStore adapter.
]


def _public_methods(cls: type) -> dict[str, Any]:
    """Return public methods of cls (skip dunders + private prefix)."""
    out = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name)
        if not callable(attr):
            continue
        out[name] = attr
    return out


def _named_params(sig: inspect.Signature) -> dict[str, inspect.Parameter]:
    """Return named parameters (exclude self, *args, **kwargs catch-alls)."""
    return {
        p: info
        for p, info in sig.parameters.items()
        if p != "self"
        and info.kind
        not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    }


def _has_var_keyword(sig: inspect.Signature) -> bool:
    """True if the signature has a **kwargs catch-all."""
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


def _has_var_positional(sig: inspect.Signature) -> bool:
    """True if the signature has a *args catch-all."""
    return any(
        p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()
    )


def _signatures_compatible(
    port_sig: inspect.Signature, fake_sig: inspect.Signature
) -> tuple[bool, str]:
    """Check whether fake_sig is a drop-in-compatible implementation of port_sig.

    Compatibility rules (in priority order):

    1.  Named params that appear on both Port and Fake must agree on
        required-vs-optional status (default-vs-no-default).  Type
        annotations are not compared — Python's runtime accepts
        duck-typed kwargs, and exact type matching would over-constrain
        Fakes.

    2.  Port params absent from Fake's named params are acceptable if the
        Fake has a ``**kwargs`` catch-all (VAR_KEYWORD) — the catch-all
        absorbs them.  Similarly a ``*args`` catch-all (VAR_POSITIONAL)
        absorbs unmatched positional params.

    3.  Fake params absent from Port's named params are allowed (the Fake
        may accept extra test-seeding kwargs not on the Port).

    Returns ``(ok: bool, reason: str)``.  ``reason`` is empty when ok.
    """
    port_params = _named_params(port_sig)
    fake_params = _named_params(fake_sig)
    fake_has_vk = _has_var_keyword(fake_sig)
    fake_has_vp = _has_var_positional(fake_sig)

    # Port params not covered by Fake's named params.
    uncovered = set(port_params.keys()) - set(fake_params.keys())
    if uncovered:
        if fake_has_vk or fake_has_vp:
            # Absorbed by *args/**kwargs catch-all — intentional Fake pattern.
            pass
        else:
            return False, (
                f"Port params not present in Fake and no catch-all to absorb them: "
                f"{sorted(uncovered)}"
            )

    # For params that exist on both: check required-vs-optional status.
    for name in set(port_params.keys()) & set(fake_params.keys()):
        port_pinfo = port_params[name]
        fake_pinfo = fake_params[name]
        port_required = port_pinfo.default is inspect.Parameter.empty
        fake_required = fake_pinfo.default is inspect.Parameter.empty
        if port_required != fake_required:
            return False, (
                f"Param '{name}': Port required={port_required} but "
                f"Fake required={fake_required}.  They must agree on "
                f"required-vs-optional status."
            )

    return True, ""


@pytest.mark.parametrize(
    "port_cls,fake_cls",
    _PORT_FAKE_PAIRS,
    ids=[f"{p.__name__}-{f.__name__}" for p, f in _PORT_FAKE_PAIRS],
)
def test_fake_signatures_match_port(port_cls: type, fake_cls: type) -> None:
    """For every public method on the Port, the Fake must have a method
    with the same name AND a compatible kwarg signature.

    ``**kwargs`` / ``*args`` catch-alls on the Fake are accepted as
    intentional absorb patterns (see module docstring for the full rule).
    """
    port_methods = _public_methods(port_cls)
    fake_methods = _public_methods(fake_cls)

    missing = port_methods.keys() - fake_methods.keys()
    assert not missing, (
        f"{fake_cls.__name__} is missing methods declared on {port_cls.__name__}: "
        f"{sorted(missing)}\n\n"
        f"This catches the C2/C3 class of break from PR #8439 — Fake drift "
        f"hidden by AsyncMock auto-attribute behavior."
    )

    failures: list[str] = []
    for name in sorted(port_methods):
        try:
            port_sig = inspect.signature(port_methods[name])
            fake_sig = inspect.signature(fake_methods[name])
        except (ValueError, TypeError) as exc:
            # inspect.signature can fail on some builtins; skip gracefully.
            failures.append(f"  {name}: could not inspect signature — {exc}")
            continue

        ok, reason = _signatures_compatible(port_sig, fake_sig)
        if not ok:
            failures.append(
                f"  {name}:\n"
                f"    Port: {port_sig}\n"
                f"    Fake: {fake_sig}\n"
                f"    Reason: {reason}"
            )

    assert not failures, (
        f"Signature mismatches on {fake_cls.__name__} vs {port_cls.__name__}:\n"
        + "\n".join(failures)
        + "\n\nEither rename the Fake method/param to match the Port, "
        "or use a **kwargs catch-all for intentional absorb patterns."
    )
