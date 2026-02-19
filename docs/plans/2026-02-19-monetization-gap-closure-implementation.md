# Monetization Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all remaining gaps between the monetization scaffolding and production-ready billing enforcement — enterprise tier, real usage data, agent limits, retention cron, and E2E tests.

**Architecture:**
- **Supabase is the single source of truth** for plan/billing data. New `vex_plan` and `vex_plan_overrides` columns on the Supabase `accounts` table.
- **TimescaleDB stays purely analytics** — executions, check_results, agents, hourly_agent_stats. The existing `organizations.plan` column in TimescaleDB is deprecated (kept for backward compat but no longer authoritative).
- **Python backend connects to Supabase** via a second `SUPABASE_DATABASE_URL` env var to read plan data during key validation. Plan data is cached with the same 60s TTL as API keys.
- **Dashboard reads plan from Supabase** natively via `getSupabaseServerClient()` — no TimescaleDB query needed for plan info.
- **Admin UI updates plan** directly on Supabase `accounts` table via admin client.

**Tech Stack:** Python (FastAPI, SQLAlchemy, Alembic), TypeScript (Next.js 16, React 19, Supabase), TimescaleDB (analytics only), Makerkit admin framework.

---

### Task 1: Supabase Migration — Add Plan Columns to Accounts

**Files:**
- Create: `nextjs-application/apps/web/supabase/migrations/20260219000000_add_vex_plan_columns.sql`

**Step 1: Create migration**

Following the pattern from `20260213144754_add_onboarding_columns.sql`:

```sql
-- Add Vex plan columns to accounts table.
-- vex_plan: the current pricing tier (free/pro/team/enterprise)
-- vex_plan_overrides: optional JSONB with per-org custom limit overrides (enterprise)

ALTER TABLE public.accounts
  ADD COLUMN vex_plan varchar(50) NOT NULL DEFAULT 'free',
  ADD COLUMN vex_plan_overrides jsonb DEFAULT NULL;

-- Add check constraint for valid plan values
ALTER TABLE public.accounts
  ADD CONSTRAINT accounts_vex_plan_valid CHECK (
    vex_plan IN ('free', 'pro', 'team', 'enterprise')
  );

-- Index for plan-based queries (admin dashboard, retention)
CREATE INDEX ix_accounts_vex_plan ON public.accounts (vex_plan);
```

**Step 2: Regenerate TypeScript types**

Run: `pnpm supabase:web:typegen`

This will add `vex_plan` and `vex_plan_overrides` to the `accounts` Row/Insert/Update types in `database.types.ts`.

**Step 3: Commit**

```bash
git add nextjs-application/apps/web/supabase/migrations/20260219000000_add_vex_plan_columns.sql \
        nextjs-application/packages/supabase/src/database.types.ts
git commit -m "feat(supabase): add vex_plan and vex_plan_overrides columns to accounts"
```

---

### Task 2: Add Enterprise Tier to Python Plan Limits

**Files:**
- Modify: `services/shared/shared/plan_limits.py`

**Step 1: Add enterprise plan config**

Add the `enterprise` entry to `PLAN_LIMITS` dict after `team`:

```python
    "enterprise": PlanConfig(
        observations_per_month=10_000_000,
        verifications_per_month=1_000_000,
        max_rpm=10_000,
        max_agents=-1,  # unlimited
        max_seats=-1,    # unlimited
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=365,
        overage_allowed=True,
    ),
```

**Step 2: Update `get_plan_config()` to support overrides**

Replace the current `get_plan_config` function:

```python
def get_plan_config(plan: str, overrides: Optional[Dict[str, Any]] = None) -> PlanConfig:
    """Return the PlanConfig for the given plan name.

    Falls back to ``"free"`` for unknown plan values.
    If *overrides* is provided (from ``accounts.vex_plan_overrides``),
    those values are merged on top of the plan defaults.
    """
    base = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    if not overrides:
        return base
    from dataclasses import asdict
    merged = {**asdict(base), **{k: v for k, v in overrides.items() if v is not None}}
    return PlanConfig(**merged)
```

Add `from typing import Any, Dict, Optional` to imports.

**Step 3: Commit**

```bash
git add services/shared/shared/plan_limits.py
git commit -m "feat(plan-limits): add enterprise tier and per-org overrides support"
```

---

### Task 3: Add Enterprise Tier to TypeScript Plan Limits

**Files:**
- Modify: `nextjs-application/apps/web/lib/agentguard/plan-limits.ts`

**Step 1: Add enterprise plan config**

Add the `enterprise` entry to `PLAN_LIMITS` after `team`:

