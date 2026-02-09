import uuid
from datetime import datetime, timezone

from agentguard.models import (
    ExecutionEvent,
    GuardResult,
    StepRecord,
    ThresholdConfig,
)


def test_threshold_config_defaults():
    config = ThresholdConfig()
    assert config.pass_threshold == 0.8
    assert config.flag_threshold == 0.5
    assert config.block_threshold == 0.3


def test_threshold_config_custom():
    config = ThresholdConfig(
        pass_threshold=0.9, flag_threshold=0.6, block_threshold=0.4
    )
    assert config.pass_threshold == 0.9


def test_threshold_config_validation_rejects_invalid_order():
    """block < flag < pass must hold."""
    import pytest

    with pytest.raises(ValueError):
        ThresholdConfig(pass_threshold=0.3, flag_threshold=0.5, block_threshold=0.8)


def test_step_record_creation():
    step = StepRecord(
        step_type="tool_call",
        name="query_database",
        input={"query": "SELECT *"},
        output={"rows": 5},
        duration_ms=120,
    )
    assert step.step_type == "tool_call"
    assert step.duration_ms == 120


def test_execution_event_creation():
    event = ExecutionEvent(
        agent_id="support-bot",
        input={"query": "billing question"},
        output={"response": "Your bill is $50"},
        task="Answer customer billing questions",
    )
    assert event.agent_id == "support-bot"
    assert event.execution_id is not None
    assert event.timestamp is not None
    assert event.latency_ms is None  # set later


def test_execution_event_auto_generates_execution_id():
    event1 = ExecutionEvent(agent_id="a", input={}, output={})
    event2 = ExecutionEvent(agent_id="a", input={}, output={})
    assert event1.execution_id != event2.execution_id


def test_guard_result_creation():
    result = GuardResult(
        output={"response": "answer"},
        confidence=0.92,
        action="pass",
        execution_id="exec-123",
    )
    assert result.confidence == 0.92
    assert result.action == "pass"
    assert result.corrections is None


def test_guard_result_with_corrections():
    result = GuardResult(
        output={"response": "corrected"},
        confidence=0.78,
        action="flag",
        execution_id="exec-456",
        corrections=[{"layer": 1, "action": "repair"}],
    )
    assert len(result.corrections) == 1
