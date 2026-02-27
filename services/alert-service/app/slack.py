"""Slack webhook delivery with Block Kit formatting.

Delivers alert notifications to Slack channels via incoming webhooks.
Uses the same retry pattern as the HTTP webhook module.
"""

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("agentguard.alert-service.slack")

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]
SLACK_TIMEOUT_S = 5.0


def get_slack_webhook_url(agent_id: str) -> Optional[str]:
    """Resolve the Slack webhook URL for an agent.

    Checks ``SLACK_WEBHOOK_URL_{AGENT_ID}`` first (with hyphens replaced
    by underscores), then falls back to the global ``SLACK_WEBHOOK_URL``.

    Returns:
        The Slack webhook URL, or None if not configured.
    """
    env_key = f"SLACK_WEBHOOK_URL_{agent_id.replace('-', '_').upper()}"
    url = os.environ.get(env_key)
    if url:
        return url
    return os.environ.get("SLACK_WEBHOOK_URL")


def _severity_emoji(severity: str) -> str:
    if severity == "critical":
        return ":rotating_light:"
    return ":warning:"


def format_slack_message(
    alert_id: str,
    agent_id: str,
    execution_id: str,
    action: str,
    severity: str,
    confidence: Optional[float],
    failure_types: list[str],
    dashboard_base_url: Optional[str] = None,
    suppressed_count: int = 0,
) -> dict[str, Any]:
    """Build a Slack Block Kit message for an alert.

    Returns:
        A dict suitable for POSTing to Slack's incoming webhook API.
    """
    emoji = _severity_emoji(severity)
    confidence_str = f"{confidence:.2f}" if confidence is not None else "N/A"
    failures_str = ", ".join(failure_types) if failure_types else "none"

    header_text = f"{emoji} Agent *{agent_id}* output *{action}ed* verification"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Verification {action.capitalize()}", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header_text},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:*\n{agent_id}"},
                {"type": "mrkdwn", "text": f"*Action:*\n{action}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence_str}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                {"type": "mrkdwn", "text": f"*Failed Checks:*\n{failures_str}"},
                {"type": "mrkdwn", "text": f"*Execution:*\n`{execution_id}`"},
            ],
        },
    ]

    if suppressed_count > 0:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":repeat: {suppressed_count} similar events suppressed in the last 5 minutes",
                    },
                ],
            }
        )

    if dashboard_base_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in Dashboard"},
                        "url": f"{dashboard_base_url}/executions/{execution_id}",
                    },
                ],
            }
        )

    blocks.append({"type": "divider"})

    return {"blocks": blocks}


def format_anomaly_slack_message(
    alert_id: str,
    agent_id: str,
    execution_id: str,
    alert_type: str,
    severity: str,
    details: dict[str, Any],
    dashboard_base_url: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Slack Block Kit message for a cost/latency anomaly alert."""
    emoji = _severity_emoji(severity)
    metric = details.get("metric", "unknown")
    value = details.get("value", 0)
    mean = details.get("mean_24h", 0)
    z_score = details.get("z_score", 0)

    metric_label = "Cost" if "cost" in metric else "Latency"
    unit = "" if "cost" in metric else "ms"

    header_text = f"{emoji} *{metric_label} Anomaly* detected for agent *{agent_id}*"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{metric_label} Anomaly Detected", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header_text},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:*\n{agent_id}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                {"type": "mrkdwn", "text": f"*Current Value:*\n{value}{unit}"},
                {"type": "mrkdwn", "text": f"*24h Mean:*\n{mean}{unit}"},
                {"type": "mrkdwn", "text": f"*Z-Score:*\n{z_score}"},
                {"type": "mrkdwn", "text": f"*Execution:*\n`{execution_id}`"},
            ],
        },
    ]

    if dashboard_base_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in Dashboard"},
                        "url": f"{dashboard_base_url}/executions/{execution_id}",
                    },
                ],
            }
        )

    blocks.append({"type": "divider"})
    return {"blocks": blocks}


async def deliver_slack(
    url: str,
    payload: dict[str, Any],
) -> tuple[bool, int]:
    """Deliver a Slack webhook payload with retry.

    Args:
        url: The Slack incoming webhook URL.
        payload: The Block Kit message payload.

    Returns:
        Tuple of (success: bool, status_code: int).
    """
    last_status = 0

    async with httpx.AsyncClient(timeout=SLACK_TIMEOUT_S) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(url, json=payload)
                last_status = response.status_code

                if 200 <= response.status_code < 300:
                    logger.info(
                        "Slack alert delivered (status %d, attempt %d)",
                        response.status_code,
                        attempt + 1,
                    )
                    return True, response.status_code

                logger.warning(
                    "Slack webhook returned %d (attempt %d/%d)",
                    response.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except Exception:
                logger.warning(
                    "Slack webhook failed (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                    exc_info=True,
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

    logger.error("Slack delivery failed after %d attempts", MAX_RETRIES)
    return False, last_status
