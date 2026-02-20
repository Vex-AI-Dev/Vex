# Live Agent Demo Page — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A dedicated `/demo` page on the landing app showing a scripted 30-60 second animation of a support ticket classifier agent where Vex catches drift and auto-corrects in real-time.

**Architecture:** Server component page with metadata + single `'use client'` component containing all animation logic. Scripted data array drives a 3-phase sequence (Normal → Drift → Correction). `IntersectionObserver` triggers playback, `setInterval` at 600ms advances through the sequence. No new dependencies — CSS animations + React state only.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Lucide icons

---

### Task 1: Create the Demo Page (Server Component)

**Files:**
- Create: `apps/landing/app/demo/page.tsx`

**Step 1: Create the page**

```tsx
import type { Metadata } from 'next';

import { LiveDemo } from './_components/live-demo';

export const metadata: Metadata = {
  title: 'Live Demo — Vex',
  description:
    'Watch Vex protect an AI agent in real-time. See drift detection and auto-correction in action.',
};

export default function DemoPage() {
  return (
    <div className="container py-24">
      {/* Hero */}
      <div className="mx-auto max-w-3xl text-center">
        <div className="mb-4 text-[13px] font-medium tracking-widest text-emerald-500 uppercase">
          Live Demo
        </div>

        <h1 className="mb-4 text-4xl font-bold tracking-tight text-white lg:text-5xl">
          Watch Vex Protect an Agent in Real-Time
        </h1>

        <p className="text-lg text-[#a2a2a2]">
          A support ticket classifier runs live. When the model drifts, Vex
          detects the issue and auto-corrects — before bad outputs reach
          production.
        </p>
      </div>

      {/* Demo */}
      <div className="mt-16">
        <LiveDemo />
      </div>

      {/* Key Takeaways */}
      <div className="mt-24 grid gap-6 md:grid-cols-3">
        {[
          {
            title: 'Detect',
            description:
              'Confidence scoring flags misclassifications the moment they happen.',
          },
          {
            title: 'Correct',
            description:
              'Prompt refinement cascades re-classify outputs automatically.',
          },
          {
            title: 'Zero Downtime',
            description:
              'Corrections happen inline — no redeployments, no manual intervention.',
          },
        ].map((card) => (
          <div
            key={card.title}
            className="rounded-xl border border-[#252525] bg-[#161616] p-6"
          >
            <h3 className="mb-2 text-lg font-semibold text-white">
              {card.title}
            </h3>

            <p className="text-sm text-[#a2a2a2]">{card.description}</p>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="mt-16 text-center">
        <a
          href="https://app.tryvex.dev"
          className="inline-flex items-center rounded-lg bg-emerald-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-600"
        >
          Start Protecting Your Agents
        </a>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
cd nextjs-application
git add apps/landing/app/demo/page.tsx
git commit -m "feat: add /demo page shell with hero, takeaways, and CTA"
```

---

### Task 2: Create the Live Demo Component (Client Component)

**Files:**
- Create: `apps/landing/app/demo/_components/live-demo.tsx`

**Step 1: Create the scripted data + component**

This is the entire component. It has three sections:

1. **Scripted ticket data** — array of objects with phase, ticket text, correct/wrong classification, confidence, and correction info.
2. **Animation state machine** — `IntersectionObserver` triggers playback, `setInterval` at 600ms reveals one ticket at a time.
3. **Two-panel layout** — left panel shows incoming tickets, right panel shows Vex monitoring dashboard with terminal log.

