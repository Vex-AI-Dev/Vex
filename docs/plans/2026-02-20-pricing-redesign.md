# Pricing Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure pricing from 4 tiers (Free/Pro/Team/Enterprise) to 5 tiers (Free/Starter/Pro/Team/Enterprise) with updated quotas, remove agent limits, and add a `corrections_per_month` field.

**Architecture:** Update plan config in Python (backend enforcement) and TypeScript (dashboard display) simultaneously. Add `starter` to the DB CHECK constraint via a new migration. Update landing page pricing cards, admin UI dropdown, and dashboard corrections display.

**Tech Stack:** Python (dataclass), TypeScript, Next.js 16, PostgreSQL, Tailwind CSS

---

### Task 1: Update Python Plan Config

**Files:**
- Modify: `services/shared/shared/plan_limits.py`

**Step 1: Update PlanConfig dataclass and PLAN_LIMITS**

Add `corrections_per_month` field to `PlanConfig`. Update all tier values. Add `starter` tier. Set all `max_agents` to `-1`.

Replace the entire `PlanConfig` class and `PLAN_LIMITS` dict with:

```python
@dataclass(frozen=True)
class PlanConfig:
    """Immutable configuration for a single pricing plan."""

    # Monthly quotas
    observations_per_month: int
    verifications_per_month: int
    corrections_per_month: int  # -1 = unlimited (full cascade)

    # Rate limit
    max_rpm: int

    # Resource limits
    max_agents: int  # -1 = unlimited

    # Feature flags
    corrections_enabled: bool
    webhook_alerts: bool
    slack_alerts: bool

    # Data retention
    retention_days: int

    # Overage handling
    overage_allowed: bool


PLAN_LIMITS: Dict[str, PlanConfig] = {
    "free": PlanConfig(
        observations_per_month=1_000,
        verifications_per_month=50,
        corrections_per_month=0,
        max_rpm=100,
        max_agents=-1,
        corrections_enabled=False,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=1,
        overage_allowed=False,
    ),
    "starter": PlanConfig(
        observations_per_month=25_000,
        verifications_per_month=1_000,
        corrections_per_month=100,
        max_rpm=500,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=False,
        slack_alerts=False,
        retention_days=7,
        overage_allowed=False,
    ),
    "pro": PlanConfig(
        observations_per_month=150_000,
        verifications_per_month=15_000,
        corrections_per_month=-1,
        max_rpm=1_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=False,
        retention_days=30,
        overage_allowed=True,
    ),
    "team": PlanConfig(
        observations_per_month=1_500_000,
        verifications_per_month=150_000,
        corrections_per_month=-1,
        max_rpm=5_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=90,
        overage_allowed=True,
    ),
    "enterprise": PlanConfig(
        observations_per_month=10_000_000,
        verifications_per_month=1_000_000,
        corrections_per_month=-1,
        max_rpm=10_000,
        max_agents=-1,
        corrections_enabled=True,
        webhook_alerts=True,
        slack_alerts=True,
        retention_days=365,
        overage_allowed=True,
    ),
}
```

Keep the docstrings on the fields. The `get_plan_config` function stays unchanged.

