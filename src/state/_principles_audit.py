"""PrinciplesAuditLoop state: onboarding status, last-green audit, drift attempts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")

_OnboardingStatus = Literal["pending", "blocked", "ready"]


class PrinciplesAuditStateMixin:
    """Getters/setters for PrinciplesAuditLoop state (spec §4.4)."""

    _data: StateData

    def save(self) -> None: ...  # provided by core StateTracker

    # --- onboarding status ---

    def get_onboarding_status(self, slug: str) -> _OnboardingStatus | None:
        return self._data.managed_repos_onboarding_status.get(slug)

    def set_onboarding_status(self, slug: str, status: _OnboardingStatus) -> None:
        self._data.managed_repos_onboarding_status[slug] = status
        self.save()

    def blocked_slugs(self) -> set[str]:
        return {
            slug
            for slug, status in self._data.managed_repos_onboarding_status.items()
            if status == "blocked"
        }

    # --- last-green audit snapshot ---

    def get_last_green_audit(self, slug: str) -> dict[str, str]:
        return dict(self._data.last_green_audit.get(slug, {}))

    def set_last_green_audit(self, slug: str, snapshot: dict[str, str]) -> None:
        self._data.last_green_audit[slug] = dict(snapshot)
        self.save()

    # --- drift attempts ---

    @staticmethod
    def _attempt_key(slug: str, check_id: str) -> str:
        return f"{slug}:{check_id}"

    def get_drift_attempts(self, slug: str, check_id: str) -> int:
        return self._data.principles_drift_attempts.get(
            self._attempt_key(slug, check_id), 0
        )

    def increment_drift_attempts(self, slug: str, check_id: str) -> int:
        key = self._attempt_key(slug, check_id)
        n = self._data.principles_drift_attempts.get(key, 0) + 1
        self._data.principles_drift_attempts[key] = n
        self.save()
        return n

    def reset_drift_attempts(self, slug: str, check_id: str) -> None:
        self._data.principles_drift_attempts.pop(
            self._attempt_key(slug, check_id), None
        )
        self.save()
