# Phase 1: Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the observability foundation — Python SDK that captures agent telemetry, Ingestion API that receives it, Storage Worker that persists it, and a minimal Dashboard that displays it. Design partners can instrument agents and see traces.

**Architecture:** FastAPI backend services connected via Redis Streams. Python SDK wraps agent calls and sends telemetry async. Storage Worker persists to PostgreSQL/TimescaleDB (metadata) + S3 (payloads). React dashboard renders fleet list and trace viewer. Everything containerized with docker-compose for local dev.

**Tech Stack:** Python 3.11, FastAPI, Redis 7 Streams, PostgreSQL 16 + TimescaleDB, S3 (MinIO locally), React + TypeScript, Docker + docker-compose, pytest, Alembic (migrations)

**Reference:** `docs/plans/2026-02-10-agentguard-architecture-design.md`

---

## Task 1: Python SDK — Core Data Models and Configuration

**Files:**
- Create: `sdk/python/agentguard/__init__.py`
- Create: `sdk/python/agentguard/models.py`
- Create: `sdk/python/agentguard/config.py`
- Create: `sdk/python/agentguard/exceptions.py`
- Test: `sdk/python/tests/__init__.py`
- Test: `sdk/python/tests/test_models.py`
- Test: `sdk/python/tests/test_config.py`
- Create: `sdk/python/pyproject.toml`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard"
version = "0.1.0"
description = "The reliability layer for AI agents in production"
requires-python = ">=3.9"
dependencies = [
    "httpx>=0.25.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "respx>=0.20.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Write failing tests for data models**

```python
# sdk/python/tests/test_models.py
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
```

**Step 3: Run tests to verify they fail**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && pip install -e "sdk/python[dev]" && pytest sdk/python/tests/test_models.py -v`
Expected: FAIL — modules not found

**Step 4: Implement data models**

```python
# sdk/python/agentguard/__init__.py
from agentguard.config import GuardConfig
from agentguard.models import GuardResult

__all__ = ["GuardConfig", "GuardResult"]
__version__ = "0.1.0"
```

```python
# sdk/python/agentguard/exceptions.py
class AgentGuardError(Exception):
    """Base exception for AgentGuard SDK."""

class ConfigurationError(AgentGuardError):
    """Invalid SDK configuration."""

class IngestionError(AgentGuardError):
    """Failed to send telemetry to AgentGuard backend."""

class VerificationError(AgentGuardError):
    """Verification request failed."""
```

```python
# sdk/python/agentguard/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ThresholdConfig(BaseModel):
    pass_threshold: float = 0.8
    flag_threshold: float = 0.5
    block_threshold: float = 0.3

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ThresholdConfig":
        if not (self.block_threshold < self.flag_threshold < self.pass_threshold):
            raise ValueError(
                "Thresholds must satisfy: block < flag < pass. "
                f"Got block={self.block_threshold}, flag={self.flag_threshold}, "
                f"pass={self.pass_threshold}"
            )
        return self


class StepRecord(BaseModel):
    step_type: str  # "tool_call", "llm", "custom"
    name: str
    input: Any = None
    output: Any = None
    duration_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionEvent(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    task: str | None = None
    input: Any
    output: Any
    steps: list[StepRecord] = Field(default_factory=list)
    token_count: int | None = None
    latency_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ground_truth: Any = None
    schema_definition: dict | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuardResult(BaseModel):
    output: Any
    confidence: float | None = None
    action: str = "pass"  # "pass" | "flag" | "block"
    corrections: list[dict] | None = None
    execution_id: str
    verification: dict | None = None
```

```python
# sdk/python/agentguard/config.py
from __future__ import annotations

from pydantic import BaseModel

from agentguard.models import ThresholdConfig


class GuardConfig(BaseModel):
    mode: str = "async"  # "sync" | "async"
    correction: str = "none"  # "cascade" | "none"
    transparency: str = "opaque"  # "opaque" | "transparent"
    confidence_threshold: ThresholdConfig = Field(default_factory=ThresholdConfig)
    api_url: str = "https://api.agentguard.dev"
    flush_interval_s: float = 1.0
    flush_batch_size: int = 50
    timeout_s: float = 2.0

from pydantic import Field
```

**Step 5: Write failing tests for config**

```python
# sdk/python/tests/test_config.py
from agentguard.config import GuardConfig
from agentguard.models import ThresholdConfig


def test_guard_config_defaults():
    config = GuardConfig()
    assert config.mode == "async"
    assert config.correction == "none"
    assert config.transparency == "opaque"
    assert config.flush_interval_s == 1.0
    assert config.flush_batch_size == 50
    assert config.timeout_s == 2.0


def test_guard_config_custom():
    config = GuardConfig(
        mode="sync",
        correction="cascade",
        transparency="transparent",
        api_url="http://localhost:8000",
    )
    assert config.mode == "sync"
    assert config.api_url == "http://localhost:8000"


def test_guard_config_with_custom_thresholds():
    config = GuardConfig(
        confidence_threshold=ThresholdConfig(
            pass_threshold=0.9,
            flag_threshold=0.6,
            block_threshold=0.2,
        )
    )
    assert config.confidence_threshold.pass_threshold == 0.9
```

**Step 6: Run all tests to verify they pass**

Run: `pytest sdk/python/tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add sdk/python/
git commit -m "feat(sdk): add core data models and configuration"
```

---

## Task 2: Python SDK — Telemetry Client (Async Buffer + HTTP)

**Files:**
- Create: `sdk/python/agentguard/client.py`
- Create: `sdk/python/agentguard/transport.py`
- Test: `sdk/python/tests/test_transport.py`
- Test: `sdk/python/tests/test_client.py`

**Step 1: Write failing tests for transport layer**

```python
# sdk/python/tests/test_transport.py
import asyncio
import pytest
import httpx
import respx

from agentguard.transport import AsyncTransport
from agentguard.models import ExecutionEvent


@pytest.fixture
def transport():
    return AsyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        flush_interval_s=0.1,
        flush_batch_size=5,
        timeout_s=2.0,
    )


def test_transport_creation(transport):
    assert transport.api_url == "https://api.agentguard.dev"
    assert transport._buffer == []


def test_transport_enqueue(transport):
    event = ExecutionEvent(agent_id="test", input={}, output={})
    transport.enqueue(event)
    assert len(transport._buffer) == 1


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_sends_batch(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 3})
    )
    for _ in range(3):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    await transport.flush()

    assert route.called
    assert len(transport._buffer) == 0


