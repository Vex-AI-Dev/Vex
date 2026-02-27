"""Pydantic models for verification results and configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """A single turn in a multi-turn conversation."""

    sequence_number: int
    input: Any = None
    output: Any = None
    task: str | None = None


class CheckResult(BaseModel):
    """Result of a single verification check."""

    check_type: str  # "schema", "hallucination", "drift", "coherence"
    score: float | None = None  # 0-1, None if unable to verify
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class GuardrailRule(BaseModel):
    """A single custom guardrail rule (mirrors shared.models.GuardrailRule)."""

    id: str | None = None
    name: str = ""
    rule_type: str  # "regex", "keyword", "threshold", "llm"
    condition: dict[str, Any] = Field(default_factory=dict)
    action: str = "flag"  # "flag" or "block"
    enabled: bool = True


class VerificationConfig(BaseModel):
    """Configuration for verification thresholds and check weights."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "schema": 0.3,
            "hallucination": 0.4,
            "drift": 0.3,
        }
    )
    pass_threshold: float = 0.8
    flag_threshold: float = 0.5
    guardrails: list[GuardrailRule] = Field(default_factory=list)


class CorrectionAttempt(BaseModel):
    """Record of a single correction attempt within the cascade."""

    layer: int  # 1, 2, or 3
    layer_name: str  # "repair", "constrained_regen", "full_reprompt"
    input_action: str  # action that triggered correction
    input_confidence: float | None = None
    corrected_output: Any = None
    verification: dict[str, Any] | None = None
    model_used: str = ""
    latency_ms: float = 0.0
    success: bool = False


class CorrectionResult(BaseModel):
    """Full correction cascade outcome."""

    corrected: bool = False
    final_output: Any = None
    attempts: list[CorrectionAttempt] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    escalation_path: list[int] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Composite result from the full verification pipeline."""

    confidence: float | None = None  # weighted composite, None if all checks failed
    action: str = "pass"  # "pass" | "flag" | "block"
    checks: dict[str, CheckResult] = Field(default_factory=dict)
    correction: CorrectionResult | None = None
