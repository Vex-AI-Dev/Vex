"""Plan-level limits for Vex pricing tiers.

These constants define the quotas, rate limits, and feature flags
for each plan. The ``PLAN_LIMITS`` dict is keyed by the ``plan``
column value in the ``organizations`` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanConfig:
    """Immutable configuration for a single pricing plan."""

    # Monthly quotas
    # ──────────────
    # Observations: async fire-and-forget events sent via POST /v1/ingest
    # or the SDK's async mode. These are telemetry records of agent executions
    # (input, output, latency, steps) stored for dashboards and analytics.
    # No LLM scoring is performed — just data collection.
    observations_per_month: int

    # Verifications: synchronous POST /v1/verify calls where the output is
    # scored in real-time by the verification engine (schema validation,
    # hallucination detection, drift scoring, coherence checking). Each call
    # invokes 2-4 LLM checks and returns a confidence score + pass/flag/block
    # action. Significantly more expensive than observations due to LLM costs.
    verifications_per_month: int

    # Corrections: monthly quota for auto-correction cascade invocations.
    # When a verification fails and correction=cascade is requested, this
    # counter is decremented. -1 means unlimited (full cascade available).
    # 0 means corrections are not available on this plan.
    corrections_per_month: int  # -1 = unlimited (full cascade)

    # Rate limit
    # ──────────
    # Maximum requests per minute across all endpoints for this org.
    # Applied as a sliding 60-second window. If a per-key RPM is also set,
    # the effective limit is min(per_key_rpm, plan_max_rpm).
    # Exceeding this returns HTTP 429 with a Retry-After header.
    max_rpm: int

    # Resource limits
    # ───────────────
    # Max agents: the number of distinct agent_id values this org can use.
    # Each unique agent_id seen in ingest/verify requests counts toward this
    # limit. -1 means unlimited. Exceeding this returns HTTP 403.
    max_agents: int

    # Feature flags
    # ─────────────
    # Corrections: when enabled, the verification engine can auto-correct
    # failing outputs using a 3-layer cascade (L1 Repair → L2 Constrained
    # Regen → L3 Full Reprompt). Each layer uses progressively stronger LLM
    # models. When disabled, correction=cascade requests are silently skipped
    # and the response includes correction_skipped=true with
    # correction_skipped_reason="upgrade_required".
    corrections_enabled: bool

    # Webhook alerts: when enabled, the alert service can deliver
    # notifications to user-configured HTTP webhook endpoints for events
    # like block actions, confidence drops, or anomaly detection.
    webhook_alerts: bool

    # Slack alerts: when enabled, the alert service can post notifications
    # directly to Slack channels via incoming webhooks for real-time
    # team visibility into agent health issues.
    slack_alerts: bool

    # Data retention
    # ──────────────
    # Number of days execution records, check results, and correction
    # attempts are retained in the database before automatic deletion.
    # After this period, data is permanently purged. Longer retention
    # enables deeper historical analysis and trend tracking.
    retention_days: int

    # Overage handling
    # ────────────────
    # When True: requests beyond the monthly quota are allowed to proceed
    # and the excess usage is billed at the per-unit overage rate.
    # When False: requests beyond the monthly quota are hard-rejected with
    # HTTP 429 and a message to upgrade. No overage charges are incurred.
    overage_allowed: bool


PLAN_LIMITS: dict[str, PlanConfig] = {
    "free": PlanConfig(
        observations_per_month=1_000,
        verifications_per_month=50,
        corrections_per_month=0,
        max_rpm=100,
        max_agents=-1,
        corrections_enabled=False,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=1,
        overage_allowed=False,
    ),
    "starter": PlanConfig(
        observations_per_month=25_000,
        verifications_per_month=1_000,
        corrections_per_month=100,
        max_rpm=500,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=7,
        overage_allowed=False,
    ),
    "pro": PlanConfig(
        observations_per_month=150_000,
        verifications_per_month=15_000,
        corrections_per_month=-1,
        max_rpm=1_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=False,
        retention_days=30,
        overage_allowed=True,
    ),
    "team": PlanConfig(
        observations_per_month=1_500_000,
        verifications_per_month=150_000,
        corrections_per_month=-1,
        max_rpm=5_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=90,
        overage_allowed=True,
    ),
    "enterprise": PlanConfig(
        observations_per_month=10_000_000,
        verifications_per_month=1_000_000,
        corrections_per_month=-1,
        max_rpm=10_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=365,
        overage_allowed=True,
    ),
}


def get_plan_config(plan: str, overrides: dict[str, Any] | None = None) -> PlanConfig:
    """Return the PlanConfig for the given plan name.

    Falls back to ``"free"`` for unknown plan values.
    If *overrides* is provided (from ``accounts.vex_plan_overrides``),
    those values are merged on top of the plan defaults.
    """
    base = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    if not overrides:
        return base
    from dataclasses import asdict

    merged = {**asdict(base), **{k: v for k, v in overrides.items() if v is not None}}
    return PlanConfig(**merged)