@respx.mock
@pytest.mark.asyncio
async def test_transport_flush_empty_buffer_noop(transport):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )
    await transport.flush()
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_transport_auto_flush_on_batch_size():
    transport = AsyncTransport(
        api_url="https://api.agentguard.dev",
        api_key="ag_test_key",
        flush_interval_s=10.0,  # long interval so it won't trigger
        flush_batch_size=3,
        timeout_s=2.0,
    )
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 3})
    )

    for _ in range(3):
        transport.enqueue(ExecutionEvent(agent_id="test", input={}, output={}))

    # Give the auto-flush a moment to trigger
    await asyncio.sleep(0.1)
    await transport.flush()  # force flush remaining
    assert route.call_count >= 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest sdk/python/tests/test_transport.py -v`
Expected: FAIL — module not found

**Step 3: Implement transport layer**

```python
# sdk/python/agentguard/transport.py
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import httpx

from agentguard.models import ExecutionEvent

logger = logging.getLogger("agentguard")


class AsyncTransport:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        flush_interval_s: float = 1.0,
        flush_batch_size: int = 50,
        timeout_s: float = 2.0,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.flush_interval_s = flush_interval_s
        self.flush_batch_size = flush_batch_size
        self.timeout_s = timeout_s
        self._buffer: list[ExecutionEvent] = []
        self._lock = threading.Lock()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "X-AgentGuard-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_s,
            )
        return self._client

    def enqueue(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self.flush_batch_size:
                # Schedule a flush in the background if possible
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.flush())
                except RuntimeError:
                    pass  # No event loop — will flush on next interval

    async def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()

        try:
            client = self._get_client()
            payload = [event.model_dump(mode="json") for event in batch]
            response = await client.post(
                f"{self.api_url}/v1/ingest/batch",
                json={"events": payload},
            )
            response.raise_for_status()
            logger.debug(f"Flushed {len(batch)} events")
        except Exception as e:
            logger.warning(f"Failed to flush {len(batch)} events: {e}")
            # Put events back in the buffer for retry
            with self._lock:
                self._buffer = batch + self._buffer

    async def close(self) -> None:
        await self.flush()
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class SyncTransport:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_s: float = 2.0,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                headers={
                    "X-AgentGuard-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_s,
            )
        return self._client

    def verify(self, event: ExecutionEvent) -> dict:
        client = self._get_client()
        response = client.post(
            f"{self.api_url}/v1/verify",
            json=event.model_dump(mode="json"),
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()
```

**Step 4: Run tests to verify they pass**

Run: `pytest sdk/python/tests/test_transport.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add sdk/python/agentguard/transport.py sdk/python/tests/test_transport.py
git commit -m "feat(sdk): add async and sync transport layers"
```

---

## Task 3: Python SDK — Guard Client (Decorator, Context Manager, Explicit Wrap)

**Files:**
- Create: `sdk/python/agentguard/guard.py`
- Test: `sdk/python/tests/test_guard.py`
- Modify: `sdk/python/agentguard/__init__.py`

**Step 1: Write failing tests for the Guard client**

```python
# sdk/python/tests/test_guard.py
import time
import pytest
import httpx
import respx

from agentguard import AgentGuard, GuardConfig, GuardResult
from agentguard.config import GuardConfig
from agentguard.models import ThresholdConfig


@pytest.fixture
def guard():
    return AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
        ),
    )


def test_guard_creation(guard):
    assert guard.api_key == "ag_test_key"
    assert guard.config.mode == "async"


@respx.mock
def test_guard_watch_decorator_async_mode(guard):
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    @guard.watch(agent_id="test-bot", task="answer questions")
    def my_agent(query: str) -> str:
        return f"Answer to: {query}"

    result = my_agent("What is 2+2?")
    assert result.output == "Answer to: What is 2+2?"
    assert result.action == "pass"
    assert result.execution_id is not None


@respx.mock
def test_guard_watch_captures_latency(guard):
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    @guard.watch(agent_id="slow-bot")
    def slow_agent(query: str) -> str:
        time.sleep(0.05)
        return "done"

    result = slow_agent("test")
    assert result.output == "done"


@respx.mock
def test_guard_watch_handles_agent_exception(guard):
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )

    @guard.watch(agent_id="failing-bot")
    def failing_agent(query: str) -> str:
        raise ValueError("Agent broke")

    with pytest.raises(ValueError, match="Agent broke"):
        failing_agent("test")


@respx.mock
def test_guard_run_explicit(guard):
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    result = guard.run(
        agent_id="report-gen",
        task="Generate report",
        fn=lambda: {"report": "Q4 summary"},
    )
    assert result.output == {"report": "Q4 summary"}
    assert result.action == "pass"


@respx.mock
def test_guard_trace_context_manager(guard):
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    with guard.trace(agent_id="enricher", task="Enrich records") as trace:
        output = {"company": "ACME", "revenue": 1000000}
        trace.set_ground_truth({"source": "database"})
        trace.set_schema({"type": "object", "required": ["company", "revenue"]})
        trace.record(output)

    result = trace.result
    assert result.output == output
    assert result.action == "pass"


@respx.mock
def test_guard_sync_mode():
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-123",
            "confidence": 0.92,
            "action": "pass",
            "output": "verified answer",
            "corrections": None,
            "checks": {},
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    result = critical_agent("test")
    assert result.confidence == 0.92
    assert result.action == "pass"
```

**Step 2: Run tests to verify they fail**

Run: `pytest sdk/python/tests/test_guard.py -v`
Expected: FAIL — AgentGuard class not found

**Step 3: Implement the Guard client**

```python
# sdk/python/agentguard/guard.py
from __future__ import annotations

import asyncio
import functools
import logging
import time
import threading
from contextlib import contextmanager
from typing import Any, Callable

from agentguard.config import GuardConfig
from agentguard.models import ExecutionEvent, GuardResult, StepRecord
from agentguard.transport import AsyncTransport, SyncTransport

logger = logging.getLogger("agentguard")


class TraceContext:
    def __init__(self, agent_id: str, task: str | None, guard: "AgentGuard"):
        self._agent_id = agent_id
        self._task = task
        self._guard = guard
        self._ground_truth: Any = None
        self._schema: dict | None = None
        self._steps: list[StepRecord] = []
        self._output: Any = None
        self._start_time: float = time.monotonic()
        self.result: GuardResult | None = None

    def set_ground_truth(self, data: Any) -> None:
        self._ground_truth = data

    def set_schema(self, schema: dict) -> None:
        self._schema = schema

    def step(self, step_type: str, name: str, input: Any = None, output: Any = None, duration_ms: float | None = None) -> None:
        self._steps.append(StepRecord(
            step_type=step_type,
            name=name,
            input=input,
            output=output,
            duration_ms=duration_ms,
        ))

    def record(self, output: Any) -> None:
        self._output = output