```tsx
'use client';

import { useEffect, useRef, useState } from 'react';

import {
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  RotateCcw,
  Shield,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Scripted data                                                      */
/* ------------------------------------------------------------------ */

interface Ticket {
  id: number;
  phase: 1 | 2 | 3;
  text: string;
  classification: string;
  correctClassification?: string;
  confidence: number;
  status: 'pass' | 'flag' | 'corrected';
}

const TICKETS: Ticket[] = [
  // Phase 1: Normal operation
  {
    id: 1,
    phase: 1,
    text: "Can't login to my account",
    classification: 'Technical',
    confidence: 0.97,
    status: 'pass',
  },
  {
    id: 2,
    phase: 1,
    text: 'I want a refund for my last order',
    classification: 'Billing',
    confidence: 0.95,
    status: 'pass',
  },
  {
    id: 3,
    phase: 1,
    text: 'App crashes when I open settings',
    classification: 'Technical',
    confidence: 0.96,
    status: 'pass',
  },
  {
    id: 4,
    phase: 1,
    text: 'How do I cancel my subscription?',
    classification: 'Billing',
    confidence: 0.93,
    status: 'pass',
  },
  // Phase 2: Drift
  {
    id: 5,
    phase: 2,
    text: 'Payment failed on checkout',
    classification: 'Technical',
    correctClassification: 'Billing',
    confidence: 0.61,
    status: 'flag',
  },
  {
    id: 6,
    phase: 2,
    text: 'Charged twice for same item',
    classification: 'Technical',
    correctClassification: 'Billing',
    confidence: 0.58,
    status: 'flag',
  },
  // Phase 3: Correction
  {
    id: 7,
    phase: 3,
    text: 'Payment failed on checkout',
    classification: 'Billing',
    confidence: 0.92,
    status: 'corrected',
  },
  {
    id: 8,
    phase: 3,
    text: 'Charged twice for same item',
    classification: 'Billing',
    confidence: 0.94,
    status: 'corrected',
  },
];

interface LogEntry {
  phase: 1 | 2 | 3;
  text: string;
  type: 'info' | 'warn' | 'success';
}

const LOGS: LogEntry[] = [
  { phase: 1, text: 'session started — model: gpt-4o-mini', type: 'info' },
  { phase: 1, text: 'check: confidence 0.97 → action: pass', type: 'info' },
  { phase: 1, text: 'check: confidence 0.95 → action: pass', type: 'info' },
  { phase: 1, text: 'check: confidence 0.96 → action: pass', type: 'info' },
  { phase: 1, text: 'check: confidence 0.93 → action: pass', type: 'info' },
  {
    phase: 2,
    text: '⚠ drift_score: 0.45 — confidence dropping',
    type: 'warn',
  },
  {
    phase: 2,
    text: 'check: confidence 0.61 → action: flag',
    type: 'warn',
  },
  {
    phase: 2,
    text: 'check: confidence 0.58 → action: flag',
    type: 'warn',
  },
  {
    phase: 3,
    text: 'correction cascade triggered — L1 prompt refinement',
    type: 'success',
  },
  {
    phase: 3,
    text: 're-classify ticket #5 → Billing (0.92)',
    type: 'success',
  },
  {
    phase: 3,
    text: 're-classify ticket #6 → Billing (0.94)',
    type: 'success',
  },
  {
    phase: 3,
    text: '✓ 2 issues caught, 2 auto-corrected, 0 reached production',
    type: 'success',
  },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function LiveDemo() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [started, setStarted] = useState(false);
  const [ticketIndex, setTicketIndex] = useState(0);
  const [logIndex, setLogIndex] = useState(0);
  const [done, setDone] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Intersection Observer — trigger once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setStarted(true);
          observer.unobserve(el);
        }
      },
      { threshold: 0.05 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Playback interval
  useEffect(() => {
    if (!started || done) return;

    let tIdx = 0;
    let lIdx = 0;

    intervalRef.current = setInterval(() => {
      // Advance whichever is behind, preferring logs for pacing
      const ticketPhase = TICKETS[tIdx]?.phase ?? 4;
      const logPhase = LOGS[lIdx]?.phase ?? 4;

      if (lIdx < LOGS.length && logPhase <= ticketPhase) {
        lIdx++;
        setLogIndex(lIdx);
      } else if (tIdx < TICKETS.length) {
        tIdx++;
        setTicketIndex(tIdx);
      } else if (lIdx < LOGS.length) {
        lIdx++;
        setLogIndex(lIdx);
      }

      if (tIdx >= TICKETS.length && lIdx >= LOGS.length) {
        setDone(true);
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }, 600);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [started, done]);

  const replay = () => {
    setTicketIndex(0);
    setLogIndex(0);
    setDone(false);
    setStarted(true);
  };

  const visibleTickets = TICKETS.slice(0, ticketIndex);
  const visibleLogs = LOGS.slice(0, logIndex);
  const currentPhase = done
    ? 3
    : (visibleLogs[visibleLogs.length - 1]?.phase ?? 1);

  return (
    <div ref={containerRef}>
      {/* Phase indicator */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex gap-3">
          {[
            { phase: 1, label: 'Normal' },
            { phase: 2, label: 'Drift Detected' },
            { phase: 3, label: 'Auto-Corrected' },
          ].map((p) => (
            <div
              key={p.phase}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                currentPhase === p.phase
                  ? p.phase === 1
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : p.phase === 2
                      ? 'bg-amber-500/20 text-amber-400'
                      : 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-[#1a1a1a] text-[#585858]'
              }`}
            >
              {p.label}
            </div>
          ))}
        </div>

        {done && (
          <button
            onClick={replay}
            className="flex items-center gap-1.5 text-xs text-[#a2a2a2] transition-colors hover:text-white"
          >
            <RotateCcw className="h-3 w-3" />
            Replay
          </button>
        )}
      </div>

      {/* Split panel */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Left: Ticket Feed */}
        <div className="rounded-xl border border-[#252525] bg-[#161616] p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-white">
            <Shield className="h-4 w-4 text-emerald-500" />
            Incoming Tickets
          </div>

          <div className="space-y-3">
            {visibleTickets.length === 0 && !started && (
              <p className="py-8 text-center text-sm text-[#585858]">
                Scroll down to start the demo…
              </p>
            )}

            {visibleTickets.length === 0 && started && !done && (
              <p className="py-8 text-center text-sm text-[#585858]">
                Processing…
              </p>
            )}

            {visibleTickets.map((ticket) => (
              <div
                key={`${ticket.id}-${ticket.phase}`}
                className="animate-[termLine_0.4s_cubic-bezier(0.16,1,0.3,1)_forwards] rounded-lg border border-[#252525] bg-[#0f0f0f] p-3 opacity-0"
              >
                <div className="mb-2 text-sm text-white">
                  &quot;{ticket.text}&quot;
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                        ticket.status === 'pass'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : ticket.status === 'flag'
                            ? 'bg-amber-500/10 text-amber-400'
                            : 'bg-emerald-500/10 text-emerald-400'
                      }`}
                    >
                      {ticket.status === 'corrected' ? (
                        <span className="flex items-center gap-1">
                          <RefreshCw className="h-3 w-3" />
                          corrected
                        </span>
                      ) : (
                        ticket.status
                      )}
                    </span>

                    <span className="text-xs text-[#a2a2a2]">
                      → {ticket.classification}
                    </span>

                    {ticket.correctClassification && (
                      <span className="text-xs text-red-400 line-through">
                        (was {ticket.classification})
                      </span>
                    )}
                  </div>

                  <span
                    className={`text-xs font-mono ${
                      ticket.confidence >= 0.9
                        ? 'text-emerald-400'
                        : ticket.confidence >= 0.7
                          ? 'text-amber-400'
                          : 'text-red-400'
                    }`}
                  >
                    {ticket.confidence.toFixed(2)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Vex Monitor */}
        <div className="rounded-xl border border-[#252525] bg-[#161616] p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-white">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            Vex Monitor
          </div>

          {/* Confidence meter */}
          <div className="mb-4 rounded-lg border border-[#252525] bg-[#0f0f0f] p-3">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="text-[#a2a2a2]">Model Confidence</span>

              <span
                className={`font-mono ${
                  currentPhase === 2 ? 'text-amber-400' : 'text-emerald-400'
                }`}
              >
                {currentPhase === 2
                  ? '0.58'
                  : currentPhase === 3
                    ? '0.92'
                    : '0.95'}
              </span>
            </div>

            <div className="h-1.5 overflow-hidden rounded-full bg-[#252525]">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  currentPhase === 2 ? 'bg-amber-500' : 'bg-emerald-500'
                }`}
                style={{
                  width:
                    currentPhase === 2
                      ? '58%'
                      : currentPhase === 3
                        ? '92%'
                        : '95%',
                }}
              />
            </div>
          </div>

          {/* Drift alert */}
          {currentPhase >= 2 && (
            <div
              className={`mb-4 flex items-center gap-2 rounded-lg border p-3 text-xs animate-[termLine_0.4s_cubic-bezier(0.16,1,0.3,1)_forwards] opacity-0 ${
                currentPhase === 2
                  ? 'border-amber-500/30 bg-amber-500/5 text-amber-400'
                  : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400'
              }`}
            >
              {currentPhase === 2 ? (
                <>
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Model drift detected — confidence below threshold
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Drift resolved — corrections applied successfully
                </>
              )}
            </div>
          )}

          {/* Terminal log */}
          <div className="rounded-lg border border-[#252525] bg-[#0a0a0a] p-3">
            <div className="mb-2 text-[10px] font-medium tracking-wider text-[#585858] uppercase">
              Terminal
            </div>

            <div className="max-h-64 space-y-1 overflow-y-auto font-mono text-xs">
              {visibleLogs.map((log, i) => (
                <div
                  key={i}
                  className={`animate-[termLine_0.4s_cubic-bezier(0.16,1,0.3,1)_forwards] opacity-0 ${
                    log.type === 'warn'
                      ? 'text-amber-400'
                      : log.type === 'success'
                        ? 'text-emerald-400'
                        : 'text-[#a2a2a2]'
                  }`}
                >
                  <span className="mr-2 text-[#585858]">$</span>
                  {log.text}
                </div>
              ))}

              {visibleLogs.length === 0 && (
                <div className="text-[#585858]">
                  <span className="mr-2">$</span>
                  awaiting session…
                </div>
              )}
            </div>
          </div>

          {/* Summary (Phase 3 complete) */}
          {done && (
            <div className="mt-4 animate-[termLine_0.4s_cubic-bezier(0.16,1,0.3,1)_forwards] rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 opacity-0">
              <div className="flex items-center justify-around text-center text-xs">
                <div>
                  <div className="text-lg font-bold text-emerald-400">2</div>
                  <div className="text-[#a2a2a2]">Issues caught</div>
                </div>

                <div>
                  <div className="text-lg font-bold text-emerald-400">2</div>
                  <div className="text-[#a2a2a2]">Auto-corrected</div>
                </div>

                <div>
                  <div className="text-lg font-bold text-white">0</div>
                  <div className="text-[#a2a2a2]">Reached production</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors in landing app

**Step 3: Commit**

```bash
cd nextjs-application
git add apps/landing/app/demo/_components/live-demo.tsx
git commit -m "feat: add live demo component with 3-phase animation"
```

---

### Task 3: Final Verification

**Step 1: Full typecheck**

Run: `cd nextjs-application && pnpm typecheck`
Expected: No new errors

**Step 2: Lint and format**

Run: `cd nextjs-application && pnpm lint:fix && pnpm format:fix`

**Step 3: Commit any formatting changes**

```bash
cd nextjs-application
git add -A && git commit -m "chore: lint and format"
```