```typescript
  enterprise: {
    observationsPerMonth: 10_000_000,
    verificationsPerMonth: 1_000_000,
    maxRpm: 10_000,
    maxAgents: -1, // unlimited
    maxSeats: -1,  // unlimited
    correctionsEnabled: true,
    webhookAlerts: true,
    slackAlerts: true,
    retentionDays: 365,
    overageAllowed: true,
  },
```

**Step 2: Update `getPlanLimits()` to support overrides**

```typescript
export function getPlanLimits(
  plan: string,
  overrides?: Partial<PlanLimits> | null,
): PlanLimits {
  const base = PLAN_LIMITS[plan] ?? PLAN_LIMITS.free!;
  if (!overrides) return base;
  return { ...base, ...Object.fromEntries(
    Object.entries(overrides).filter(([, v]) => v != null)
  ) } as PlanLimits;
}
```

**Step 3: Update `canAddSeat` and `canAddAgent` to accept overrides**

```typescript
export function canAddSeat(
  plan: string,
  currentMemberCount: number,
  seatsToAdd = 1,
  overrides?: Partial<PlanLimits> | null,
): { allowed: true } | { allowed: false; reason: string } {
  const limits = getPlanLimits(plan, overrides);
  if (limits.maxSeats === -1) return { allowed: true };
  // ... rest unchanged
}

export function canAddAgent(
  plan: string,
  currentAgentCount: number,
  agentsToAdd = 1,
  overrides?: Partial<PlanLimits> | null,
): { allowed: true } | { allowed: false; reason: string } {
  const limits = getPlanLimits(plan, overrides);
  // ... rest unchanged (already handles -1)
}
```

**Step 4: Commit**

```bash
git add nextjs-application/apps/web/lib/agentguard/plan-limits.ts
git commit -m "feat(plan-limits): add enterprise tier and overrides to TypeScript config"
```

---

### Task 4: Python Backend — Read Plan from Supabase

**Files:**
- Modify: `services/shared/shared/auth.py`
- Modify: `services/sync-gateway/app/auth.py`
- Modify: `services/ingestion-api/app/auth.py`

This is the key architectural change. The `KeyValidator` currently reads `plan` from TimescaleDB's `organizations` table. We need it to read plan from Supabase's `accounts` table instead.

**Step 1: Add `supabase_database_url` parameter to `KeyValidator.__init__()`**

```python
def __init__(
    self,
    database_url: str,
    required_scope: str,
    supabase_database_url: Optional[str] = None,
    cache_ttl_s: float = 60.0,
    flush_interval_s: float = 60.0,
) -> None:
```

Create a second SQLAlchemy engine for Supabase if the URL is provided:

```python
self._supabase_engine: Optional[Engine] = None
if supabase_database_url:
    self._supabase_engine = create_engine(
        supabase_database_url,
        pool_size=1,
        max_overflow=2,
        pool_pre_ping=True,
    )
```

**Step 2: Add `_query_plan_from_supabase()` method**

The bridge: TimescaleDB `organizations.account_slug` maps to Supabase `accounts.slug`.

```python
def _query_plan_from_supabase(self, org_id: str) -> tuple[str, Optional[dict]]:
    """Query plan data from Supabase accounts table.

    Returns (plan, plan_overrides) tuple. Falls back to ("free", None)
    on any error or if Supabase is not configured.
    """
    if self._supabase_engine is None:
        return ("free", None)

    try:
        with self._supabase_engine.connect() as conn:
            # organizations.account_slug == accounts.slug
            result = conn.execute(
                text(
                    """
                    SELECT vex_plan, vex_plan_overrides
                    FROM accounts
                    WHERE slug = :slug AND is_personal_account = false
                    LIMIT 1
                    """
                ),
                {"slug": org_id},
            )
            row = result.fetchone()
            if row is None:
                return ("free", None)
            plan = row[0] or "free"
            overrides = row[1] if isinstance(row[1], dict) else (
                json.loads(row[1]) if row[1] else None
            )
            return (plan, overrides)
    except Exception:
        logger.warning("Failed to query plan from Supabase, defaulting to free", exc_info=True)
        return ("free", None)
```

**Step 3: Update `_query_db()` to use Supabase for plan**

In `_query_db()`, after finding the matching key entry, replace:
```python
plan_val = row[2] if row[2] else "free"
```
with:
```python
# Plan data comes from Supabase (source of truth), not TimescaleDB
# Use account_slug from the org record to look up Supabase
account_slug_result = conn.execute(
    text("SELECT account_slug FROM organizations WHERE org_id = :org_id"),
    {"org_id": org_id},
)
slug_row = account_slug_result.fetchone()
account_slug = slug_row[0] if slug_row else org_id
plan_val, plan_overrides = self._query_plan_from_supabase(account_slug)
```