class AgentGuard:
    def __init__(self, api_key: str, config: GuardConfig | None = None):
        self.api_key = api_key
        self.config = config or GuardConfig()
        self._async_transport = AsyncTransport(
            api_url=self.config.api_url,
            api_key=self.api_key,
            flush_interval_s=self.config.flush_interval_s,
            flush_batch_size=self.config.flush_batch_size,
            timeout_s=self.config.timeout_s,
        )
        self._sync_transport = SyncTransport(
            api_url=self.config.api_url,
            api_key=self.api_key,
            timeout_s=self.config.timeout_s,
        ) if self.config.mode == "sync" else None
        self._flush_thread: threading.Thread | None = None
        self._running = False

    def _ensure_flush_loop(self) -> None:
        if self._running:
            return
        self._running = True

        def _run_flush_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self._running:
                loop.run_until_complete(self._async_transport.flush())
                time.sleep(self.config.flush_interval_s)
            loop.run_until_complete(self._async_transport.flush())
            loop.close()

        self._flush_thread = threading.Thread(target=_run_flush_loop, daemon=True)
        self._flush_thread.start()

    def _process_event(self, event: ExecutionEvent) -> GuardResult:
        if self.config.mode == "sync" and self._sync_transport:
            try:
                response = self._sync_transport.verify(event)
                return GuardResult(
                    output=response.get("output", event.output),
                    confidence=response.get("confidence"),
                    action=response.get("action", "pass"),
                    corrections=response.get("corrections"),
                    execution_id=response.get("execution_id", event.execution_id),
                    verification=response.get("checks"),
                )
            except Exception as e:
                logger.warning(f"Sync verification failed, falling back to pass: {e}")
                return GuardResult(
                    output=event.output,
                    confidence=None,
                    action="pass",
                    execution_id=event.execution_id,
                )
        else:
            self._ensure_flush_loop()
            self._async_transport.enqueue(event)
            return GuardResult(
                output=event.output,
                action="pass",
                execution_id=event.execution_id,
            )

    def watch(self, agent_id: str, task: str | None = None):
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs) -> GuardResult:
                start = time.monotonic()
                try:
                    output = fn(*args, **kwargs)
                except Exception:
                    raise
                latency_ms = (time.monotonic() - start) * 1000

                event = ExecutionEvent(
                    agent_id=agent_id,
                    task=task,
                    input={"args": args, "kwargs": kwargs},
                    output=output,
                    latency_ms=latency_ms,
                )
                return self._process_event(event)
            return wrapper
        return decorator

    def run(
        self,
        agent_id: str,
        fn: Callable,
        task: str | None = None,
        ground_truth: Any = None,
        schema: dict | None = None,
    ) -> GuardResult:
        start = time.monotonic()
        output = fn()
        latency_ms = (time.monotonic() - start) * 1000

        event = ExecutionEvent(
            agent_id=agent_id,
            task=task,
            input={},
            output=output,
            latency_ms=latency_ms,
            ground_truth=ground_truth,
            schema_definition=schema,
        )
        return self._process_event(event)

    @contextmanager
    def trace(self, agent_id: str, task: str | None = None):
        ctx = TraceContext(agent_id=agent_id, task=task, guard=self)
        try:
            yield ctx
        finally:
            if ctx._output is not None:
                latency_ms = (time.monotonic() - ctx._start_time) * 1000
                event = ExecutionEvent(
                    agent_id=agent_id,
                    task=task,
                    input={},
                    output=ctx._output,
                    steps=ctx._steps,
                    latency_ms=latency_ms,
                    ground_truth=ctx._ground_truth,
                    schema_definition=ctx._schema,
                )
                ctx.result = self._process_event(event)

    def close(self) -> None:
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=5.0)
        if self._sync_transport:
            self._sync_transport.close()
```

**Step 4: Update `__init__.py` to export AgentGuard**

```python
# sdk/python/agentguard/__init__.py
from agentguard.config import GuardConfig
from agentguard.guard import AgentGuard
from agentguard.models import GuardResult

__all__ = ["AgentGuard", "GuardConfig", "GuardResult"]
__version__ = "0.1.0"
```

**Step 5: Run all SDK tests**

Run: `pytest sdk/python/tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add sdk/python/
git commit -m "feat(sdk): add Guard client with decorator, context manager, and explicit wrap"
```

---

## Task 4: Shared Models — Common Pydantic Models for Backend Services

**Files:**
- Create: `services/shared/__init__.py`
- Create: `services/shared/models.py`
- Create: `services/shared/pyproject.toml`
- Test: `services/shared/tests/__init__.py`
- Test: `services/shared/tests/test_models.py`

**Step 1: Create pyproject.toml for shared package**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard-shared"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Write failing tests for shared models**

```python
# services/shared/tests/test_models.py
from shared.models import (
    IngestEvent,
    IngestBatchRequest,
    IngestResponse,
    VerifyRequest,
    VerifyResponse,
    CheckResult,
)


def test_ingest_event_creation():
    event = IngestEvent(
        agent_id="bot-1",
        input={"query": "test"},
        output={"answer": "result"},
    )
    assert event.agent_id == "bot-1"
    assert event.execution_id is not None


def test_ingest_batch_request():
    events = [
        IngestEvent(agent_id="bot-1", input={}, output={}),
        IngestEvent(agent_id="bot-2", input={}, output={}),
    ]
    batch = IngestBatchRequest(events=events)
    assert len(batch.events) == 2


def test_ingest_response():
    resp = IngestResponse(accepted=5, execution_ids=["a", "b", "c", "d", "e"])
    assert resp.accepted == 5


def test_verify_response():
    resp = VerifyResponse(
        execution_id="exec-1",
        confidence=0.85,
        action="pass",
        output={"answer": "verified"},
        corrections=None,
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )
    assert resp.action == "pass"
    assert resp.checks["schema"].passed is True


def test_check_result():
    cr = CheckResult(
        check_type="hallucination",
        score=0.72,
        passed=True,
        details={"flagged_claims": []},
    )
    assert cr.check_type == "hallucination"
    assert cr.score == 0.72
```

**Step 3: Run tests to verify they fail**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && pip install -e "services/shared[dev]" && pytest services/shared/tests/ -v`
Expected: FAIL

**Step 4: Implement shared models**

```python
# services/shared/__init__.py
```

```python
# services/shared/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class StepRecord(BaseModel):
    step_type: str
    name: str
    input: Any = None
    output: Any = None
    duration_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestEvent(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    task: str | None = None
    input: Any
    output: Any
    steps: list[StepRecord] = Field(default_factory=list)
    token_count: int | None = None
    latency_ms: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ground_truth: Any = None
    schema_definition: dict | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestBatchRequest(BaseModel):
    events: list[IngestEvent]


class IngestResponse(BaseModel):
    accepted: int
    execution_ids: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    check_type: str
    score: float
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class VerifyRequest(IngestEvent):
    pass


class VerifyResponse(BaseModel):
    execution_id: str
    confidence: float | None = None
    action: str = "pass"
    output: Any = None
    corrections: list[dict] | None = None
    checks: dict[str, CheckResult] = Field(default_factory=dict)
```

**Step 5: Run tests to verify they pass**

