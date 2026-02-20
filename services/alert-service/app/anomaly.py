"""Z-score based cost and latency anomaly detection.

Compares each execution's cost and latency against the agent's rolling
24-hour mean and standard deviation. Generates anomaly alerts when values
exceed a configurable number of standard deviations from the mean.

Default sensitivity: 3 standard deviations (99.7% confidence interval).
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger("agentguard.alert-service.anomaly")

DEFAULT_SENSITIVITY = 3.0
MIN_SAMPLES = 10  # Need at least 10 data points for meaningful stats


def detect_anomalies(
    event_data: Dict[str, Any],
    db_session: object,
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> List[Dict[str, Any]]:
    """Check for cost and latency anomalies in the given execution.

    Args:
        event_data: The verified event dict from Redis.
        db_session: A SQLAlchemy session for database reads.
        sensitivity: Number of standard deviations for the threshold.

    Returns:
        List of anomaly dicts, each with keys: alert_type, severity, details.
        Empty list if no anomalies detected.
    """
    agent_id = event_data.get("agent_id", "")
    execution_id = event_data.get("execution_id", "")

    cost = _parse_float(event_data.get("cost_estimate"))
    latency = _parse_float(event_data.get("latency_ms"))

    if cost is None and latency is None:
        return []

    # Fetch rolling 24h stats for this agent
    stats = _get_agent_stats(agent_id, db_session)
    if stats is None:
        return []

    anomalies: List[Dict[str, Any]] = []

    # Cost anomaly check
    if cost is not None and stats["cost_count"] >= MIN_SAMPLES:
        mean = stats["cost_mean"]
        stddev = stats["cost_stddev"]
        if stddev > 0:
            z_score = (cost - mean) / stddev
            if z_score > sensitivity:
                anomalies.append({
                    "alert_type": "cost_anomaly",
                    "severity": "high" if z_score > sensitivity * 1.5 else "medium",
                    "details": {
                        "metric": "cost_estimate",
                        "value": cost,
                        "mean_24h": round(mean, 6),
                        "stddev_24h": round(stddev, 6),
                        "z_score": round(z_score, 2),
                        "threshold": sensitivity,
                    },
                })

    # Latency anomaly check
    if latency is not None and stats["latency_count"] >= MIN_SAMPLES:
        mean = stats["latency_mean"]
        stddev = stats["latency_stddev"]
        if stddev > 0:
            z_score = (latency - mean) / stddev
            if z_score > sensitivity:
                anomalies.append({
                    "alert_type": "latency_anomaly",
                    "severity": "high" if z_score > sensitivity * 1.5 else "medium",
                    "details": {
                        "metric": "latency_ms",
                        "value": latency,
                        "mean_24h": round(mean, 2),
                        "stddev_24h": round(stddev, 2),
                        "z_score": round(z_score, 2),
                        "threshold": sensitivity,
                    },
                })

    return anomalies


def _get_agent_stats(
    agent_id: str,
    db_session: object,
) -> Optional[Dict[str, Any]]:
    """Fetch rolling 24h mean and stddev for cost and latency."""
    try:
        result = db_session.execute(
            text("""
                SELECT
                    COUNT(cost_estimate) AS cost_count,
                    AVG(cost_estimate) AS cost_mean,
                    STDDEV_POP(cost_estimate) AS cost_stddev,
                    COUNT(latency_ms) AS latency_count,
                    AVG(latency_ms) AS latency_mean,
                    STDDEV_POP(latency_ms) AS latency_stddev
                FROM executions
                WHERE agent_id = :agent_id
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            """),
            {"agent_id": agent_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "cost_count": row[0] or 0,
            "cost_mean": float(row[1]) if row[1] is not None else 0.0,
            "cost_stddev": float(row[2]) if row[2] is not None else 0.0,
            "latency_count": row[3] or 0,
            "latency_mean": float(row[4]) if row[4] is not None else 0.0,
            "latency_stddev": float(row[5]) if row[5] is not None else 0.0,
        }
    except Exception:
        logger.warning(
            "Failed to fetch agent stats for %s", agent_id, exc_info=True
        )
        return None


def _parse_float(value: Any) -> Optional[float]:
    """Safely parse a value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