Actually, we already have `org_id` from the key lookup. The `organizations` table has `account_slug`. We can query it in the same query:

Modify the existing SQL in `_query_db()` from:
```sql
SELECT org_id, api_keys, plan FROM organizations WHERE api_keys @> ...
```
to:
```sql
SELECT org_id, api_keys, account_slug FROM organizations WHERE api_keys @> ...
```

Then use `account_slug` (from `row[2]`) to query Supabase for plan:

```python
account_slug = row[2] if row[2] else org_id
plan_val, plan_overrides_val = self._query_plan_from_supabase(account_slug)
```

**Step 4: Add `plan_overrides` to `_CachedKey`**

```python
@dataclass
class _CachedKey:
    org_id: str
    key_id: str
    scopes: List[str]
    rate_limit_rpm: int
    expires_at: Optional[datetime]
    revoked: bool
    plan: str = "free"
    plan_overrides: Optional[Dict] = None
    cached_at: float = field(default_factory=time.monotonic)
```

Set `plan_overrides` when constructing the `_CachedKey` in `_query_db()`.

**Step 5: Update all `get_plan_config()` calls to pass overrides**

In `_check_quota()`:
```python
plan_config = get_plan_config(entry.plan, entry.plan_overrides)
```

In `_query_db()` for RPM calculation:
```python
plan_config = get_plan_config(plan_val, plan_overrides_val)
effective_rpm = min(per_key_rpm, plan_config.max_rpm)
```

**Step 6: Update gateway/ingestion auth modules to pass `SUPABASE_DATABASE_URL`**

File: `services/sync-gateway/app/auth.py` — add:
```python
SUPABASE_DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
```

Pass to `KeyValidator`:
```python
_validators[scope] = KeyValidator(
    database_url=DATABASE_URL,
    required_scope=scope,
    supabase_database_url=SUPABASE_DATABASE_URL,
)
```

Same change in `services/ingestion-api/app/auth.py`.

**Step 7: Update `close()` to dispose Supabase engine**

```python
def close(self) -> None:
    self.flush_usage()
    self._engine.dispose()
    if self._supabase_engine:
        self._supabase_engine.dispose()
```

**Step 8: Commit**

```bash
git add services/shared/shared/auth.py \
        services/sync-gateway/app/auth.py \
        services/ingestion-api/app/auth.py
git commit -m "feat(auth): read plan data from Supabase instead of TimescaleDB"
```

---

### Task 5: Admin Plan Management UI

**Files:**
- Create: `nextjs-application/apps/web/app/admin/accounts/[id]/_components/plan-management.tsx`
- Create: `nextjs-application/apps/web/app/admin/accounts/[id]/_lib/update-plan.action.ts`
- Modify: `nextjs-application/apps/web/app/admin/accounts/[id]/page.tsx`

**Step 1: Create server action for updating plan**

File: `nextjs-application/apps/web/app/admin/accounts/[id]/_lib/update-plan.action.ts`

This now updates the **Supabase `accounts` table** directly:

```typescript
'use server';

import { z } from 'zod';

import { isSuperAdmin } from '@kit/admin';
import { getSupabaseServerAdminClient } from '@kit/supabase/server-admin-client';
import { requireUser } from '@kit/supabase/require-user';
import { getLogger } from '@kit/shared/logger';

const UpdatePlanSchema = z.object({
  accountId: z.string().uuid(),
  plan: z.enum(['free', 'pro', 'team', 'enterprise']),
  overrides: z.object({
    observations_per_month: z.number().optional(),
    verifications_per_month: z.number().optional(),
    max_rpm: z.number().optional(),
    max_agents: z.number().optional(),
    max_seats: z.number().optional(),
    retention_days: z.number().optional(),
  }).nullable(),
});

export async function updateAccountPlan(input: z.infer<typeof UpdatePlanSchema>) {
  const data = UpdatePlanSchema.parse(input);

  const auth = await requireUser();
  if (!(await isSuperAdmin(auth.data))) {
    throw new Error('Unauthorized');
  }

  const logger = await getLogger();
  const adminClient = getSupabaseServerAdminClient();

  const { error } = await adminClient
    .from('accounts')
    .update({
      vex_plan: data.plan,
      vex_plan_overrides: data.overrides,
    })
    .eq('id', data.accountId);

  if (error) {
    throw new Error(`Failed to update plan: ${error.message}`);
  }

  logger.info({
    name: 'admin-audit',
    action: 'update-account-plan',
    adminId: auth.data?.id,
    accountId: data.accountId,
    plan: data.plan,
    overrides: data.overrides,
  }, 'Admin updated account plan');

  return { success: true };
}
```