Run: `pytest services/shared/tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add services/shared/
git commit -m "feat(shared): add common Pydantic models for backend services"
```

---

## Task 5: Infrastructure — Docker Compose + PostgreSQL/TimescaleDB + Redis + MinIO

**Files:**
- Create: `infra/docker/docker-compose.yml`
- Create: `infra/docker/.env.example`
- Create: `services/ingestion-api/Dockerfile`
- Create: `services/storage-worker/Dockerfile`

**Step 1: Create docker-compose.yml**

```yaml
# infra/docker/docker-compose.yml
version: "3.9"

services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: agentguard
      POSTGRES_USER: agentguard
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-agentguard_dev}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentguard"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-agentguard}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-agentguard_dev}
    ports:
      - "9000:9000"
      - "9001:9001"
    command: server /data --console-address ":9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 5

  createbuckets:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 agentguard agentguard_dev;
      mc mb local/agentguard-traces --ignore-existing;
      exit 0;
      "

volumes:
  pgdata:
  redisdata:
  miniodata:
```

**Step 2: Create .env.example**

```bash
# infra/docker/.env.example
POSTGRES_PASSWORD=agentguard_dev
MINIO_ROOT_USER=agentguard
MINIO_ROOT_PASSWORD=agentguard_dev
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://agentguard:agentguard_dev@localhost:5432/agentguard
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=agentguard
S3_SECRET_KEY=agentguard_dev
S3_BUCKET=agentguard-traces
```

**Step 3: Start infra and verify**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/infra/docker && docker compose up -d`
Expected: postgres, redis, minio all healthy

Run: `docker compose ps`
Expected: All services running

**Step 4: Commit**

```bash
git add infra/
git commit -m "infra: add docker-compose with TimescaleDB, Redis, and MinIO"
```

---

## Task 6: Database Migrations — Schema Setup with Alembic

**Files:**
- Create: `services/migrations/alembic.ini`
- Create: `services/migrations/alembic/env.py`
- Create: `services/migrations/alembic/versions/001_initial_schema.py`
- Create: `services/migrations/pyproject.toml`

**Step 1: Create pyproject.toml for migrations**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard-migrations"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "alembic>=1.12.0",
    "psycopg2-binary>=2.9.0",
    "sqlalchemy>=2.0.0",
]
```

**Step 2: Create alembic.ini**

```ini
# services/migrations/alembic.ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://agentguard:agentguard_dev@localhost:5432/agentguard

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Step 3: Create Alembic env.py**

```python
# services/migrations/alembic/env.py
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Enable TimescaleDB extension
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        connection.commit()

        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4: Create initial migration**

```python
# services/migrations/alembic/versions/001_initial_schema.py
"""Initial schema with TimescaleDB hypertables.

Revision ID: 001
Revises:
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Organizations
    op.create_table(
        "organizations",
        sa.Column("org_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("api_keys", JSONB, server_default="[]"),
        sa.Column("plan", sa.String(50), server_default="'free'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Agents
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(128), primary_key=True),
        sa.Column("org_id", sa.String(64), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("task", sa.Text, nullable=True),
        sa.Column("config", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_org_id", "agents", ["org_id"])

    # Executions — TimescaleDB hypertable
    op.create_table(
        "executions",
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("action", sa.String(10), server_default="'pass'"),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("correction_layers_used", JSONB, nullable=True),
        sa.Column("trace_payload_ref", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default="'pass'"),
        sa.Column("task", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
    )
    op.create_primary_key("pk_executions", "executions", ["execution_id", "timestamp"])
    op.execute("SELECT create_hypertable('executions', 'timestamp')")
    op.create_index("ix_executions_agent_id", "executions", ["agent_id", "timestamp"])
    op.create_index("ix_executions_org_id", "executions", ["org_id", "timestamp"])

    # Check results — TimescaleDB hypertable
    op.create_table(
        "check_results",
        sa.Column("id", sa.BigInteger, autoincrement=True),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("check_type", sa.String(50), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("details", JSONB, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_primary_key("pk_check_results", "check_results", ["id", "timestamp"])
    op.execute("SELECT create_hypertable('check_results', 'timestamp')")
    op.create_index("ix_check_results_execution_id", "check_results", ["execution_id"])

    # Alerts
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("delivered", sa.Boolean, server_default="false"),
        sa.Column("webhook_response", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_alerts_agent_id", "alerts", ["agent_id"])
    op.create_index("ix_alerts_org_id", "alerts", ["org_id"])

    # Human reviews (for v2, create table now for schema stability)
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("verdict", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Continuous aggregate: agent health hourly
    op.execute("""
        CREATE MATERIALIZED VIEW agent_health_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            agent_id,
            time_bucket('1 hour', timestamp) AS bucket,
            COUNT(*) AS execution_count,
            AVG(confidence) AS avg_confidence,
            COUNT(*) FILTER (WHERE action = 'pass') AS pass_count,
            COUNT(*) FILTER (WHERE action = 'flag') AS flag_count,
            COUNT(*) FILTER (WHERE action = 'block') AS block_count,
            SUM(token_count) AS total_tokens,
            SUM(cost_estimate) AS total_cost,
            AVG(latency_ms) AS avg_latency
        FROM executions
        GROUP BY agent_id, bucket
    """)

    # Refresh policy: refresh every 1 minute, covering the last 2 hours
    op.execute("""
        SELECT add_continuous_aggregate_policy('agent_health_hourly',
            start_offset => INTERVAL '2 hours',
            end_offset => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute'
        )
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_health_hourly CASCADE")
    op.drop_table("human_reviews")
    op.drop_table("alerts")
    op.drop_table("check_results")
    op.drop_table("executions")
    op.drop_table("agents")
    op.drop_table("organizations")
```

**Step 5: Create `alembic/script.py.mako` (required by alembic)**

Standard file — create `services/migrations/alembic/script.py.mako` with default Alembic template.

**Step 6: Run migration**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/services/migrations && pip install -e ".[dev]" && alembic upgrade head`
Expected: Migration runs successfully, tables and hypertables created

**Step 7: Verify tables exist**

Run: `psql postgresql://agentguard:agentguard_dev@localhost:5432/agentguard -c "\dt"`
Expected: organizations, agents, executions, check_results, alerts, human_reviews tables visible

**Step 8: Commit**

```bash
git add services/migrations/
git commit -m "feat(db): add initial schema migration with TimescaleDB hypertables"
```

---

## Task 7: Ingestion API — FastAPI Service