**Step 2: Verify**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python -c "from services.shared.shared.plan_limits import PLAN_LIMITS; print(PLAN_LIMITS['starter'])"`
Expected: Prints the starter PlanConfig

**Step 3: Commit**

```bash
git add services/shared/shared/plan_limits.py
git commit -m "feat: update plan limits — add starter tier, remove agent caps, add corrections_per_month"
```

---

### Task 2: Update TypeScript Plan Config

**Files:**
- Modify: `apps/web/lib/agentguard/plan-limits.ts`

**Step 1: Update PlanLimits interface and PLAN_LIMITS**

Add `correctionsPerMonth` field to `PlanLimits` interface. Add `starter` tier. Update all values. Set all `maxAgents` to `-1`.

The full updated interface:

```typescript
export interface PlanLimits {
  observationsPerMonth: number;
  verificationsPerMonth: number;
  correctionsPerMonth: number; // -1 = unlimited (full cascade)
  maxRpm: number;
  maxAgents: number;
  maxSeats: number;
  correctionsEnabled: boolean;
  webhookAlerts: boolean;
  slackAlerts: boolean;
  retentionDays: number;
  overageAllowed: boolean;
}
```

The full updated `PLAN_LIMITS`:

```typescript
export const PLAN_LIMITS: Record<string, PlanLimits> = {
  free: {
    observationsPerMonth: 1_000,
    verificationsPerMonth: 50,
    correctionsPerMonth: 0,
    maxRpm: 100,
    maxAgents: -1,
    maxSeats: 1,
    correctionsEnabled: false,
    webhookAlerts: false,
    slackAlerts: false,
    retentionDays: 1,
    overageAllowed: false,
  },
  starter: {
    observationsPerMonth: 25_000,
    verificationsPerMonth: 1_000,
    correctionsPerMonth: 100,
    maxRpm: 500,
    maxAgents: -1,
    maxSeats: 3,
    correctionsEnabled: true,
    webhookAlerts: false,
    slackAlerts: false,
    retentionDays: 7,
    overageAllowed: false,
  },
  pro: {
    observationsPerMonth: 150_000,
    verificationsPerMonth: 15_000,
    correctionsPerMonth: -1,
    maxRpm: 1_000,
    maxAgents: -1,
    maxSeats: 5,
    correctionsEnabled: true,
    webhookAlerts: true,
    slackAlerts: false,
    retentionDays: 30,
    overageAllowed: true,
  },
  team: {
    observationsPerMonth: 1_500_000,
    verificationsPerMonth: 150_000,
    correctionsPerMonth: -1,
    maxRpm: 5_000,
    maxAgents: -1,
    maxSeats: 15,
    correctionsEnabled: true,
    webhookAlerts: true,
    slackAlerts: true,
    retentionDays: 90,
    overageAllowed: true,
  },
  enterprise: {
    observationsPerMonth: 10_000_000,
    verificationsPerMonth: 1_000_000,
    correctionsPerMonth: -1,
    maxRpm: 10_000,
    maxAgents: -1,
    maxSeats: -1,
    correctionsEnabled: true,
    webhookAlerts: true,
    slackAlerts: true,
    retentionDays: 365,
    overageAllowed: true,
  },
};
```

The `getPlanLimits`, `canAddSeat`, and `canAddAgent` functions stay unchanged.

**Step 2: Verify**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors

**Step 3: Commit**

```bash
cd nextjs-application
git add apps/web/lib/agentguard/plan-limits.ts
git commit -m "feat: update TypeScript plan limits — mirror Python changes"
```

---

### Task 3: Database Migration

**Files:**
- Create: `apps/web/supabase/migrations/20260220100000_add_starter_plan.sql`

**Step 1: Create migration**

```sql
-- Add 'starter' to the valid plan values CHECK constraint.
-- This is a non-destructive change — existing rows are unaffected.

ALTER TABLE public.accounts
  DROP CONSTRAINT accounts_vex_plan_valid;

ALTER TABLE public.accounts
  ADD CONSTRAINT accounts_vex_plan_valid CHECK (
    vex_plan IN ('free', 'starter', 'pro', 'team', 'enterprise')
  );
```

**Step 2: Commit**

```bash
cd nextjs-application
git add apps/web/supabase/migrations/20260220100000_add_starter_plan.sql
git commit -m "feat: add starter to vex_plan CHECK constraint"
```

---

### Task 4: Admin UI — Add Starter to Dropdown and Zod Schema

**Files:**
- Modify: `apps/web/app/admin/accounts/[id]/_components/plan-management.tsx`
- Modify: `apps/web/app/admin/accounts/[id]/_lib/update-plan.action.ts`

**Step 1: Update plan-management.tsx**

Change line 25:

```typescript
const PLANS = ['free', 'starter', 'pro', 'team', 'enterprise'] as const;
```

**Step 2: Update update-plan.action.ts**

Change the Zod schema plan enum on line 12:

```typescript
  plan: z.enum(['free', 'starter', 'pro', 'team', 'enterprise']),
```

**Step 3: Verify**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors

**Step 4: Commit**

```bash
cd nextjs-application
git add apps/web/app/admin/accounts/[id]/_components/plan-management.tsx \
  apps/web/app/admin/accounts/[id]/_lib/update-plan.action.ts