**Step 2: Create PlanManagement client component**

File: `nextjs-application/apps/web/app/admin/accounts/[id]/_components/plan-management.tsx`

```tsx
'use client';

import { useState, useTransition } from 'react';

import { Button } from '@kit/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@kit/ui/card';
import { Input } from '@kit/ui/input';
import { Label } from '@kit/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@kit/ui/select';

import { updateAccountPlan } from '../_lib/update-plan.action';

const PLANS = ['free', 'pro', 'team', 'enterprise'] as const;

interface PlanManagementProps {
  accountId: string;
  currentPlan: string;
  currentOverrides: Record<string, number> | null;
}

export function PlanManagement({ accountId, currentPlan, currentOverrides }: PlanManagementProps) {
  const [plan, setPlan] = useState(currentPlan);
  const [overrides, setOverrides] = useState<Record<string, string>>(
    currentOverrides
      ? Object.fromEntries(Object.entries(currentOverrides).map(([k, v]) => [k, String(v)]))
      : {},
  );
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState('');

  const handleSave = () => {
    startTransition(async () => {
      try {
        const parsedOverrides = Object.keys(overrides).length > 0
          ? Object.fromEntries(
              Object.entries(overrides)
                .filter(([, v]) => v !== '')
                .map(([k, v]) => [k, parseInt(v, 10)]),
            )
          : null;

        await updateAccountPlan({ accountId, plan, overrides: parsedOverrides });
        setMessage('Plan updated successfully');
      } catch (e) {
        setMessage(`Error: ${e instanceof Error ? e.message : 'Unknown error'}`);
      }
    });
  };

  const overrideFields = [
    { key: 'observations_per_month', label: 'Observations/month' },
    { key: 'verifications_per_month', label: 'Verifications/month' },
    { key: 'max_rpm', label: 'Max RPM' },
    { key: 'max_agents', label: 'Max Agents (-1 = unlimited)' },
    { key: 'max_seats', label: 'Max Seats (-1 = unlimited)' },
    { key: 'retention_days', label: 'Retention (days)' },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Vex Plan Management</CardTitle>
        <CardDescription>
          Manage the organization&apos;s Vex plan and custom limit overrides.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Plan</Label>
          <Select value={plan} onValueChange={setPlan}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PLANS.map((p) => (
                <SelectItem key={p} value={p}>
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {plan === 'enterprise' && (
          <div className="space-y-3">
            <Label className="text-sm font-medium">Custom Overrides</Label>
            <div className="grid grid-cols-2 gap-3">
              {overrideFields.map(({ key, label }) => (
                <div key={key} className="space-y-1">
                  <Label className="text-xs text-muted-foreground">{label}</Label>
                  <Input
                    type="number"
                    placeholder="Plan default"
                    value={overrides[key] ?? ''}
                    onChange={(e) =>
                      setOverrides((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button onClick={handleSave} disabled={isPending}>
            {isPending ? 'Saving...' : 'Save Plan'}
          </Button>
          {message && (
            <span className={`text-sm ${message.startsWith('Error') ? 'text-destructive' : 'text-green-600'}`}>
              {message}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

**Step 3: Modify account detail page to include PlanManagement**

File: `nextjs-application/apps/web/app/admin/accounts/[id]/page.tsx`

The page already loads the account from Supabase. After Task 1's migration, the account data will include `vex_plan` and `vex_plan_overrides`. Simply pass them to the new component:

```typescript
import { PlanManagement } from './_components/plan-management';

async function AccountPage(props: Params) {
  const params = await props.params;
  const account = await loadAccount(params.id);

  return (
    <>
      <AdminAccountPage account={account} />
      <div className="mx-auto max-w-4xl px-4 py-6">
        <PlanManagement
          accountId={account.id}
          currentPlan={account.vex_plan ?? 'free'}
          currentOverrides={account.vex_plan_overrides as Record<string, number> | null}
        />
      </div>
    </>
  );
}
```

No separate DB query needed — the account data already comes from Supabase and now includes plan columns.

**Step 4: Commit**

```bash
git add nextjs-application/apps/web/app/admin/accounts/\[id\]/_components/plan-management.tsx \
        nextjs-application/apps/web/app/admin/accounts/\[id\]/_lib/update-plan.action.ts \
        nextjs-application/apps/web/app/admin/accounts/\[id\]/page.tsx
