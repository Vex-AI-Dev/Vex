# Sessions Page Design

## Goal

Add a dedicated Sessions page to the Vex dashboard, providing a session-centric view of multi-turn conversations — complementing the existing agent-centric view on the Agents page.

## Architecture

Two routes derived from existing `executions` table (no new DB tables):

- **`/home/[account]/sessions`** — Paginated list of all sessions for the org
- **`/home/[account]/sessions/[sessionId]`** — Detail page with turn-by-turn timeline

Navigation: Added to the Monitoring section in the sidebar, between Agents and Failures.

## Sessions List Page

### Table Columns

| Column | Source |
|--------|--------|
| Session ID | `session_id` (first 8 chars) |
| Agent | `agent_id` joined with `agents.name` |
| Turns | `COUNT(*)` |
| Avg Confidence | `AVG(confidence)` |
| Status | Derived: all pass = healthy, any flag = degraded, any block = risky |
| Duration | `MAX(timestamp) - MIN(timestamp)` |
| Last Active | `MAX(timestamp)` |

### Filters (search params)

- **Agent** — dropdown populated from org's agents
- **Date range** — last 24h / 7d / 30d / all
- **Status** — all / healthy / degraded / risky

### Query

```sql
SELECT
  e.session_id,
  e.agent_id,
  a.name AS agent_name,
  COUNT(*) AS turn_count,
  AVG(e.confidence) AS avg_confidence,
  MIN(e.timestamp) AS first_timestamp,
  MAX(e.timestamp) AS last_timestamp,
  BOOL_OR(e.action = 'block') AS has_block,
  BOOL_OR(e.action = 'flag') AS has_flag
FROM executions e
JOIN agents a ON e.agent_id = a.agent_id AND e.org_id = a.org_id
WHERE e.org_id = $1
  AND e.session_id IS NOT NULL
  -- dynamic filters appended here
GROUP BY e.session_id, e.agent_id, a.name
ORDER BY MAX(e.timestamp) DESC
LIMIT 50
```

Status derived from: `has_block` → risky, `has_flag` → degraded, else → healthy.

### Row Click

Navigates to `/home/[account]/sessions/[sessionId]`.

## Session Detail Page

### Header

Session ID, agent name (linked to agent detail), total turns, overall avg confidence, duration, total tokens, total cost.

### Turn Timeline

Vertical list of all executions ordered by `sequence_number ASC`:

Each turn card shows:
- Sequence number
- Task description
- Confidence badge (color-coded)
- Action badge (pass/flag/block)
- Latency
- Timestamp
- Corrected indicator (if applicable)

Expandable: click a turn to see full check results (schema validation, hallucination, drift, coherence scores) and correction details.

### Query

```sql
-- Summary
SELECT
  e.session_id,
  e.agent_id,
  a.name AS agent_name,
  COUNT(*) AS turn_count,
  AVG(e.confidence) AS avg_confidence,
  MIN(e.timestamp) AS first_timestamp,
  MAX(e.timestamp) AS last_timestamp,
  SUM(e.token_count) AS total_tokens,
  SUM(e.cost_estimate) AS total_cost
FROM executions e
JOIN agents a ON e.agent_id = a.agent_id AND e.org_id = a.org_id
WHERE e.session_id = $1 AND e.org_id = $2
GROUP BY e.session_id, e.agent_id, a.name

-- Turns
SELECT
  e.execution_id,
  e.sequence_number,
  e.task,
  e.confidence,
  e.action,
  e.latency_ms,
  e.timestamp,
  e.corrected,
  e.token_count,
  e.cost_estimate,
  e.metadata
FROM executions e
WHERE e.session_id = $1 AND e.org_id = $2
ORDER BY e.sequence_number ASC
```

## Tech Stack

- Server components (Next.js App Router) for data loading
- Client components for filters and interactive timeline
- `@kit/ui` components (Card, Badge, Tabs, Table)
- Existing `getAgentGuardPool()` for DB queries
- React `cache()` for loader memoization
- Search params for filter state (same pattern as alerts page)

## Files to Create/Modify

- `config/paths.config.ts` — add `accountSessions`, `accountSessionDetail`
- `config/team-account-navigation.config.tsx` — add Sessions to Monitoring
- `public/locales/en/agentguard.json` — add session i18n keys
- `lib/agentguard/types.ts` — add `SessionListRow`, `SessionTurn` types
- `app/home/[account]/sessions/page.tsx` — list page
- `app/home/[account]/sessions/_lib/server/sessions.loader.ts` — queries
- `app/home/[account]/sessions/_components/sessions-table.tsx` — filterable table
- `app/home/[account]/sessions/[sessionId]/page.tsx` — detail page
- `app/home/[account]/sessions/[sessionId]/_components/session-timeline.tsx` — turn timeline
