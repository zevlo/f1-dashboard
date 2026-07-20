# F1 Telemetry Dashboard — v0.dev Wireframe Prompt

**Created:** June 2026
**Purpose:** Generate the README hero + blog asset for the F1 Telemetry Dashboard. Static mockup only — Frame 1 (live race view).
**Tool:** v0.dev (free tier — single-shot optimized)
**Spec reference:** planning spec at `~/projects/dev/f1-telemetry-dashboard.md` Section 6 (lines 200-381)

---

## 1. Pre-flight

1. Sign in at **v0.dev** (GitHub or Vercel account).
2. Click **New Project** → blank canvas (React + Tailwind + shadcn/ui is the default — confirm).
3. Have this file open in a second tab for the iteration prompts.

---

## 2. The Prompt (copy-paste verbatim)

Optimized for first-shot success on free tier. Every detail is specified so v0 doesn't have to guess.

```
Build a single-screen React + Tailwind dashboard mockup. STATIC ONLY — no
state, no fetch, no interactivity, just hardcoded sample data. Treat this
as a portfolio screenshot.

Stack: Next.js + Tailwind + shadcn/ui (Card, Badge, Button) + lucide-react
icons + Recharts. Dark theme. Viewport: 1440×900, desktop only, no mobile
breakpoints, single screen with no scroll.

LAYOUT (use CSS grid):

Row 1 — TopBar (h-14, full width):
  [Session: Race · Monza Grand Prix ▼]  [● LIVE green-pulse]  [🟢 GREEN FLAG]
                                                   [Lap 34/53]   [15:42 UTC]

Row 2 — 3-column grid (h-[580px]):
  Col 1 (w-72): POSITION TOWER card
  Col 2 (flex-1): TELEMETRY — VERSTAPPEN card
  Col 3 (w-80): RACE ENGINEER chat card

Row 3 — LAP TIMES card (h-56, full width)

POSITION TOWER content:
  Card title "POSITION TOWER"
  20 rows, each h-7, single line:
    [Pn] [team-color-stripe w-1] [DRIVER 3-letter code] ......... [+gap]
  Drivers (P1-P20) in this exact order with these team colors:
    P1 VER #1E3A8A (highlighted row, bg-blue-950)
    P2 NOR #F97316
    P3 LEC #DC2626
    P4 HAM #DC2626
    P5 SAI #DC2626
    P6 RUS #14B8A6
    P7 ALO #16A34A
    P8 STR #16A34A
    P9 GAS #EC4899
    P10 OCO #EC4899
    P11-P20: HUL, ALB, ZHO, MAG, RIC, BOT, KEV, TSU, SAR, PER
      (use neutral zinc stripes, increment gap by ~1.2s per position)
  Gaps: P1 "+0.000", P2 "+2.341", P3 "+5.112", P4 "+8.704", then
  increase roughly linearly.

TELEMETRY — VERSTAPPEN content:
  Card title "TELEMETRY — VERSTAPPEN · #1" with VER navy stripe accent
  Row of 3 equal stat cards:
    SPEED     GEAR    DRS
    348 km/h   8       ON
  Two horizontal progress bars:
    THROTTLE [████████████████░░░░] 100% (green-500 fill)
    BRAKE    [░░░░░░░░░░░░░░░░░░░░] 0%   (red-500 fill)
  Info line at bottom in mono font:
    "TIRE: SOFT · Lap 18/22   GAP: +0.000s   INTERVAL: —"

RACE ENGINEER content:
  Card title "RACE ENGINEER" with mono session/driver context in header
  Scrollable message list (stub chat until AgentCore):
    YOU: "Where is VER losing time in S2?"
    ENGINEER: stub acknowledgement mentioning session + focused driver
  Sticky input row at bottom: text field + Send button

LAP TIMES content:
  Card title "LAP TIMES — VER vs NOR (last 10 laps)"
  Recharts LineChart with 2 lines:
    VER (stroke #1E3A8A) and NOR (stroke #F97316)
    X-axis: laps 24-33
    Y-axis: lap duration 82-86 seconds
    10 data points per series, realistic variation around 83.5s
  Legend top-right

STYLE (enforce strictly):
  - bg-zinc-950 page background
  - Cards: bg-zinc-900, border-zinc-800, rounded-xl, p-4
  - Text: text-zinc-100 (primary), text-zinc-400 (secondary), font-mono for numbers
  - No gradients, no glows, no drop shadows beyond shadow-sm
  - Aesthetic: ops console, not TV broadcast
```

---

## 3. If Something's Off (single follow-up prompt)

Free tier is tight — don't burn generations on small fixes. Send this one follow-up with up to 3 specific issues:

```
The layout is close. Make ONLY these specific fixes, keep everything else
identical:
- [specific issue 1]
- [specific issue 2]
- [specific issue 3]
Single screen, no scroll, dark theme preserved.
```

Common fixes to drop in:
- "Position tower rows must be h-7 and fit all 20 drivers without scrolling"
- "Remove the mobile breakpoint logic — desktop 1440px only"
- "Lap chart needs 10 visible data points per series, not 3"
- "Remove all gradients and shadows except shadow-sm"
- "VER row must have bg-blue-950 to show it's selected"

---

## 4. Export the PNG

After v0 produces a satisfactory result:

1. Click the **Preview** tab (not Code).
2. Resize preview pane to ~1440px wide (or use viewport dropdown if available).
3. Cleanest export — Chrome DevTools full-size screenshot:
   - `Cmd+Option+I` to open DevTools
   - `Cmd+Shift+P` to open Command Menu
   - Type "Capture full size screenshot" → Enter
   - Saves a PNG of the entire rendered page at 2x resolution
4. Fallback — macOS screenshot:
   - `Cmd+Shift+5` → choose window or drag region
5. Save the file as `mockup-live.png` and place it in this `frontend/docs/` folder.
6. **Save the v0 project** (click Save / fork to your account) so you can re-export or modify later without regenerating from scratch.

Target resolution: ~2880×1800 (2x of 1440×900) for crisp retina rendering in README/blog.

---

## 5. Where the Asset Lives

This file is at `frontend/docs/wireframe-v0-prompt.md` in the F1 dashboard repo. The PNG goes alongside it:

```
f1-telemetry-dashboard/
└── frontend/
    └── docs/
        ├── wireframe-v0-prompt.md   ← this file
        └── mockup-live.png          ← exported PNG lands here
```

**README hero placement** — once `mockup-live.png` exists, edit `README.md` at repo root:

```markdown
# F1 Telemetry Dashboard

![F1 Telemetry Dashboard — live race view](frontend/docs/mockup-live.png)

Real-time event-driven AWS pipeline that ingests live F1 telemetry...
```

**Blog post** (planned "AWS Project Architecture" post, Week 8): use the same PNG with a caption describing the data flow — `OpenF1 → Kinesis → Lambda → DynamoDB → WebSocket → browser`.

---

## 6. Quota Discipline (free tier)

- Initial prompt = 1 generation
- One follow-up = 1 generation (only if needed)
- Target: ≤2 generations total
- If the first output is 80% right, fix with ONE follow-up — don't iterate more
- If the first output is <50% right, the prompt itself needs work; revisit before retrying