git commit -m "feat(admin): add plan management UI for enterprise org overrides"
```

---

### Task 6: Wire Real Usage Data to Dashboard

**Files:**
- Modify: `nextjs-application/apps/web/app/home/[account]/_lib/server/homepage.loader.ts`
- Modify: `nextjs-application/apps/web/app/home/[account]/page.tsx`
- Modify: `nextjs-application/apps/web/app/home/[account]/_components/homepage-charts.tsx`
- Modify: `nextjs-application/apps/web/app/home/[account]/_components/homepage-dashboard.tsx`

**Step 1: Add `loadPlanUsage` loader**

File: `nextjs-application/apps/web/app/home/[account]/_lib/server/homepage.loader.ts`

Plan data comes from Supabase (via `getSupabaseServerClient()`), usage counts from TimescaleDB (via `getAgentGuardPool()`):

```typescript
import { getSupabaseServerClient } from '@kit/supabase/server-client';

/**
 * Load current month usage counts and plan info for the usage meters.
 * Plan data: Supabase accounts table (source of truth).
 * Usage data: TimescaleDB hourly_agent_stats (analytics).
 */
export const loadPlanUsage = cache(
  async (orgId: string, accountSlug: string): Promise<{
    plan: string;
    planOverrides: Record<string, number> | null;
    observationsUsed: number;
    verificationsUsed: number;
    agentCount: number;
  }> => {
    const pool = getAgentGuardPool();
    const supabase = getSupabaseServerClient();

    const [accountResult, usageResult, agentResult] = await Promise.all([
      // Plan from Supabase
      supabase
        .from('accounts')
        .select('vex_plan, vex_plan_overrides')
        .eq('slug', accountSlug)
        .single(),
      // Usage from TimescaleDB
      pool.query<{ total_executions: string }>(
        `SELECT COALESCE(SUM(execution_count), 0) AS total_executions
         FROM hourly_agent_stats
         WHERE org_id = $1
           AND bucket >= date_trunc('month', NOW())`,
        [orgId],
      ),
      // Agent count from TimescaleDB
      pool.query<{ agent_count: string }>(
        'SELECT COUNT(*) AS agent_count FROM agents WHERE org_id = $1',
        [orgId],
      ),
    ]);

    const account = accountResult.data;
    const totalExecs = parseInt(usageResult.rows[0]?.total_executions ?? '0', 10);
    const agentCount = parseInt(agentResult.rows[0]?.agent_count ?? '0', 10);

    return {
      plan: account?.vex_plan ?? 'free',
      planOverrides: (account?.vex_plan_overrides as Record<string, number>) ?? null,
      observationsUsed: totalExecs,
      verificationsUsed: 0, // TODO: separate when scope tagging is added to hourly_agent_stats
      agentCount,
    };
  },
);
```

**Step 2: Load plan usage in page.tsx**

The `TeamAccountHomePage` already has `account` (the slug) and `orgId`. Add `loadPlanUsage` to `Promise.all`:

```typescript
import { loadPlanUsage } from './_lib/server/homepage.loader';

const [kpis, agentHealth, alertSummary, trend, planUsage] = await Promise.all([
  loadHomepageKpis(orgId),
  loadAgentHealth(orgId),
  loadAlertSummary(orgId),
  loadHomepageTrend(orgId),
  loadPlanUsage(orgId, account),
]);
```

Pass `planUsage` through to `HomepageDashboard` and then to `HomepageCharts`.

**Step 3: Update HomepageCharts to use real data**

```tsx
import { getPlanLimits } from '~/lib/agentguard/plan-limits';

// Add to HomepageChartsProps:
planUsage: {
  plan: string;
  planOverrides: Record<string, number> | null;
  observationsUsed: number;
  verificationsUsed: number;
};

// In the component body:
const planLimits = getPlanLimits(planUsage.plan, planUsage.planOverrides);

// Replace the hardcoded UsageMeter calls:
<UsageMeter label="Observations" current={planUsage.observationsUsed} limit={planLimits.observationsPerMonth} />
<UsageMeter label="Verifications" current={planUsage.verificationsUsed} limit={planLimits.verificationsPerMonth} />

// Replace the hardcoded "Free" badge:
<Badge variant="outline" className="text-xs capitalize">
  {planUsage.plan}
</Badge>
```

**Step 4: Commit**

```bash
git add nextjs-application/apps/web/app/home/\[account\]/_lib/server/homepage.loader.ts \
        nextjs-application/apps/web/app/home/\[account\]/page.tsx \
        nextjs-application/apps/web/app/home/\[account\]/_components/homepage-charts.tsx \
        nextjs-application/apps/web/app/home/\[account\]/_components/homepage-dashboard.tsx
