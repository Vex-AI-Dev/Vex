"""Tests for tool_policy guardrail rule type."""

import pytest

from engine.guardrails import check
from engine.models import GuardrailRule
from shared.models import StepRecord


@pytest.mark.asyncio
async def test_tool_policy_deny_blocks_matching_tool():
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="send_email"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert not result.passed
    assert result.score == 0.0
    violations = result.details.get("violations", [])
    assert len(violations) == 1
    assert violations[0]["rule_name"] == "Block send_email"


@pytest.mark.asyncio
async def test_tool_policy_deny_passes_when_tool_not_used():
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="calculator"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert result.passed
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_tool_policy_allow_with_limit_blocks_excess():
    rules = [
        GuardrailRule(
            name="Limit web_search",
            rule_type="tool_policy",
            condition={"tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 3},
            action="flag",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert not result.passed
    violations = result.details.get("violations", [])
    assert len(violations) == 1


@pytest.mark.asyncio
async def test_tool_policy_allow_within_limit_passes():
    rules = [
        GuardrailRule(
            name="Limit web_search",
            rule_type="tool_policy",
            condition={"tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 5},
            action="flag",
        ),
    ]
    steps = [
        StepRecord(step_type="tool_call", name="web_search"),
        StepRecord(step_type="tool_call", name="web_search"),
    ]
    result = await check(output="some output", rules=rules, steps=steps)
    assert result.passed


@pytest.mark.asyncio
async def test_tool_policy_no_steps_passes():
    rules = [
        GuardrailRule(
            name="Block send_email",
            rule_type="tool_policy",
            condition={"tool_name": "send_email", "policy": "deny"},
            action="block",
        ),
    ]
    result = await check(output="some output", rules=rules, steps=None)
    assert result.passed
