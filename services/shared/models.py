"""Shared Pydantic models for Vex backend services.

These models define the API contract between the SDK and backend services.
They mirror SDK types (StepRecord, ExecutionEvent -> IngestEvent) for
serialization compatibility, but live in a separate package so backend
services do not depend on the SDK.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """A single turn in a multi-turn conversation.

    Mirrors the SDK's ConversationTurn for serialization compatibility.
    Used by the verification engine to evaluate cross-turn consistency.
    """

    sequence_number: int
    input: Any = None
    output: Any = None
    task: str | None = None


class StepRecord(BaseModel):
    """An intermediate agent step (tool call, LLM call, etc.).

    Mirrors the SDK's StepRecord for serialization compatibility.
    """

    step_type: str
    name: str
    input: Any = None
    output: Any = None
    duration_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestEvent(BaseModel):
    """Telemetry payload received from the SDK.

    Mirrors the SDK's ExecutionEvent. This is the primary ingest format
    for both async (ingestion) and sync (verification) paths.
    """

    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str | None = None
    parent_execution_id: str | None = None
    sequence_number: int | None = None
    agent_id: str
    task: str | None = None
    input: Any = None
    output: Any = None
    steps: list[StepRecord] = Field(default_factory=list)
    token_count: int | None = None
    cost_estimate: float | None = None
    latency_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ground_truth: Any = None
    schema_definition: dict[str, Any] | None = None
    conversation_history: list[ConversationTurn] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestBatchRequest(BaseModel):
    """A batch of ingest events submitted together."""

    events: list[IngestEvent]


class IngestResponse(BaseModel):
    """Response returned from ingestion endpoints."""

    accepted: int
    execution_ids: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    """Result of a single verification check (schema, hallucination, etc.)."""

    check_type: str
    score: float
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class VerifyRequest(IngestEvent):
    """Request payload for synchronous verification.

    Inherits from IngestEvent -- same payload structure, but semantically
    indicates the caller expects a synchronous verification response.
    """

    pass


class CorrectionAttemptResponse(BaseModel):
    """Wire format for a single correction attempt."""

    layer: int
    layer_name: str
    corrected_output: Any = None
    confidence: float | None = None
    action: str = "pass"
    success: bool = False
    latency_ms: float = 0.0


class VerifyResponse(BaseModel):
    """Response from synchronous verification."""

    execution_id: str
    confidence: float | None = None
    action: str = "pass"
    output: Any = None
    corrections: list[dict[str, Any]] | None = None
    checks: dict[str, CheckResult] = Field(default_factory=dict)
    corrected: bool = False
    original_output: Any | None = None
    correction_attempts: list[CorrectionAttemptResponse] | None = None
    correction_skipped: bool = False
    correction_skipped_reason: str | None = None