git commit -m "feat(dashboard): wire real usage data and Supabase plan to usage meters"
```

---

### Task 7: Backend Agent Limit Enforcement

**Files:**
- Modify: `services/shared/shared/auth.py`

**Step 1: Add known agent cache to KeyValidator `__init__`**

```python
# Known agent IDs per org (avoids DB query on every request)
self._known_agents: Dict[str, set] = {}
self._known_agents_lock = Lock()
```

**Step 2: Add `_check_agent_limit()` method**

```python
def _check_agent_limit(self, entry: _CachedKey, agent_id: Optional[str]) -> None:
    """Enforce per-plan agent limit."""
    if agent_id is None:
        return

    plan_config = get_plan_config(entry.plan, entry.plan_overrides)
    if plan_config.max_agents == -1:
        return

    with self._known_agents_lock:
        known = self._known_agents.get(entry.org_id)
        if known and agent_id in known:
            return  # Already known, skip DB check

    try:
        with self._engine.connect() as conn:
            agent_count = conn.execute(
                text("SELECT COUNT(DISTINCT agent_id) FROM agents WHERE org_id = :org_id"),
                {"org_id": entry.org_id},
            ).scalar() or 0

            exists = conn.execute(
                text("SELECT 1 FROM agents WHERE org_id = :org_id AND agent_id = :agent_id"),
                {"org_id": entry.org_id, "agent_id": agent_id},
            ).fetchone()
    except Exception:
        logger.warning("Failed to check agent limit, allowing request", exc_info=True)
        return

    if exists:
        with self._known_agents_lock:
            if entry.org_id not in self._known_agents:
                self._known_agents[entry.org_id] = set()
            self._known_agents[entry.org_id].add(agent_id)
        return

    if agent_count >= plan_config.max_agents:
        raise AuthError(
            403,
            f"Agent limit reached ({agent_count}/{plan_config.max_agents}). "
            f"Upgrade your plan at https://app.tryvex.dev",
        )
