# Tool Usage Analytics Redesign — Design

## Goal

Transform the Tool Usage page from a raw data table into an actionable analytics dashboard that surfaces anomalies, visualizes tool behavior patterns, and enables inline tool policy creation via the existing guardrails system.

## Architecture

The redesign has three layers:

1. **Visual dashboard** — KPI cards, stacked area chart (tool call volume over time), tool-agent risk heatmap, anomaly cards, enriched data table
2. **Anomaly detection** — Server-side comparison of current metrics vs 7-day rolling averages, surfaced as ranked alert cards
3. **Tool policies** — New `tool_policy` guardrail rule type enforced in the verification pipeline, creatable directly from anomaly cards

All data comes from the existing `tool_calls` and `executions` tables plus one new materialized view. Tool policies reuse the existing `guardrails` table and pipeline.

## Page Layout

### 1. KPI Strip (4 cards)

| Card | Source | Notes |
|------|--------|-------|
| Total Tool Calls (7d) | `COUNT(*) FROM tool_calls` | With sparkline trend |
| Unique Tools Active | `COUNT(DISTINCT tool_name)` | |
| Anomalies Detected | Computed in loader | Count with severity color |
| Active Tool Policies | `COUNT(*) FROM guardrails WHERE rule_type = 'tool_policy'` | |

### 2. Charts Row (side by side)

**Tool Call Volume Over Time** — Stacked area chart, 7 days, daily buckets. Each tool is a colored area. Shows volume patterns and spikes.

**Tool Risk Heatmap** — Grid: rows = tools, columns = agents. Cell color intensity = block rate (green 0% → yellow 10% → red 30%+). Instantly shows which tool+agent combinations are problematic. Empty cells = no usage.

### 3. Anomalies Section

Auto-detected anomaly cards, sorted by severity. Each card contains:
- Severity badge (critical / high / medium)
- Description (e.g., "web_search called 47x consecutively by agent-X")
- Affected agent link
- **"Create Guardrail"** button (pre-fills the create dialog)

**Anomaly detection rules:**
- Call count > 2x the 7-day daily average → medium
- Block rate > 20% → high
- Avg duration > 3x the 7-day average → medium
- Tool loop check failure (from check_results where check_type = 'tool_loop') → critical

### 4. Tool Detail Table (enriched)

Existing columns (tool_name, call_count, avg_duration, agents_using, flag_rate, block_rate) plus:
- 7-day sparkline per tool (tiny inline chart)
- Anomaly indicator column (icon if anomaly detected)
- Actions column: dropdown with "Create Guardrail" and "View Executions" (links to failures page filtered by tool)

## Backend

### New Materialized View: `tool_usage_daily`

```sql
CREATE MATERIALIZED VIEW tool_usage_daily AS
SELECT
  date_trunc('day', tc.timestamp) AS bucket,
  tc.org_id,
  tc.tool_name,
  tc.agent_id,
  COUNT(*) AS call_count,
  AVG(tc.duration_ms) AS avg_duration_ms,
  AVG(CASE WHEN e.action = 'flag' THEN 1.0 ELSE 0.0 END) AS flag_rate,
  AVG(CASE WHEN e.action = 'block' THEN 1.0 ELSE 0.0 END) AS block_rate
FROM tool_calls tc
JOIN executions e ON tc.execution_id = e.execution_id
GROUP BY bucket, tc.org_id, tc.tool_name, tc.agent_id;
```

Refreshed on same schedule as other materialized views.

### New Loaders

| Loader | Purpose |
|--------|---------|
| `loadToolUsageKpis(orgId)` | KPI card aggregates |
| `loadToolUsageTimeSeries(orgId)` | Daily tool call volumes for stacked area chart |
| `loadToolRiskMatrix(orgId)` | Tool × agent block rates for heatmap |
| `loadToolAnomalies(orgId)` | Anomaly detection: compare current vs 7-day averages |
| `loadToolUsage(orgId)` | Existing table query (unchanged) |

### Anomaly Detection Logic (in loader)

```
For each tool in the org:
  today_count = call count in last 24h
  avg_7d = average daily call count over last 7 days
  today_block_rate = block rate in last 24h
  today_avg_duration = avg duration in last 24h
  avg_7d_duration = avg duration over last 7 days

  If today_count > 2 * avg_7d → anomaly (medium: "volume spike")
  If today_block_rate > 0.20 → anomaly (high: "high block rate")
  If today_avg_duration > 3 * avg_7d_duration → anomaly (medium: "latency spike")
  If tool_loop check failed for executions using this tool → anomaly (critical: "tool loop detected")
```

## Tool Policy Guardrail

### Schema

Reuses the existing `guardrails` table with:
- `rule_type: 'tool_policy'`
- `condition` JSON:
  - `{ "tool_name": "send_email", "policy": "deny" }` — blocks the tool entirely
  - `{ "tool_name": "web_search", "policy": "allow", "max_calls_per_execution": 10 }` — allows with cap
- `agent_id`: if set, applies to that agent only. If null, org-wide.
- `action`: 'flag' or 'block' (existing field)

### Enforcement

In `engine/guardrails.py`, when evaluating rules:
1. For `rule_type == 'tool_policy'` rules:
   - Extract tool names from the execution's steps (filter `step_type == 'tool_call'`)
   - If `policy == 'deny'`: trigger if the denied tool appears in steps
   - If `policy == 'allow'` with `max_calls_per_execution`: trigger if call count exceeds limit
2. Agent scoping uses existing `agent_id` field on the guardrail row.

### Create from Anomaly Card

Clicking "Create Guardrail" on an anomaly card pre-fills the create guardrail dialog:
- `rule_type: 'tool_policy'`
- `condition: { tool_name: '<from anomaly>', policy: 'deny' }`
- `agent_id`: from the anomaly's agent if agent-specific
- `action: 'block'`

User reviews and confirms. Reuses existing `createGuardrailAction` server action.

## Frontend Components

### New
- `tool-usage-dashboard.tsx` — Client component, orchestrates all sections
- `tool-usage-charts.tsx` — Stacked area chart + risk heatmap
- `tool-anomaly-cards.tsx` — Anomaly cards with create-guardrail action
- `tool-usage-kpis.tsx` — KPI card strip

### Modified
- `tools/page.tsx` — Calls new loaders, passes to dashboard
- `tool-usage-table.tsx` — Add sparkline, anomaly indicator, actions column
- `guardrail.schema.ts` — Add `tool_policy` rule_type validation
- `create-guardrail-dialog.tsx` — Support `tool_policy` type with pre-fill props

## Migration

- `013_add_tool_usage_daily.py` — Creates `tool_usage_daily` materialized view

## Non-Goals

- Tool dependency graph visualization (future)
- Real-time streaming of tool calls (future)
- Per-tool detail page with drill-down (future — link to failures page filtered by tool for now)