**Files:**
- Create: `services/ingestion-api/app/__init__.py`
- Create: `services/ingestion-api/app/main.py`
- Create: `services/ingestion-api/app/auth.py`
- Create: `services/ingestion-api/app/redis_client.py`
- Create: `services/ingestion-api/app/routes.py`
- Create: `services/ingestion-api/pyproject.toml`
- Create: `services/ingestion-api/Dockerfile`
- Test: `services/ingestion-api/tests/__init__.py`
- Test: `services/ingestion-api/tests/test_routes.py`
- Test: `services/ingestion-api/tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard-ingestion-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "redis>=5.0.0",
    "pydantic>=2.0.0",
    "agentguard-shared",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Write failing tests**

```python
# services/ingestion-api/tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    mock.xadd = AsyncMock(return_value="1234567890-0")
    return mock


@pytest.fixture
def client(mock_redis):
    app = create_app()
    app.state.redis = mock_redis
    return TestClient(app)
```

```python
# services/ingestion-api/tests/test_routes.py
import pytest


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ingest_single_event(client, mock_redis):
    event = {
        "agent_id": "test-bot",
        "input": {"query": "hello"},
        "output": {"response": "world"},
    }
    response = client.post(
        "/v1/ingest",
        json=event,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 202
    assert "execution_id" in response.json()
    mock_redis.xadd.assert_called_once()


def test_ingest_batch(client, mock_redis):
    events = {
        "events": [
            {"agent_id": "bot-1", "input": {}, "output": {}},
            {"agent_id": "bot-2", "input": {}, "output": {}},
            {"agent_id": "bot-3", "input": {}, "output": {}},
        ]
    }
    response = client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] == 3
    assert len(data["execution_ids"]) == 3
    assert mock_redis.xadd.call_count == 3


def test_ingest_rejects_missing_api_key(client):
    response = client.post("/v1/ingest", json={"agent_id": "x", "input": {}, "output": {}})
    assert response.status_code == 401


