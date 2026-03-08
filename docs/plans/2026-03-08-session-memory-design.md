# Vex Session Memory — Design Document

**Date:** 2026-03-08
**Status:** Approved

## Problem

Vex's verification checks are stateless — each turn is verified in isolation. If an agent contradicts something it said 3 turns ago, the drift/hallucination checks have no way to detect it unless the SDK sends full conversation history. This leads to undetected drift within sessions.

## Solution

A native memory layer that accumulates verified facts during a session and uses them to catch contradictions, prevent drift, and ground corrections.

## Architecture Overview

```
SDK → sync-gateway → verification-engine → storage-worker
           ↕                  ↕                   ↕
      session-memory     memory_consistency    async fact
      (read via          check (new)           extraction
       pgvector)                               (async-worker)
           ↕
      PostgreSQL + pgvector
      (session_memories table)
```

No new services. Uses existing sync-gateway (read + write summaries), async-worker (fact extraction), and shared modules.

No SDK changes. Memory is fully server-side and transparent.

## Data Model

### Table: `session_memories`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `session_id` | VARCHAR(256) | Links to the session |
| `org_id` | VARCHAR(64) | Tenant isolation |
| `agent_id` | VARCHAR(128) | Which agent |
| `execution_id` | VARCHAR(64) | Which turn created this memory |
| `memory_type` | VARCHAR(32) | `'summary'`, `'fact'`, `'procedural'` |
| `content` | TEXT | The memory text |
| `embedding` | vector(1536) | pgvector embedding for semantic search |
| `confidence` | FLOAT | Verification confidence when captured |
| `sequence_number` | INTEGER | Turn order within session |
| `scope` | VARCHAR(32) | `'session'`, `'agent'`, `'org'` (future-proof) |
| `status` | VARCHAR(16) | `'active'`, `'superseded'`, `'deleted'` |
| `superseded_by` | UUID | Points to the memory that replaced this one |
| `metadata` | JSONB | Source check, extraction model, tags, etc. |
| `created_at` | TIMESTAMPTZ | When written |
| `updated_at` | TIMESTAMPTZ | Last modified |

### Indexes

- `(session_id, org_id, scope, status)` — primary lookup: active memories for a session
- HNSW index on `embedding` via pgvector — semantic similarity search
- `(agent_id, org_id, scope)` — future agent-level memory queries
- `(org_id, scope)` — future org-level memory queries

### Memory Relationships

- **Supersedes:** New fact replaces old one. Old memory gets `status='superseded'`, `superseded_by` points to new memory.
- **Deduplication:** Before inserting, semantic search existing memories. If similarity > 0.92, update the existing memory instead of creating a new one.

### Memory Lifecycle

- `active` — normal state, included in retrieval
- `superseded` — replaced by newer fact, excluded from retrieval but kept for audit
- `deleted` — soft-deleted, excluded from everything

## Memory Pipeline

### Write Path

**Immediate (sync-gateway, after successful verification):**
1. Generate embedding for a compact turn summary via LiteLLM
2. Insert into `session_memories` with `memory_type='summary'`

**Async (async-worker, background):**
1. LLM extracts discrete facts from the verified turn
2. For each fact:
   - Generate embedding via LiteLLM
   - Semantic search existing session memories (similarity > 0.92)
   - If match found: update existing memory, mark old as `superseded`
   - If no match: insert new memory with `memory_type='fact'`

### Read Path (at verification time)

1. Embed current turn's output via LiteLLM (~20ms)
2. pgvector semantic search: top-10 relevant facts where `scope='session'`, `status='active'` (~5ms)
3. Chronological fetch: last 5 turn summaries by `sequence_number`
4. Deduplicate overlapping results
5. Pass combined context to `memory_consistency` check
6. Same retrieved memories available to correction cascade

## Verification Engine Integration

### New Check: `memory_consistency`

Added to the pipeline alongside existing checks. Runs in parallel.

**LLM prompt receives:**
- Current turn's output and task/input
- Retrieved session memories (relevant facts + recent summaries)

**Evaluates:**
- Does the output contradict any established facts?
- Does the output forget critical context from earlier turns?
- Does the output fabricate information that conflicts with session history?

**Returns:** `CheckResult` with score (0.0–1.0), passed boolean, and list of contradictions.

### Updated Composite Weights

| Check | Before | After |
|-------|--------|-------|
| schema | 0.30 | 0.25 |
| drift | 0.25 | 0.20 |
| hallucination | 0.30 | 0.25 |
| coherence | 0.15 | 0.10 |
| memory_consistency | — | 0.20 |

Existing `_rebalance_weights` handles dynamic adjustment when checks are skipped (e.g., first turn with no memories).

### First Turn Behavior

No memories exist yet. `memory_consistency` check is skipped. Weights rebalance across remaining checks. After verification, first memories are written.

### Correction Cascade Integration

When correction runs, semantically relevant session memories are retrieved via pgvector and injected into the correction prompt as grounding context:

```
The following facts have been established and verified in this session:
- User's order number is #45821
- Agent confirmed refund takes 3-5 business days
- User is asking about shipping, not billing

Correct the output to be consistent with these established facts.
```

## Configuration

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MEMORY_ENABLED` | Feature flag, globally applied | `false` |
| `MEMORY_EMBEDDING_MODEL` | LiteLLM model name | `text-embedding-3-small` |

### Behavior

- When `MEMORY_ENABLED=true`, all agents with a `session_id` get memory automatically
- Agents without a `session_id` (one-shot verifications) skip memory
- No per-agent opt-out in v1

## Changes By Service

| Service | Changes |
|---------|---------|
| `services/migrations/` | New migration: `session_memories` table with pgvector extension |
| `services/verification-engine/` | New `memory_consistency` check module, updated pipeline weights |
| `services/sync-gateway/` | Read memories before verification, write turn summary after |
| `services/async-worker/` | Extract facts + generate embeddings after verification |
| `services/shared/` | New `memory.py` module: embedding via LiteLLM, pgvector read/write, semantic search |
| `Dashboard` | Future: session detail panel showing memories timeline |
| `SDK` | No changes |

### New Dependencies

- `pgvector` Python package (SQLAlchemy vector type)
- `litellm` (already in stack)

## Future Expansion

The `scope` column supports `'agent'` and `'org'` level memory with zero schema changes:

- **Agent-level:** Behavioral patterns learned across sessions (e.g., "this agent tends to be verbose on billing questions")
- **Org-level:** Shared knowledge across all agents (e.g., "refund policy changed last week")

These require only new write/read logic, not schema migration.

## Latency Budget

| Step | Time |
|------|------|
| Embedding generation (LiteLLM) | ~20ms |
| pgvector similarity search | ~5ms |
| Memory consistency LLM check | ~500-800ms |
| **Total added (parallelized)** | **~500-800ms** |

The memory consistency check runs in parallel with other LLM-based checks (drift, hallucination, coherence), so effective added latency is near zero — it fits within the existing parallel check window.
