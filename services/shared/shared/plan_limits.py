"""Plan-level limits for Vex pricing tiers.

These constants define the quotas, rate limits, and feature flags
for each plan. The ``PLAN_LIMITS`` dict is keyed by the ``plan``
column value in the ``organizations`` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PlanConfig:
    """Immutable configuration for a single pricing plan."""

    # Monthly quotas
    observations_per_month: int
    verifications_per_month: int

    # Rate limit (overrides per-key RPM if lower)
    max_rpm: int

    # Resource limits
    max_agents: int
    max_seats: int

    # Feature flags
    corrections_enabled: bool
    webhook_alerts: bool
    slack_alerts: bool

    # Data retention (days)
    retention_days: int

    # Overage: if True, requests beyond quota are allowed (billed).
    # If False, requests beyond quota are rejected (429).
    overage_allowed: bool


PLAN_LIMITS: Dict[str, PlanConfig] = {
    "free": PlanConfig(
        observations_per_month=10_000,
        verifications_per_month=500,
        max_rpm=100,
        max_agents=3,
        max_seats=1,
        corrections_enabled=False,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=7,
        overage_allowed=False,
    ),
    "pro": PlanConfig(
        observations_per_month=100_000,
        verifications_per_month=10_000,
        max_rpm=1_000,
        max_agents=15,
        max_seats=5,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=False,
        retention_days=30,
        overage_allowed=True,
    ),
    "team": PlanConfig(
        observations_per_month=1_000_000,
        verifications_per_month=100_000,
        max_rpm=5_000,
        max_agents=-1,  # unlimited
        max_seats=15,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=90,
        overage_allowed=True,
    ),
}


def get_plan_config(plan: str) -> PlanConfig:
    """Return the PlanConfig for the given plan name.

    Falls back to ``"free"`` for unknown plan values.
    """
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
