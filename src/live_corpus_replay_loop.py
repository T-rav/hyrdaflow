"""LiveCorpusReplayLoop — read shadow corpus, diff vs fakes (Phase 2 of #8786).

Closes the value-level drift detection half of the v2 trust pattern. Each
tick:

1. Enumerate fresh samples from ``ShadowCorpus``.
2. For each sample with a registered dispatcher, invoke the matching
   fake-adapter method with the sampled input.
3. Diff the fake's normalized output against the sample's normalized
   stored output.
4. On drift, file a single ``hydraflow-find`` + ``shadow-drift`` issue
   per loop tick (dedup'd on drift signature) so the existing IMPL
   pipeline picks it up — no human escalation surface.

Samples whose ``(adapter, command, args)`` shape has no registered
dispatcher are silently skipped this tick. The dispatcher registry is
populated by follow-up PRs as call shapes are wired through Pydantic
``contracts.shapes`` models — Phase 2 ships the loop + an empty
registry + one demonstration dispatcher (``gh pr view``) to prove the
contract.

The 3-attempt escalation chain + auto-agent dispatch live in Phase 3.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001
from state import StateTracker  # noqa: TCH001

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from contracts.shadow import ShadowCorpus, ShadowSample
    from dedup_store import DedupStore
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.live_corpus_replay_loop")


# A dispatcher takes one ShadowSample and returns the fake adapter's
# "equivalent output" as a dict — the same shape the recorder captured.
# Returns None if the fake has no opinion on this sample (loop logs +
# skips). Raises on internal errors — the loop catches and reports them
# as drift attribute "dispatcher_error" so they surface, not silenced.
Dispatcher = Callable[["ShadowSample"], Awaitable[dict[str, Any] | None]]

# Registry keyed on (adapter, command). Subkey on a frozenset of arg
# prefix tokens lets multiple ``gh pr view`` shapes share one dispatcher
# (the dispatcher itself can branch on ``sample.args``).
DispatcherKey = tuple[str, str]


class LiveCorpusReplayLoop(BaseBackgroundLoop):
    """Periodically diff shadow corpus samples vs fake-adapter outputs."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        corpus: ShadowCorpus,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        state: StateTracker | None = None,
        dispatchers: dict[DispatcherKey, Dispatcher] | None = None,
    ) -> None:
        super().__init__(
            worker_name="live_corpus_replay",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._corpus = corpus
        self._pr = pr_manager
        self._dedup = dedup
        self._state = state
        self._dispatchers: dict[DispatcherKey, Dispatcher] = dict(dispatchers or {})

    def _get_default_interval(self) -> int:
        return self._config.live_corpus_replay_interval

    def register(self, adapter: str, command: str, fn: Dispatcher) -> None:
        """Register a dispatcher for ``(adapter, command)``.

        The dispatcher receives the full ShadowSample so it can branch on
        ``args`` (e.g. ``gh pr view`` covers many ``--json`` field sets).
        """
        self._dispatchers[(adapter, command)] = fn

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        samples = self._corpus.list()
        compared = 0
        skipped_no_dispatcher = 0
        drifted: list[tuple[Path, str]] = []  # (path, signature)
        errors = 0

        for path in samples:
            try:
                sample = self._corpus.load(path)
            except (OSError, ValueError) as exc:
                logger.warning("could not load shadow sample %s: %s", path, exc)
                errors += 1
                continue

            dispatcher = self._dispatchers.get((sample.adapter, sample.command))
            if dispatcher is None:
                skipped_no_dispatcher += 1
                continue

            try:
                fake_output = await dispatcher(sample)
            except Exception:  # noqa: BLE001 — replay must continue on dispatcher error
                logger.exception(
                    "dispatcher raised for %s/%s args=%s",
                    sample.adapter,
                    sample.command,
                    sample.args,
                )
                errors += 1
                continue

            compared += 1
            if fake_output is None:
                continue

            signature = _drift_signature(sample, fake_output)
            if signature is not None:
                drifted.append((path, signature))

        filed_issue: int | None = None
        escalated_issue: int | None = None
        escalated_signatures: list[str] = []

        if drifted:
            # Increment per-signature attempt counters and identify any
            # that have hit the escalation threshold.
            if self._state is not None:
                threshold = self._config.live_corpus_max_drift_attempts
                for _path, sig in drifted:
                    attempts = self._state.inc_live_corpus_drift_attempts(sig)
                    if attempts >= threshold and sig not in escalated_signatures:
                        escalated_signatures.append(sig)

            dedup_key = _fleet_dedup_key(drifted)
            seen = self._dedup.get()
            if dedup_key not in seen:
                filed_issue = await self._file_drift_issue(drifted)
                seen.add(dedup_key)
                self._dedup.set_all(seen)

            # If any signature reached the threshold, file an escalation
            # issue routed to the auto-agent preflight loop via the
            # ``hitl-escalation`` label.
            if escalated_signatures:
                escalated_issue = await self._file_escalation_issue(
                    escalated_signatures
                )
        # Clean tick: clear all attempt counters so a future
        # re-occurrence of the same drift starts fresh.
        elif self._state is not None:
            self._state.clear_live_corpus_drift_attempts()

        return {
            "status": "ok",
            "compared": compared,
            "skipped_no_dispatcher": skipped_no_dispatcher,
            "drifted": len(drifted),
            "errors": errors,
            "filed_issue": filed_issue,
            "escalated_issue": escalated_issue,
            "escalated_signatures": len(escalated_signatures),
        }

    async def _file_escalation_issue(self, signatures: list[str]) -> int:
        """File a ``hitl-escalation`` issue when drift signatures exhaust
        the loop's own retry budget.

        Routed via the existing ``hitl-escalation`` label to the
        ``AutoAgentPreflightLoop`` — that loop runs its OWN 3-attempt
        cycle (auto-agent IMPL pipeline) before labeling
        ``human-required``. The combined autonomous-attempt budget is
        ``live_corpus_max_drift_attempts × auto_agent_max_attempts``.
        """
        labels = ["hitl-escalation", "shadow-drift-stuck"]
        title = (
            f"Shadow drift stuck: {len(signatures)} signature(s) survived "
            f"{self._config.live_corpus_max_drift_attempts} tick(s) without repair"
        )
        sig_lines = "\n".join(f"- `{s[:12]}`" for s in signatures[:50])
        body = (
            f"## Drift survived the LiveCorpusReplayLoop retry budget\n\n"
            f"After {self._config.live_corpus_max_drift_attempts} consecutive "
            f"ticks of detecting the same drift signature(s) without the "
            f"earlier `hydraflow-find` repair PR landing, the loop escalates "
            f"to `hitl-escalation` so `AutoAgentPreflightLoop` runs its own "
            f"attempts.\n\n"
            f"### Stuck signatures\n\n{sig_lines}\n\n"
            f"### Repair path\n\n"
            f"The auto-agent preflight loop will pick this up and run "
            f"`auto_agent_max_attempts` IMPL attempts before adding "
            f"`human-required`. Closing this issue clears all per-signature "
            f"counters on the next clean tick."
        )
        return await self._pr.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

    async def _file_drift_issue(self, drifted: list[tuple[Path, str]]) -> int:
        """File a single hydraflow-find issue covering all drift this tick."""
        labels = ["hydraflow-find", "shadow-drift"]
        title = (
            f"Shadow drift: {len(drifted)} fake-adapter output(s) diverged "
            f"from live samples"
        )
        body_lines = [
            "## Shadow corpus drift",
            "",
            "`LiveCorpusReplayLoop` compared live-recorded subprocess outputs "
            "against fake-adapter outputs and detected divergence.",
            "",
            "### Drifted samples",
            "",
        ]
        for path, sig in drifted[:50]:  # cap body length
            body_lines.append(f"- `{path.name}` — signature `{sig[:12]}`")
        body_lines.extend(
            [
                "",
                "**Repair path.** The auto-agent should pick this up via the "
                "`hydraflow-find` label, regenerate the affected fake method to "
                "match the live sample, and open a PR. See #8786 (Phase 3) for "
                "the full auto-repair chain.",
            ]
        )
        return await self._pr.create_issue(
            title=title,
            body="\n".join(body_lines),
            labels=labels,
        )


def _canonicalize(value: Any) -> Any:
    """Stable JSON-canonical form. Sort dict keys; preserve list order."""
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def _drift_signature(sample: ShadowSample, fake_output: dict[str, Any]) -> str | None:
    """Return a stable signature when sample and fake diverge, else None.

    Compares the parsed stdout (if JSON) against ``fake_output``. For
    non-JSON stdout, falls back to a literal string compare.
    """
    try:
        sample_value: Any = json.loads(sample.stdout) if sample.stdout else None
    except (TypeError, ValueError):
        sample_value = sample.stdout
    if _canonicalize(sample_value) == _canonicalize(fake_output):
        return None
    blob = json.dumps(
        {
            "adapter": sample.adapter,
            "command": sample.command,
            "args": sample.args,
            "sample": _canonicalize(sample_value),
            "fake": _canonicalize(fake_output),
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _fleet_dedup_key(drifted: list[tuple[Path, str]]) -> str:
    """Stable dedup key across all drifts in this tick."""
    payload = {"signatures": sorted(sig for _path, sig in drifted)}
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