git commit -m "feat: add starter plan to admin UI dropdown and Zod schema"
```

---

### Task 5: Dashboard — Update Corrections Display for Starter

**Files:**
- Modify: `apps/web/app/home/[account]/_components/homepage-charts.tsx`

**Step 1: Update the corrections conditional**

The current code shows the Verifications meter only when `planLimits.correctionsEnabled` is true, and shows "Auto-Correction is available on paid plans" when false. Since Starter now has `correctionsEnabled: true` (with 100/mo), the existing conditional already works — Starter users will see the Verifications meter.

No code change needed here. The `correctionsEnabled: true` on the Starter tier handles this automatically.

**Step 2: Verify**

Confirm by reading the code: `planLimits.correctionsEnabled` is the gate. Starter has `correctionsEnabled: true`. Free has `correctionsEnabled: false`. The existing conditional is correct.

---

### Task 6: Landing Page — Rewrite Pricing Cards

**Files:**
- Modify: `apps/landing/app/pricing/page.tsx`

**Step 1: Replace the `plans` array (lines 19-82) with:**

```typescript
const plans = [
  {
    name: 'Free',
    price: '$0',
    period: '/mo',
    description: 'Sandbox for exploring agent reliability.',
    cta: 'Get Started Free',
    href: 'https://app.tryvex.dev',
    highlighted: false,
    features: [
      { label: 'Observations', value: '1,000 / mo' },
      { label: 'Verifications', value: '50 / mo' },
      { label: 'Corrections', value: 'None' },
      { label: 'Agents', value: 'Unlimited' },
      { label: 'Data retention', value: '1 day' },
      { label: 'Rate limit', value: '100 RPM' },
      { label: 'Overage', value: 'Hard limit' },
      { label: 'Support', value: 'Community' },
    ],
  },
  {
    name: 'Starter',
    price: '$29',
    period: '/mo',
    description: 'For founders running 1-2 agents in production.',
    cta: 'Start Starter',
    href: 'https://app.tryvex.dev',
    highlighted: false,
    features: [
      { label: 'Observations', value: '25,000 / mo' },
      { label: 'Verifications', value: '1,000 / mo' },
      { label: 'Corrections', value: '100 / mo' },
      { label: 'Agents', value: 'Unlimited' },
      { label: 'Data retention', value: '7 days' },
      { label: 'Rate limit', value: '500 RPM' },
      { label: 'Overage', value: 'Hard limit' },
      { label: 'Support', value: 'Email' },
    ],
  },
  {
    name: 'Pro',
    price: '$99',
    period: '/mo',
    yearly: '$990/yr ($83/mo)',
    description: 'For teams shipping agents to production.',
    cta: 'Start Pro',
    href: 'https://app.tryvex.dev',
    highlighted: true,
    features: [
      { label: 'Observations', value: '150,000 / mo' },
      { label: 'Verifications', value: '15,000 / mo' },
      { label: 'Corrections', value: 'Full cascade' },
      { label: 'Agents', value: 'Unlimited' },
      { label: 'Data retention', value: '30 days' },
      { label: 'Rate limit', value: '1,000 RPM' },
      { label: 'Overage', value: '$0.0005/obs, $0.005/verify' },
      { label: 'Support', value: 'Email (48h)' },
    ],
  },
  {
    name: 'Team',
    price: '$349',
    period: '/mo',
    yearly: '$3,490/yr ($291/mo)',
    description: 'For organizations running agents at scale.',
    cta: 'Start Team',
    href: 'https://app.tryvex.dev',
    highlighted: false,
    features: [
      { label: 'Observations', value: '1,500,000 / mo' },
      { label: 'Verifications', value: '150,000 / mo' },
      { label: 'Corrections', value: 'Full cascade + priority' },
      { label: 'Agents', value: 'Unlimited' },
      { label: 'Data retention', value: '90 days' },
      { label: 'Rate limit', value: '5,000 RPM' },
      { label: 'Overage', value: '$0.0004/obs, $0.004/verify' },
      { label: 'Support', value: 'Priority (24h)' },
    ],
  },
];
```

**Step 2: Update the grid layout**

Change line 134 from `lg:grid-cols-3` to `lg:grid-cols-4` to fit 4 plan cards:

```tsx
<div className="mx-auto mb-20 grid max-w-[1200px] gap-4 lg:grid-cols-4">
```

Also update the `max-w-[1100px]` on the hero container (line 121) and enterprise CTA (line 193) to `max-w-[1200px]` to accommodate the wider grid.

**Step 3: Update FAQ about annual billing**

Replace the annual billing FAQ answer:

```typescript
  {
    question: 'Do you offer annual billing?',
    answer:
      'Yes. Annual billing saves you roughly two months compared to monthly pricing. Pro is $990/yr ($83/mo) and Team is $3,490/yr ($291/mo). Contact us to switch to annual billing.',
  },
```

Update the free plan overage FAQ:

```typescript
  {
    question: 'What happens when I exceed my plan limits?',
    answer:
      'On Free and Starter plans, monitoring pauses until the next billing cycle. On Pro and Team plans, you can continue beyond your included quota at the listed overage rates. You will receive alerts as you approach your limits.',
  },
```

**Step 4: Verify**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors

**Step 5: Commit**

```bash
cd nextjs-application
git add apps/landing/app/pricing/page.tsx
git commit -m "feat: update pricing page — add Starter tier, new quotas across all plans"
```

---

### Task 7: Final Verification

**Step 1: Full typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors

**Step 2: Python import test**

Run: `cd /Users/thakurg/Hive/Research/AgentGuard && python -c "from services.shared.shared.plan_limits import PLAN_LIMITS, get_plan_config; assert 'starter' in PLAN_LIMITS; cfg = get_plan_config('starter'); assert cfg.corrections_per_month == 100; print('OK')"`
Expected: `OK`

**Step 3: Lint and format**

Run: `cd nextjs-application && pnpm lint:fix && pnpm format:fix`

**Step 4: Commit any formatting changes**

```bash
cd nextjs-application
git add -A && git commit -m "chore: lint and format"
```