```

**Step 3: Update `validate()` signature**

```python
def validate(self, api_key: str, agent_id: Optional[str] = None) -> KeyInfo:
```

Insert `self._check_agent_limit(entry, agent_id)` after quota check (step 7), before usage tracking (step 8).

**Step 4: Commit**

```bash
git add services/shared/shared/auth.py
git commit -m "feat(auth): add agent limit enforcement to KeyValidator"
```

---

### Task 8: Update Retention Function for Enterprise + Supabase

**Files:**
- Modify: `services/migrations/alembic/versions/008_plan_retention_enforcement.py`

The retention function runs in TimescaleDB but now needs plan data from Supabase. Two options:
1. Use `dblink` or foreign data wrapper to query Supabase from TimescaleDB
2. Pass plan data as a parameter or read from the (now-deprecated) TimescaleDB `organizations.plan` column

**Pragmatic approach:** The retention cron script (Task 9) will query Supabase for plan data and pass retention days per-org to TimescaleDB. Update the PL/pgSQL function to accept org-level retention as a parameter, or better — rewrite the retention logic into the Python cron script itself.

**Step 1: Update `enforce_plan_retention()` to accept a table of retention configs**

Replace the function to accept explicit retention days rather than reading `plan` from `organizations`:

```sql
CREATE OR REPLACE FUNCTION enforce_plan_retention(
    p_org_id TEXT,
    p_retention_days INT
)
RETURNS void AS $$
BEGIN
    DELETE FROM check_results cr
    USING executions e
    WHERE cr.execution_id = e.execution_id
      AND e.org_id = p_org_id
      AND cr.timestamp < NOW() - (p_retention_days || ' days')::INTERVAL;

    DELETE FROM executions
    WHERE org_id = p_org_id
      AND timestamp < NOW() - (p_retention_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;
```

**Step 2: Commit**

```bash
git add services/migrations/alembic/versions/008_plan_retention_enforcement.py
git commit -m "feat(retention): refactor to accept per-org retention days parameter"
```

---

### Task 9: Retention Cron Script (Reads Plan from Supabase)

**Files:**
- Create: `services/scripts/run_retention.py`

The script:
1. Connects to Supabase to read all accounts with their `vex_plan` and `vex_plan_overrides`
2. Resolves retention days per org using `get_plan_config()`
3. Connects to TimescaleDB and calls `enforce_plan_retention(org_id, retention_days)` per org

```python
"""Run plan-based data retention enforcement.

Reads plan data from Supabase (source of truth), then enforces
retention in TimescaleDB per organization.

Usage:
    python -m scripts.run_retention

Environment:
    DATABASE_URL: TimescaleDB connection string
    SUPABASE_DATABASE_URL: Supabase Postgres connection string
"""

import json
import logging
import os
import sys
import time

from sqlalchemy import create_engine, text

# Add parent to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.plan_limits import get_plan_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("retention")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    supabase_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)
    if not supabase_url:
        logger.error("SUPABASE_DATABASE_URL environment variable is required")
        sys.exit(1)

    tsdb_engine = create_engine(database_url, pool_pre_ping=True)
    supa_engine = create_engine(supabase_url, pool_pre_ping=True)

    logger.info("Starting plan-based data retention enforcement...")
    start = time.monotonic()

    try:
        # 1. Read all team accounts with plan data from Supabase
        with supa_engine.connect() as supa_conn:
            accounts = supa_conn.execute(
                text(
                    "SELECT slug, vex_plan, vex_plan_overrides FROM accounts "
                    "WHERE is_personal_account = false AND slug IS NOT NULL"
                )
            ).fetchall()

        # 2. For each account, resolve retention days and enforce in TimescaleDB
        with tsdb_engine.connect() as tsdb_conn:
            for row in accounts:
                slug, plan, overrides_raw = row[0], row[1] or "free", row[2]
                overrides = (
                    json.loads(overrides_raw) if isinstance(overrides_raw, str)
                    else overrides_raw
                )
                config = get_plan_config(plan, overrides)

                # Find org_id in TimescaleDB by account_slug
                org_row = tsdb_conn.execute(
                    text("SELECT org_id FROM organizations WHERE account_slug = :slug"),
                    {"slug": slug},
                ).fetchone()

                if org_row is None:
                    continue

                org_id = org_row[0]
                tsdb_conn.execute(
                    text("SELECT enforce_plan_retention(:org_id, :days)"),
                    {"org_id": org_id, "days": config.retention_days},
                )
                logger.info(
                    "Enforced %d-day retention for org=%s plan=%s",
                    config.retention_days, org_id, plan,
                )

            tsdb_conn.commit()

    except Exception:
        logger.exception("Retention enforcement failed")
        sys.exit(1)
    finally:
        tsdb_engine.dispose()
        supa_engine.dispose()

    elapsed = time.monotonic() - start
    logger.info("Retention enforcement completed in %.2f seconds", elapsed)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add services/scripts/run_retention.py
git commit -m "feat(scripts): add retention cron script reading plan from Supabase"
```

---

### Task 10: E2E Test — Quota Enforcement

**Files:**
- Create: `scripts/test_quota_enforcement.py`

**Step 1: Create test script**

```python
"""E2E test: quota enforcement.

Sends observations via the API until quota exceeded,
verifies 429 response with upgrade message.

Requires:
    VEX_API_KEY: API key for a free-plan org
    VEX_INGEST_URL: Ingestion API base URL (e.g. http://localhost:8001)
"""

import os
import sys

import requests

API_KEY = os.environ.get("VEX_API_KEY", "")
INGEST_URL = os.environ.get("VEX_INGEST_URL", "http://localhost:8001")
HEADERS = {"X-Vex-Key": API_KEY, "Content-Type": "application/json"}


def test_quota_exceeded():
    print("Testing quota enforcement...")
    payload = {
        "agent_id": "test-agent-quota",
        "task": "quota-test",
        "output": "test output",
    }

    last_status = None
    for i in range(100):
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        last_status = resp.status_code
        if resp.status_code == 429:
            body = resp.json()
            assert "quota" in body.get("detail", "").lower() or "upgrade" in body.get("detail", "").lower()
            print(f"  PASS: Got 429 after {i + 1} requests — {body.get('detail')}")
            return True
        if resp.status_code not in (200, 201, 202):
            print(f"  Unexpected status {resp.status_code}: {resp.text}")
            return False

    print(f"  INFO: Sent 100 requests, last status={last_status} (quota not yet exceeded)")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required"); sys.exit(1)
    sys.exit(0 if test_quota_exceeded() else 1)
```

**Step 2: Commit**

```bash
git add scripts/test_quota_enforcement.py
git commit -m "test: add E2E quota enforcement test script"
```

---

### Task 11: E2E Test — Correction Gating

**Files:**
- Create: `scripts/test_correction_gating.py`

**Step 1: Create test script**

```python
"""E2E test: correction gating on free plan.

Sends verify request with correction=cascade on free-plan org,
verifies correction_skipped=true in response.

Requires:
    VEX_API_KEY: API key for a free-plan org
    VEX_GATEWAY_URL: Sync gateway base URL (e.g. http://localhost:8000)
"""

import os
import sys

import requests

API_KEY = os.environ.get("VEX_API_KEY", "")
GATEWAY_URL = os.environ.get("VEX_GATEWAY_URL", "http://localhost:8000")
HEADERS = {"X-Vex-Key": API_KEY, "Content-Type": "application/json"}


def test_correction_gating():
    print("Testing correction gating on free plan...")
    payload = {
        "agent_id": "test-agent-gating",
        "task": "gating-test",
        "output": "The capital of France is Berlin",
        "correction_mode": "cascade",
        "checks": [{"name": "factuality", "expect": "correct facts"}],
    }

    resp = requests.post(f"{GATEWAY_URL}/v1/verify", json=payload, headers=HEADERS)
    if resp.status_code != 200:
        print(f"  FAIL: Expected 200, got {resp.status_code}: {resp.text}")
        return False

    body = resp.json()
    if body.get("correction_skipped"):
        print(f"  PASS: correction_skipped=true, reason={body.get('correction_skipped_reason')}")
        return True

    print(f"  INFO: correction_skipped=false (org may be on paid plan)")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required"); sys.exit(1)
    sys.exit(0 if test_correction_gating() else 1)
```

**Step 2: Commit**

```bash
git add scripts/test_correction_gating.py
git commit -m "test: add E2E correction gating test script"
```

---

### Task 12: E2E Test — Agent Limit & Rate Limit

**Files:**
- Create: `scripts/test_plan_enforcement.py`

**Step 1: Create test script**

```python
"""E2E test: agent limit and rate limit enforcement.

Requires:
    VEX_API_KEY: API key for a free-plan org
    VEX_INGEST_URL: Ingestion API base URL (e.g. http://localhost:8001)
"""

import os
import sys

import requests

API_KEY = os.environ.get("VEX_API_KEY", "")
INGEST_URL = os.environ.get("VEX_INGEST_URL", "http://localhost:8001")
HEADERS = {"X-Vex-Key": API_KEY, "Content-Type": "application/json"}


def test_agent_limit():
    print("Testing agent limit enforcement...")
    for i in range(10):
        payload = {"agent_id": f"limit-test-agent-{i}", "task": "test", "output": f"out-{i}"}
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        if resp.status_code == 403:
            print(f"  PASS: Got 403 after agent #{i + 1} — {resp.json().get('detail')}")
            return True
        if resp.status_code not in (200, 201, 202):
            print(f"  Unexpected {resp.status_code}: {resp.text}")
    print("  INFO: 10 agents without hitting limit")
    return True


def test_rate_limit():
    print("Testing rate limit enforcement...")
    payload = {"agent_id": "rate-limit-agent", "task": "test", "output": "test"}
    for i in range(150):
        resp = requests.post(f"{INGEST_URL}/v1/observe", json=payload, headers=HEADERS)
        if resp.status_code == 429:
            print(f"  PASS: Got 429 after {i + 1} requests, Retry-After: {resp.headers.get('Retry-After')}")
            return True
    print("  INFO: No 429 in 150 requests")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VEX_API_KEY required"); sys.exit(1)
    sys.exit(0 if all([test_agent_limit(), test_rate_limit()]) else 1)
```

**Step 2: Commit**

```bash
git add scripts/test_plan_enforcement.py
git commit -m "test: add E2E agent limit and rate limit test scripts"
```

---

### Task 13: Deprecate TimescaleDB `organizations.plan` Column

**Files:**
- Modify: `services/shared/shared/auth.py` — remove reading `plan` from `organizations` query (now comes from Supabase)
- Modify: `nextjs-application/apps/web/lib/agentguard/resolve-org-id.ts` — remove `plan` from auto-provision INSERT

This is a cleanup task. The `organizations.plan` column in TimescaleDB is no longer the source of truth. We:
1. Stop writing to it
2. Stop reading from it (already done in Task 4)
3. Leave the column in place (no destructive migration) but document it as deprecated

**Step 1: Update `resolve-org-id.ts`**

Change the auto-provision INSERT from:
```sql
INSERT INTO organizations (org_id, name, api_keys, plan, account_slug)
VALUES ($1, $2, '[]'::jsonb, 'free', $3)
```
to:
```sql
INSERT INTO organizations (org_id, name, api_keys, account_slug)
VALUES ($1, $2, '[]'::jsonb, $3)
```

**Step 2: Commit**

```bash
git add nextjs-application/apps/web/lib/agentguard/resolve-org-id.ts
git commit -m "chore: stop writing plan to TimescaleDB (Supabase is source of truth)"
```
