"""Tests for Z-score based cost and latency anomaly detection."""

from unittest.mock import MagicMock

from app.anomaly import detect_anomalies


def _mock_db_with_stats(
    cost_count=20,
    cost_mean=0.10,
    cost_stddev=0.02,
    latency_count=20,
    latency_mean=500.0,
    latency_stddev=50.0,
):
    mock = MagicMock()
    mock.execute.return_value.fetchone.return_value = (
        cost_count,
        cost_mean,
        cost_stddev,
        latency_count,
        latency_mean,
        latency_stddev,
    )
    return mock


def _mock_db_no_data():
    mock = MagicMock()
    mock.execute.return_value.fetchone.return_value = None
    return mock


def test_no_anomaly_within_normal_range():
    db = _mock_db_with_stats()
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.12, "latency_ms": 550}
    result = detect_anomalies(event, db)
    assert result == []


def test_cost_anomaly_triggered():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50, "latency_ms": 500}
    result = detect_anomalies(event, db)
    assert len(result) == 1
    assert result[0]["alert_type"] == "cost_anomaly"
    assert result[0]["details"]["z_score"] > 3.0


def test_latency_anomaly_triggered():
    db = _mock_db_with_stats(latency_mean=500.0, latency_stddev=50.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.10, "latency_ms": 900}
    result = detect_anomalies(event, db)
    assert len(result) == 1
    assert result[0]["alert_type"] == "latency_anomaly"
    assert result[0]["details"]["z_score"] > 3.0


def test_both_anomalies_triggered():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02, latency_mean=500.0, latency_stddev=50.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50, "latency_ms": 900}
    result = detect_anomalies(event, db)
    assert len(result) == 2
    types = {r["alert_type"] for r in result}
    assert types == {"cost_anomaly", "latency_anomaly"}


def test_insufficient_samples_skips():
    db = _mock_db_with_stats(cost_count=5, latency_count=5)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 999, "latency_ms": 99999}
    result = detect_anomalies(event, db)
    assert result == []


def test_zero_stddev_skips():
    db = _mock_db_with_stats(cost_stddev=0.0, latency_stddev=0.0)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 999, "latency_ms": 99999}
    result = detect_anomalies(event, db)
    assert result == []


def test_no_db_data_skips():
    db = _mock_db_no_data()
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50}
    result = detect_anomalies(event, db)
    assert result == []


def test_none_values_handled():
    db = _mock_db_with_stats()
    event = {"agent_id": "bot-1", "execution_id": "e1"}
    result = detect_anomalies(event, db)
    assert result == []


def test_severity_escalation_high():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.50}
    result = detect_anomalies(event, db)
    assert result[0]["severity"] == "high"


def test_severity_medium():
    db = _mock_db_with_stats(cost_mean=0.10, cost_stddev=0.02)
    event = {"agent_id": "bot-1", "execution_id": "e1", "cost_estimate": 0.17}
    result = detect_anomalies(event, db)
    assert result[0]["severity"] == "medium"