def test_ingest_rejects_invalid_payload(client):
    response = client.post(
        "/v1/ingest",
        json={"bad": "data"},
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 422


def test_batch_rejects_over_50_events(client):
    events = {"events": [{"agent_id": f"bot-{i}", "input": {}, "output": {}} for i in range(51)]}
    response = client.post(
        "/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert response.status_code == 422
```

**Step 3: Run tests to verify they fail**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && pip install -e services/shared && pip install -e "services/ingestion-api[dev]" && pytest services/ingestion-api/tests/ -v`
Expected: FAIL

**Step 4: Implement the Ingestion API**

```python
# services/ingestion-api/app/__init__.py
```

```python
# services/ingestion-api/app/auth.py
from fastapi import HTTPException, Request


async def verify_api_key(request: Request) -> str:
    api_key = request.headers.get("X-AgentGuard-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-AgentGuard-Key header")
    # TODO: validate against DB in Phase 2. For now, accept any non-empty key.
    return api_key
```

```python
# services/ingestion-api/app/redis_client.py
import os
import redis.asyncio as redis


async def get_redis() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(url, decode_responses=True)
```

```python
# services/ingestion-api/app/routes.py
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.auth import verify_api_key
from shared.models import IngestEvent, IngestBatchRequest, IngestResponse

router = APIRouter()

STREAM_KEY = "executions.raw"
MAX_BATCH_SIZE = 50


class BatchRequest(BaseModel):
    events: list[IngestEvent] = Field(..., max_length=MAX_BATCH_SIZE)


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.post("/v1/ingest", status_code=202)
async def ingest_single(
    event: IngestEvent,
    request: Request,
    api_key: Annotated[str, Depends(verify_api_key)],
):
    redis = request.app.state.redis
    await redis.xadd(
        STREAM_KEY,
        {"data": event.model_dump_json()},
    )
    return {"accepted": 1, "execution_id": event.execution_id}


@router.post("/v1/ingest/batch", status_code=202)
async def ingest_batch(
    batch: BatchRequest,
    request: Request,
    api_key: Annotated[str, Depends(verify_api_key)],
):
    redis = request.app.state.redis
    execution_ids = []
    for event in batch.events:
        await redis.xadd(
            STREAM_KEY,
            {"data": event.model_dump_json()},
        )
        execution_ids.append(event.execution_id)

    return IngestResponse(accepted=len(batch.events), execution_ids=execution_ids)
```

```python
# services/ingestion-api/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.redis_client import get_redis
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = await get_redis()
    yield
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentGuard Ingestion API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
```

**Step 5: Create Dockerfile**

```dockerfile
# services/ingestion-api/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY services/shared /app/services/shared
RUN pip install /app/services/shared

COPY services/ingestion-api/pyproject.toml /app/
COPY services/ingestion-api/app /app/app

RUN pip install .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 6: Run tests**

Run: `pytest services/ingestion-api/tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add services/ingestion-api/
git commit -m "feat(ingestion-api): add FastAPI ingestion service with single and batch endpoints"
```

---

## Task 8: Storage Worker — Redis Consumer + S3 + PostgreSQL Writer

**Files:**
- Create: `services/storage-worker/app/__init__.py`
- Create: `services/storage-worker/app/main.py`
- Create: `services/storage-worker/app/s3_client.py`
- Create: `services/storage-worker/app/db.py`
- Create: `services/storage-worker/app/worker.py`
- Create: `services/storage-worker/pyproject.toml`
- Create: `services/storage-worker/Dockerfile`
- Test: `services/storage-worker/tests/__init__.py`
- Test: `services/storage-worker/tests/test_worker.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard-storage-worker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "redis>=5.0.0",
    "boto3>=1.29.0",
    "psycopg2-binary>=2.9.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.0.0",
    "agentguard-shared",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "moto[s3]>=4.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Write failing tests**

```python
# services/storage-worker/tests/test_worker.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.worker import process_event
from shared.models import IngestEvent


@pytest.fixture
def sample_event():
    return IngestEvent(
        execution_id="exec-test-123",
        agent_id="test-bot",
        task="Answer questions",
        input={"query": "hello"},
        output={"response": "world"},
        token_count=150,
        latency_ms=320.5,
    )


@pytest.fixture
def mock_s3():
    mock = MagicMock()
    mock.put_object = MagicMock()
    return mock


@pytest.fixture
def mock_db_session():
    mock = MagicMock()
    mock.execute = MagicMock()
    mock.commit = MagicMock()
    return mock


def test_process_event_writes_to_s3(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    mock_s3.put_object.assert_called_once()
    call_kwargs = mock_s3.put_object.call_args[1]
    assert "agentguard-traces" in call_kwargs["Bucket"]
    assert "exec-test-123" in call_kwargs["Key"]


def test_process_event_writes_to_db(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    mock_db_session.execute.assert_called_once()
    mock_db_session.commit.assert_called_once()


def test_process_event_s3_key_format(sample_event, mock_s3, mock_db_session):
    process_event(sample_event, s3_client=mock_s3, db_session=mock_db_session, org_id="org-1")
    call_kwargs = mock_s3.put_object.call_args[1]
    key = call_kwargs["Key"]
    # Format: {org_id}/{agent_id}/{date}/{execution_id}.json
    assert key.startswith("org-1/test-bot/")
    assert key.endswith("exec-test-123.json")
```

**Step 3: Run tests to verify they fail**

Run: `pip install -e "services/storage-worker[dev]" && pytest services/storage-worker/tests/ -v`
Expected: FAIL

**Step 4: Implement storage worker**

```python
# services/storage-worker/app/__init__.py
```

```python
# services/storage-worker/app/s3_client.py
import os
import boto3


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "agentguard"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "agentguard_dev"),
    )
```

```python
# services/storage-worker/app/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
```

```python
# services/storage-worker/app/worker.py
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")

S3_BUCKET = "agentguard-traces"


def process_event(
    event: IngestEvent,
    s3_client,
    db_session,
    org_id: str,
) -> None:
    date_str = event.timestamp.strftime("%Y-%m-%d")
    s3_key = f"{org_id}/{event.agent_id}/{date_str}/{event.execution_id}.json"

    # Write full payload to S3
    payload = event.model_dump_json()
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=payload,
        ContentType="application/json",
    )

    # Write metadata to PostgreSQL
    db_session.execute(
        text("""
            INSERT INTO executions (
                execution_id, agent_id, org_id, timestamp,
                confidence, action, latency_ms, token_count,
                cost_estimate, trace_payload_ref, status, task, metadata
            ) VALUES (
                :execution_id, :agent_id, :org_id, :timestamp,
                :confidence, :action, :latency_ms, :token_count,
                :cost_estimate, :trace_payload_ref, :status, :task, :metadata
            )
        """),
        {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "org_id": org_id,
            "timestamp": event.timestamp,
            "confidence": None,  # Set by verification engine later
            "action": "pass",
            "latency_ms": event.latency_ms,
            "token_count": event.token_count,
            "cost_estimate": None,
            "trace_payload_ref": f"s3://{S3_BUCKET}/{s3_key}",
            "status": "pass",
            "task": event.task,
            "metadata": json.dumps(event.metadata),
        },
    )
    db_session.commit()

    logger.info(f"Stored execution {event.execution_id} for agent {event.agent_id}")
```

```python
# services/storage-worker/app/main.py
import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from app.db import SessionLocal
from app.s3_client import get_s3_client
from app.worker import process_event
from shared.models import IngestEvent

logger = logging.getLogger("agentguard.storage-worker")
logging.basicConfig(level=logging.INFO)

STREAM_KEY = "executions.raw"
CONSUMER_GROUP = "storage-workers"
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "storage-worker-1")
DEFAULT_ORG = "default"  # TODO: resolve org from API key in Phase 2


async def run():
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Create consumer group if it doesn't exist
    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass  # Group already exists

    s3_client = get_s3_client()

    logger.info(f"Storage worker started. Listening on {STREAM_KEY}")

    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=10,
                block=5000,
            )

            if not messages:
                continue

            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        event = IngestEvent.model_validate_json(data["data"])
                        db_session = SessionLocal()
                        try:
                            process_event(event, s3_client, db_session, org_id=DEFAULT_ORG)
                        finally:
                            db_session.close()
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as e:
                        logger.error(f"Failed to process message {msg_id}: {e}")

        except Exception as e:
            logger.error(f"Stream read error: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
```

**Step 5: Create Dockerfile**

```dockerfile
# services/storage-worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY services/shared /app/services/shared
RUN pip install /app/services/shared

COPY services/storage-worker/pyproject.toml /app/
COPY services/storage-worker/app /app/app

RUN pip install .

CMD ["python", "-m", "app.main"]
```

**Step 6: Run tests**

Run: `pytest services/storage-worker/tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add services/storage-worker/
git commit -m "feat(storage-worker): add Redis consumer with S3 and PostgreSQL persistence"
```

---

## Task 9: Dashboard — React App with Fleet Health and Trace Views

**Files:**
- Create: `services/dashboard/package.json`
- Create: `services/dashboard/tsconfig.json`
- Create: `services/dashboard/src/App.tsx`
- Create: `services/dashboard/src/main.tsx`
- Create: `services/dashboard/src/api/client.ts`
- Create: `services/dashboard/src/types/index.ts`
- Create: `services/dashboard/src/pages/FleetHealth.tsx`
- Create: `services/dashboard/src/pages/ExecutionTrace.tsx`
- Create: `services/dashboard/src/pages/FailuresFeed.tsx`
- Create: `services/dashboard/src/components/AgentStatusBadge.tsx`
- Create: `services/dashboard/src/components/ConfidenceBar.tsx`
- Create: `services/dashboard/index.html`
- Create: `services/dashboard/vite.config.ts`
- Create: `services/dashboard/Dockerfile`

**Step 1: Initialize React project with Vite**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/services/dashboard && npm create vite@latest . -- --template react-ts`

**Step 2: Install dependencies**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/services/dashboard && npm install react-router-dom recharts date-fns && npm install -D @types/react-router-dom`

**Step 3: Create types**

```typescript
// services/dashboard/src/types/index.ts
export interface Agent {
  agent_id: string;
  name: string;
  task: string | null;
  status: "healthy" | "degraded" | "failing";
  pass_rate: number;
  avg_confidence: number;
  execution_count: number;
  total_cost: number;
}

export interface Execution {
  execution_id: string;
  agent_id: string;
  timestamp: string;
  confidence: number | null;
  action: "pass" | "flag" | "block";
  latency_ms: number | null;
  token_count: number | null;
  task: string | null;
  trace_payload_ref: string | null;
}

export interface TracePayload {
  execution_id: string;
  input: any;
  output: any;
  corrected_output: any | null;
  intermediate_steps: StepRecord[];
  verification_details: {
    schema?: CheckResult;
    hallucination?: CheckResult;
    drift?: CheckResult;
  } | null;
  correction_history: CorrectionRecord[];
}

export interface StepRecord {
  step_type: string;
  name: string;
  input: any;
  output: any;
  duration_ms: number | null;
  timestamp: string;
}

export interface CheckResult {
  check_type: string;
  score: number;
  passed: boolean;
  details: Record<string, any>;
}

export interface CorrectionRecord {
  layer: number;
  action: string;
  input_confidence: number;
  output_confidence: number;
  changes: any[];
}

export interface FleetSummary {
  total_agents: number;
  total_executions: number;
  overall_pass_rate: number;
  total_cost: number;
}
```

**Step 4: Create API client**

```typescript
// services/dashboard/src/api/client.ts
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8001";

async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  getFleetSummary: () => fetchJSON<any>("/v1/dashboard/fleet/summary"),
  getAgents: () => fetchJSON<any[]>("/v1/dashboard/agents"),
  getExecutions: (agentId?: string, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (agentId) params.set("agent_id", agentId);
    return fetchJSON<any[]>(`/v1/dashboard/executions?${params}`);
  },
  getTrace: (executionId: string) =>
    fetchJSON<any>(`/v1/dashboard/executions/${executionId}/trace`),
  getFailures: (limit = 50) =>
    fetchJSON<any[]>(`/v1/dashboard/failures?limit=${limit}`),
};
```

**Step 5: Create components**

```typescript
// services/dashboard/src/components/AgentStatusBadge.tsx
interface Props {
  status: "healthy" | "degraded" | "failing";
}

const colors = {
  healthy: { bg: "#dcfce7", text: "#166534", label: "Healthy" },
  degraded: { bg: "#fef9c3", text: "#854d0e", label: "Degraded" },
  failing: { bg: "#fecaca", text: "#991b1b", label: "Failing" },
};

export function AgentStatusBadge({ status }: Props) {
  const c = colors[status];
  return (
    <span
      style={{
        backgroundColor: c.bg,
        color: c.text,
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "12px",
        fontWeight: 600,
      }}
    >
      {c.label}
    </span>
  );
}
```

```typescript
// services/dashboard/src/components/ConfidenceBar.tsx
interface Props {
  value: number | null;
}

export function ConfidenceBar({ value }: Props) {
  if (value === null) return <span style={{ color: "#9ca3af" }}>--</span>;

  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "#22c55e" : value >= 0.5 ? "#eab308" : "#ef4444";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <div
        style={{
          width: "60px",
          height: "8px",
          backgroundColor: "#e5e7eb",
          borderRadius: "4px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            backgroundColor: color,
            borderRadius: "4px",
          }}
        />
      </div>
      <span style={{ fontSize: "13px", fontWeight: 500 }}>{value.toFixed(2)}</span>
    </div>
  );
}
```

**Step 6: Create page components (FleetHealth, ExecutionTrace, FailuresFeed)**

These are the three primary views described in the architecture doc. Implement as React components with `useEffect` + `useState` fetching from the API client. Use Recharts for the confidence trend chart on FleetHealth.

**Step 7: Create App.tsx with routes**

```typescript
// services/dashboard/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { FleetHealth } from "./pages/FleetHealth";
import { ExecutionTrace } from "./pages/ExecutionTrace";
import { FailuresFeed } from "./pages/FailuresFeed";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<FleetHealth />} />
        <Route path="/failures" element={<FailuresFeed />} />
        <Route path="/trace/:executionId" element={<ExecutionTrace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
```

**Step 8: Create Dockerfile**

```dockerfile
# services/dashboard/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Step 9: Verify build**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/services/dashboard && npm run build`
Expected: Build succeeds

**Step 10: Commit**

```bash
git add services/dashboard/
git commit -m "feat(dashboard): add React dashboard with fleet health, trace, and failures views"
```

---

## Task 10: Dashboard API — Backend Endpoints for Dashboard Queries

**Files:**
- Create: `services/dashboard-api/app/__init__.py`
- Create: `services/dashboard-api/app/main.py`
- Create: `services/dashboard-api/app/db.py`
- Create: `services/dashboard-api/app/routes.py`
- Create: `services/dashboard-api/app/s3_client.py`
- Create: `services/dashboard-api/pyproject.toml`
- Create: `services/dashboard-api/Dockerfile`
- Test: `services/dashboard-api/tests/__init__.py`
- Test: `services/dashboard-api/tests/test_routes.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentguard-dashboard-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "psycopg2-binary>=2.9.0",
    "sqlalchemy>=2.0.0",
    "boto3>=1.29.0",
    "pydantic>=2.0.0",
    "agentguard-shared",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "httpx>=0.25.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Write failing tests**

```python
# services/dashboard-api/tests/test_routes.py
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def mock_db():
    mock = MagicMock()
    return mock


@pytest.fixture
def client(mock_db):
    app = create_app()
    app.state.db_session_factory = lambda: mock_db
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_get_agents(client, mock_db):
    mock_db.execute.return_value.mappings.return_value.all.return_value = [
        {
            "agent_id": "bot-1",
            "name": "Support Bot",
            "task": "Answer questions",
            "execution_count": 100,
            "avg_confidence": 0.91,
            "pass_count": 95,
            "flag_count": 3,
            "block_count": 2,
            "total_cost": 12.50,
        }
    ]
    response = client.get("/v1/dashboard/agents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["agent_id"] == "bot-1"
    assert data[0]["status"] == "healthy"  # 95% pass rate


def test_get_executions(client, mock_db):
    mock_db.execute.return_value.mappings.return_value.all.return_value = [
        {
            "execution_id": "exec-1",
            "agent_id": "bot-1",
            "timestamp": "2026-02-10T12:00:00Z",
            "confidence": 0.85,
            "action": "pass",
            "latency_ms": 320,
            "token_count": 150,
            "task": "Answer questions",
        }
    ]
    response = client.get("/v1/dashboard/executions?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_failures(client, mock_db):
    mock_db.execute.return_value.mappings.return_value.all.return_value = [
        {
            "execution_id": "exec-2",
            "agent_id": "bot-1",
            "timestamp": "2026-02-10T13:00:00Z",
            "confidence": 0.25,
            "action": "block",
            "latency_ms": 1200,
            "token_count": 500,
            "task": "Generate report",
        }
    ]
    response = client.get("/v1/dashboard/failures?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action"] == "block"
```

**Step 3: Implement Dashboard API routes**

The Dashboard API queries TimescaleDB (uses continuous aggregates for fleet view, raw executions for trace/failures). For trace detail, it fetches the payload from S3.

Key endpoints:
- `GET /v1/dashboard/fleet/summary` — aggregate from `agent_health_hourly`
- `GET /v1/dashboard/agents` — per-agent stats from `agent_health_hourly`
- `GET /v1/dashboard/executions` — paginated list from `executions` table
- `GET /v1/dashboard/executions/{id}/trace` — fetch from S3
- `GET /v1/dashboard/failures` — filtered `executions` where action != 'pass'

**Step 4: Run tests**

Run: `pytest services/dashboard-api/tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add services/dashboard-api/
git commit -m "feat(dashboard-api): add FastAPI endpoints for dashboard queries"
```

---

## Task 11: Integration — Docker Compose Full Stack + End-to-End Test

**Files:**
- Modify: `infra/docker/docker-compose.yml` (add all services)
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_end_to_end.py`
- Create: `tests/e2e/requirements.txt`

**Step 1: Update docker-compose.yml to include all services**

Add the following services to the existing compose file:
- `ingestion-api` (port 8000)
- `dashboard-api` (port 8001)
- `storage-worker`
- `dashboard` (port 3000)

All services depend on `postgres`, `redis`, `minio` being healthy.

**Step 2: Write end-to-end test**

```python
# tests/e2e/test_end_to_end.py
"""
End-to-end test: SDK → Ingestion API → Redis → Storage Worker → PostgreSQL + S3 → Dashboard API
"""
import time
import httpx
import pytest


API_URL = "http://localhost:8000"
DASHBOARD_URL = "http://localhost:8001"


def test_full_pipeline():
    # 1. Send an execution event via ingestion API
    event = {
        "agent_id": "e2e-test-bot",
        "task": "End-to-end test",
        "input": {"query": "What is 2+2?"},
        "output": {"response": "4"},
        "token_count": 50,
        "latency_ms": 150.0,
    }
    resp = httpx.post(
        f"{API_URL}/v1/ingest",
        json=event,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert resp.status_code == 202
    execution_id = resp.json()["execution_id"]

    # 2. Wait for storage worker to process
    time.sleep(3)

    # 3. Verify execution appears in dashboard API
    resp = httpx.get(f"{DASHBOARD_URL}/v1/dashboard/executions?limit=10")
    assert resp.status_code == 200
    executions = resp.json()
    exec_ids = [e["execution_id"] for e in executions]
    assert execution_id in exec_ids

    # 4. Verify trace is retrievable
    resp = httpx.get(f"{DASHBOARD_URL}/v1/dashboard/executions/{execution_id}/trace")
    assert resp.status_code == 200
    trace = resp.json()
    assert trace["input"]["query"] == "What is 2+2?"


def test_batch_ingestion():
    events = {
        "events": [
            {"agent_id": f"batch-bot-{i}", "input": {"n": i}, "output": {"r": i * 2}}
            for i in range(5)
        ]
    }
    resp = httpx.post(
        f"{API_URL}/v1/ingest/batch",
        json=events,
        headers={"X-AgentGuard-Key": "ag_test_key"},
    )
    assert resp.status_code == 202
    assert resp.json()["accepted"] == 5


def test_sdk_integration():
    """Test using the actual SDK against the running stack."""
    from agentguard import AgentGuard, GuardConfig

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="http://localhost:8000",
        ),
    )

    @guard.watch(agent_id="sdk-e2e-bot", task="SDK integration test")
    def my_agent(query: str) -> str:
        return f"Answer: {query}"

    result = my_agent("testing")
    assert result.output == "Answer: testing"
    assert result.action == "pass"
    assert result.execution_id is not None

    # Give time for async flush
    time.sleep(3)

    # Verify it landed in the dashboard
    resp = httpx.get(f"{DASHBOARD_URL}/v1/dashboard/executions?limit=50")
    assert resp.status_code == 200
    exec_ids = [e["execution_id"] for e in resp.json()]
    assert result.execution_id in exec_ids

    guard.close()
```

**Step 3: Start full stack**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard/infra/docker && docker compose up -d --build`
Expected: All services healthy

**Step 4: Run e2e tests**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && pip install httpx && pytest tests/e2e/ -v -s`
Expected: All PASS

**Step 5: Commit**

```bash
git add infra/docker/docker-compose.yml tests/
git commit -m "feat: add full-stack docker-compose and end-to-end tests"
```

---

## Task 12: WebSocket — Real-time Dashboard Updates

**Files:**
- Modify: `services/dashboard-api/app/main.py`
- Create: `services/dashboard-api/app/websocket.py`
- Test: `services/dashboard-api/tests/test_websocket.py`

**Step 1: Implement WebSocket endpoint**

Add a `/ws` endpoint to the Dashboard API that subscribes to Redis Stream events and pushes new executions + failures to connected dashboard clients in real-time. Use FastAPI's native WebSocket support.

```python
# services/dashboard-api/app/websocket.py
import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


async def stream_updates(redis_url: str):
    """Background task that reads from Redis Stream and broadcasts to WebSocket clients."""
    redis = aioredis.from_url(redis_url, decode_responses=True)
    last_id = "$"

    while True:
        try:
            messages = await redis.xread(
                streams={"executions.stored": last_id},
                count=10,
                block=5000,
            )
            if messages:
                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id
                        await manager.broadcast({
                            "type": "execution.new",
                            "data": json.loads(data.get("data", "{}")),
                        })
        except Exception:
            await asyncio.sleep(1)
```

**Step 2: Test WebSocket connection**

**Step 3: Run tests**

Run: `pytest services/dashboard-api/tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add services/dashboard-api/
git commit -m "feat(dashboard-api): add WebSocket for real-time dashboard updates"
```

---

## Task 13: CI/CD — GitHub Actions Pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Create CI pipeline**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  sdk-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install SDK
        run: pip install -e "sdk/python[dev]"
      - name: Run SDK tests
        run: pytest sdk/python/tests/ -v --tb=short

  service-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [shared, ingestion-api, storage-worker, dashboard-api]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install shared models
        run: pip install -e services/shared
      - name: Install service
        run: pip install -e "services/${{ matrix.service }}[dev]"
      - name: Run tests
        run: pytest services/${{ matrix.service }}/tests/ -v --tb=short

  dashboard-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install dependencies
        working-directory: services/dashboard
        run: npm ci
      - name: Build
        working-directory: services/dashboard
        run: npm run build

  docker-build:
    runs-on: ubuntu-latest
    needs: [sdk-tests, service-tests, dashboard-build]
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker images
        run: |
          docker build -f services/ingestion-api/Dockerfile -t agentguard-ingestion-api .
          docker build -f services/storage-worker/Dockerfile -t agentguard-storage-worker .
          docker build -f services/dashboard-api/Dockerfile -t agentguard-dashboard-api .
          docker build -f services/dashboard/Dockerfile -t agentguard-dashboard services/dashboard/
```

**Step 2: Commit**

```bash
git add .github/
git commit -m "ci: add GitHub Actions pipeline for tests, build, and Docker"
```

---

## Summary

| Task | Component | What it delivers |
|---|---|---|
| 1 | SDK Models + Config | Core data types, threshold configuration |
| 2 | SDK Transport | Async buffer + HTTP client for telemetry |
| 3 | SDK Guard Client | Decorator, context manager, explicit wrap patterns |
| 4 | Shared Models | Common Pydantic models for all backend services |
| 5 | Infrastructure | Docker Compose with TimescaleDB, Redis, MinIO |
| 6 | Database Migrations | PostgreSQL schema with hypertables + continuous aggregates |
| 7 | Ingestion API | FastAPI service accepting single + batch events |
| 8 | Storage Worker | Redis consumer persisting to S3 + PostgreSQL |
| 9 | Dashboard | React SPA with fleet health, traces, failures views |
| 10 | Dashboard API | Backend endpoints for dashboard queries |
| 11 | Integration | Full-stack docker-compose + end-to-end tests |
| 12 | WebSocket | Real-time dashboard updates |
| 13 | CI/CD | GitHub Actions pipeline |

**Dependencies:** Tasks 1-3 (SDK) and Tasks 4-6 (Backend foundation) can run in parallel. Tasks 7-8 depend on 4-6. Task 9-10 can start after 4. Task 11 requires all services. Task 12-13 can run any time after their dependencies.
