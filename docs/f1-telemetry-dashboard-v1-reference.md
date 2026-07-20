# F1 Telemetry Dashboard – Project Outline

**Created:** February 2026 | **Revised:** April 2026
**Timeline:** 4 weeks
**Approach:** IaC-first (Terraform + GitHub Actions from day one)
**Scope:** Real-time F1 telemetry visualization using OpenF1 API
**Purpose:** Event-driven architecture reference build — proves streaming, serverless, and production IaC discipline.

**Agent layer (follow-on phase):** Once the dashboard core is live, a Bedrock AgentCore "Race Engineer" agent is layered on top — natural-language telemetry queries against this dashboard's DynamoDB. Spec: `f1-race-engineer-agent.md`.

---

## 1. What You're Building

A real-time dashboard that ingests live F1 telemetry during race weekends and displays car positions, speeds, lap times, and session status on a web-based dashboard. Users see a live race unfolding — position changes, pit stops, flags, and weather — updated in near real-time via WebSockets.

**Why this project matters:**
- Proves you can build event-driven, real-time AWS architectures (not just static sites and CRUD APIs)

**What it is NOT:**
- Not the full multi-source dashboard (no sentiment, no NLP, no news feeds)
- Not a data lake or analytics platform (that's the stretch goal)
- Not a mobile app — browser-only React frontend

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGESTION                                │
│                                                                 │
│  OpenF1 API ──► Lambda (Poller) ──► Kinesis Data Stream         │
│                  (EventBridge                                   │
│                   scheduled                                     │
│                   every 5s)                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       PROCESSING                                │
│                                                                 │
│  Kinesis ──► Lambda (Transformer)                               │
│               ├── Normalize telemetry (speed, position, gaps)   │
│               ├── Detect events (overtakes, pit stops, flags)   │
│               └── Write to DynamoDB                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        STORAGE                                  │
│                                                                 │
│  DynamoDB Tables:                                               │
│    ├── Sessions      (PK: session_key)                          │
│    ├── Positions     (PK: session_key, SK: timestamp#driver)    │
│    ├── Laps          (PK: session_key#driver, SK: lap_number)   │
│    └── RaceControl   (PK: session_key, SK: timestamp)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DELIVERY                                  │
│                                                                 │
│  API Gateway (WebSocket API)                                    │
│    ├── $connect    → Lambda (connection manager)                │
│    ├── $disconnect → Lambda (cleanup)                           │
│    └── $default    → Lambda (query handler)                     │
│                                                                 │
│  API Gateway (REST API)                                         │
│    ├── GET /sessions         → Lambda → DynamoDB                │
│    ├── GET /sessions/{id}    → Lambda → DynamoDB                │
│    └── GET /drivers/{id}     → Lambda → DynamoDB                │
│                                                                 │
│  DynamoDB Streams → Lambda → WebSocket push to clients          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       FRONTEND                                  │
│                                                                 │
│  S3 (React build) ──► CloudFront ──► Browser                   │
│    ├── Position tower (live standings)                          │
│    ├── Telemetry cards (speed, gap, tire compound)              │
│    ├── Lap time chart (per driver)                              │
│    ├── Race control feed (flags, incidents)                     │
│    └── Session selector (FP1 → FP2 → FP3 → Quali → Race)      │
└─────────────────────────────────────────────────────────────────┘
```

**Monitoring:** CloudWatch dashboards + alarms across all Lambda functions, Kinesis iterator age, DynamoDB throttles, API Gateway 4xx/5xx rates, WebSocket connection count.

---

## 3. OpenF1 API – Endpoints to Use

Base URL: `https://api.openf1.org/v1`

| Endpoint | What It Gives You | Poll Frequency |
|----------|-------------------|----------------|
| `/sessions` | Session metadata (type, circuit, start/end times) | Once per session |
| `/position` | Live driver positions (P1-P20) | Every 5 seconds |
| `/car_data` | Speed, RPM, throttle, brake, gear, DRS | Every 5 seconds |
| `/laps` | Lap times, sector times, pit in/out laps | Every 10 seconds |
| `/pit` | Pit stop duration, tire compound | Every 10 seconds |
| `/race_control` | Flags, safety car, session status, incidents | Every 5 seconds |
| `/weather` | Track/air temp, humidity, wind, rain | Every 30 seconds |
| `/drivers` | Driver list, team, number, abbreviation | Once per session |

**Rate limit strategy (free tier: 3 req/s, 30 req/min):**
- Batch requests: poll 2-3 endpoints per cycle, rotate through them
- 5-second polling interval keeps you well under limits
- Cache `/sessions` and `/drivers` — they don't change mid-session
- Use `?date>={last_poll_timestamp}` to fetch only new records

---

## 4. AWS Services Breakdown

| Service | Role in This Project | Lab Foundation |
|---------|---------------------|----------------|
| **Lambda** | Poller, transformer, WebSocket handler, REST API | Lab 3, Lab 7 |
| **DynamoDB** | All telemetry storage, connection tracking | Lab 7 |
| **API Gateway (REST)** | Historical data queries | Lab 3 |
| **API Gateway (WebSocket)** | Real-time push to dashboard | *New* |
| **Kinesis Data Streams** | Buffer between poller and transformer | *New* |
| **EventBridge** | Scheduled trigger for poller Lambda (every 5s) | *New* |
| **S3** | React frontend hosting | Lab 1 |
| **CloudFront** | CDN for frontend | Lab 1 |
| **CloudWatch** | Dashboards, alarms, Lambda logs | Lab 6 |
| **IAM** | Roles for every service, least privilege | Lab 2 |
| **DynamoDB Streams** | Trigger WebSocket pushes on new data | *New* |

**New services to learn (4):** Kinesis Data Streams, EventBridge, WebSocket API Gateway, DynamoDB Streams
**Services from labs (6):** Lambda, DynamoDB, REST API Gateway, S3, CloudFront, CloudWatch, IAM

---

## 5. Data Model (DynamoDB)

### Sessions Table

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_key` (PK) | String | OpenF1 session identifier |
| `session_type` | String | `practice_1`, `qualifying`, `race`, etc. |
| `circuit_short_name` | String | `monza`, `silverstone`, etc. |
| `date_start` | String | ISO 8601 timestamp |
| `date_end` | String | ISO 8601 timestamp |
| `status` | String | `active`, `completed` |
| `year` | Number | Season year |

### Positions Table

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_key` (PK) | String | Session identifier |
| `ts_driver` (SK) | String | `{timestamp}#{driver_number}` |
| `driver_number` | Number | Car number |
| `position` | Number | Current position (1-20) |
| `date` | String | ISO 8601 timestamp |

**GSI:** `driver_number` (PK) + `session_key` (SK) — query all positions for a specific driver.

### CarData Table

High-frequency telemetry samples (speed, throttle, brake, gear, rpm, drs). One row per sample. Sourced from OpenF1 `/car_data`; the poller already ingests these records enveloped as `source: "car_data"`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_driver` (PK) | String | `{session_key}#{driver_number}` |
| `date` (SK) | String | ISO 8601 sample timestamp |
| `speed` | Number | Speed (km/h) |
| `throttle` | Number | Throttle application (0-100) |
| `brake` | Boolean | Braking (true/false) |
| `gear` | Number | Current gear (1-8) |
| `rpm` | Number | Engine RPM |
| `drs` | Number | DRS state (0-14) |
| `driver_number` | Number | Car number (denormalized for filters) |

**Access pattern:** query all samples for a driver in a session, sorted by time → speed/trace for the dashboard, and lap windows for the Race Engineer agent (join `date_start` from the Laps table to bound a lap's time range). The transformer must persist `car_data` records here alongside Positions.

### Laps Table

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_driver` (PK) | String | `{session_key}#{driver_number}` |
| `lap_number` (SK) | Number | Lap number |
| `date_start` | String | ISO 8601 lap-start timestamp (maps telemetry samples to laps — used by the Race Engineer) |
| `lap_duration` | Number | Total lap time (seconds) |
| `sector_1` | Number | Sector 1 time |
| `sector_2` | Number | Sector 2 time |
| `sector_3` | Number | Sector 3 time |
| `is_pit_out_lap` | Boolean | Pit exit lap flag |
| `compound` | String | `SOFT`, `MEDIUM`, `HARD`, `INTERMEDIATE`, `WET` |

### RaceControl Table

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_key` (PK) | String | Session identifier |
| `timestamp` (SK) | String | ISO 8601 timestamp |
| `category` | String | `Flag`, `SafetyCar`, `Drs`, etc. |
| `flag` | String | `GREEN`, `YELLOW`, `RED`, `CHEQUERED` |
| `message` | String | Full race control message |
| `driver_number` | Number | Affected driver (if applicable) |

### Connections Table (WebSocket)

| Attribute | Type | Description |
|-----------|------|-------------|
| `connection_id` (PK) | String | API Gateway connection ID |
| `connected_at` | String | ISO 8601 timestamp |
| `session_key` | String | Which session the client is watching |
| `ttl` | Number | Auto-expire stale connections (epoch) |

---

## 6. Frontend Wireframe & UI Spec

**Purpose:** Defines layout, components, states, and data flow for the React dashboard. Build the Excalidraw mockup from this section before writing JSX in Week 3.

**Stack:** Vite + React, served from S3 via CloudFront. No SSR. State via React hooks (or Zustand if complexity grows). Charts via Recharts or Visx. Styling via Tailwind or CSS modules.

**Target viewport:** 1440×900 desktop. Responsive collapse to single column < 1024px is a stretch goal, not MVP.

---

### 6.1 Layout — Default Live Race View

Three-column grid with a top bar and a bottom strip.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [Session: ▼ Race · Monza]   🟢 LIVE    🟢 GREEN   Lap 34/53   15:42 UTC │  TopBar (60px)
├──────────────┬───────────────────────────────────────┬───────────────────┤
│              │                                       │                   │
│  POSITION    │   TELEMETRY — VER (selected)          │  RACE ENGINEER    │
│  TOWER       │                                       │  CHAT             │
│              │   ┌───────┐ ┌──────┐ ┌──────┐         │                   │
│  P1 VER RED  │   │ SPEED │ │ GEAR │ │ DRS  │         │  YOU              │
│  P2 NOR +2.3 │   │  348  │ │  8   │ │ ON   │         │  Where is VER     │
│  P3 LEC +5.1 │   └───────┘ └──────┘ └──────┘         │  losing time S2?  │
│  P4 HAM +8.7 │                                       │                   │
│  P5 SAI +12  │   THROTTLE       BRAKE                │  ENGINEER (stub)  │
│  P6 RUS ...  │   ▓▓▓▓▓▓▓▓░░    ▓▓░░░░░░░░            │  Got it — session │
│  ...         │                                       │  … AgentCore soon │
│  P20 STR     │   TIRE: SOFT · Lap 18/22              │                   │
│              │   GAP: +2.341s   INTERVAL: +0.8s      │  [Ask…] [Send]    │
│  (280px)     │   (flexible)                          │  (320px)          │
│              │                                       │                   │
├──────────────┴───────────────────────────────────────┴───────────────────┤
│  LAP TIMES — VER vs NOR (last 10 laps)                                   │  LapTimeChart (220px)
│   ╱╲   ╱╲                                                                │
│  ╱  ╲ ╱╲╱ ╲    ← per-lap line chart, sector splits on hover             │
│ ╱    ╳╱     ╲                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

**Grid template:**
- Row 1 (60px): `TopBar` — spans all columns
- Row 2 (1fr): `PositionTower` (left, 280px) | `TelemetryPanel` (center, flexible) | `AgentChatPanel` (right, 320px) — Race Control DynamoDB/API remain for TopBar flag + future agent tools; the feed UI was replaced by the chat shell
- Row 3 (220px): `LapTimeChart` — spans all columns

---

### 6.2 Component Breakdown

| Component | Key Props | Primary Data Source | Live Updates |
|---|---|---|---|
| `TopBar` | `session`, `flagState`, `lapInfo`, `clock`, `connectionStatus`, `onSessionChange` | REST `/sessions/{id}` + WS `flag.change` | Yes |
| `PositionTower` | `positions[]`, `selectedDriverNumber`, `onSelectDriver` | REST `/sessions/{id}/positions` (initial) + WS `position.update` | Yes (rows reorder) |
| `TelemetryPanel` | `driverNumber`, `telemetry`, `tireInfo`, `gaps` | REST `/drivers/{id}` (initial) + WS `car_data.update` | Yes (multi-Hz) |
| `AgentChatPanel` | `sessionKey`, `driverNumber` | Local stub replies until AgentCore; race-control REST/WS still feed TopBar `currentFlag` | Stub only (no live stream yet) |
| `LapTimeChart` | `driverNumbers[]`, `laps[]`, `onScrub` | REST `/sessions/{id}/laps` | On new lap / driver select |

**App-level state (single source of truth):**
- `selectedSession` (string) — set by `TopBar`, drives all data fetches
- `selectedDriverNumber` (number | null) — set by `PositionTower` click, drives `TelemetryPanel` + `LapTimeChart` focus
- `comparisonDrivers` (number[]) — shift-click adds to `LapTimeChart` overlay (max 3)
- `connectionStatus` (`'connecting'` | `'live'` | `'reconnecting'` | `'disconnected'`)
- `sessionMode` (`'live'` | `'historical'`) — derived from session end time vs. now
- `scrubLap` (number | null) — historical only; freezes all panels at this lap

---

### 6.3 UI States — Build All Eight

Every component must handle each of these. Mock each state in Excalidraw (see 6.7).

**1. Initial (no session selected)**
- `TopBar`: dropdown shows "Select a session"
- All other panels: empty state — single line of muted copy ("Pick a session to load the dashboard")
- No WebSocket connection

**2. Loading**
- `TopBar`: populated (session metadata fetch is fast)
- Other panels: skeleton placeholders (gray pulse blocks matching component shape) — no spinners
- `connectionStatus`: yellow dot, "Connecting…"

**3. Live (race in progress)**
- `TopBar`: green dot, "LIVE" badge, flag color as background tint
- `PositionTower`: rows reorder smoothly on position change (200ms transition)
- `TelemetryPanel`: values tick multiple times per second, throttle/brake bars animate
- `AgentChatPanel`: accepts questions with stub acknowledgements (AgentCore wiring later)
- `LapTimeChart`: new lap point appears at right edge

**4. Historical (session ended)**
- `TopBar`: gray "ARCHIVE" badge, lap counter shows final state
- No WebSocket connection
- `LapTimeChart`: scrubable — click any lap to jump the dashboard to that moment
- `PositionTower` / `TelemetryPanel`: reflect the scrubbed moment, not "now"

**5. Reconnecting**
- `TopBar`: yellow dot, "Reconnecting…" with retry countdown
- All panels: frozen on last known data, dimmed 50%
- Auto-retry with exponential backoff: 1s → 2s → 4s → 8s → … max 30s

**6. Disconnected (give up after ~2 min of failed retries)**
- `TopBar`: red dot, "Disconnected" label + manual "Retry" button
- All panels: frozen, dimmed
- Manual retry triggers fresh WebSocket + REST fetch

**7. Error (REST or WS failure for one panel)**
- Affected panel: red-tinted card with copy ("Couldn't load positions — Retry")
- Other panels: unaffected — errors are per-component, not full-page

**8. Empty (valid session, no data yet — e.g., session hasn't started)**
- Affected panel: muted empty state ("No position data for this session yet")
- Distinct from loading and error

---

### 6.4 Interaction Map

| Action | Trigger | Effect |
|---|---|---|
| Select session | `TopBar` dropdown change | REST fetch all panels; open WebSocket if `sessionMode === 'live'` |
| Select driver | Click row in `PositionTower` | `TelemetryPanel` swaps; `LapTimeChart` highlights that driver |
| Compare driver | Shift-click row in `PositionTower` | Adds driver to `LapTimeChart` overlay (max 3) |
| Scrub lap | Click lap point in `LapTimeChart` (historical only) | Sets `scrubLap`; all panels re-render for that moment |
| Ask race engineer | Submit message in `AgentChatPanel` | Appends user + stub assistant reply (AgentCore later) |
| Manual reconnect | Click "Retry" in disconnected state | New WebSocket + REST fetch |

---

### 6.5 Data Flow

**On session select:**
1. `GET /sessions/{id}` → `TopBar` metadata; derive `sessionMode`
2. In parallel: `GET /sessions/{id}/positions`, `/race-control`, `/laps` → initial panel data
3. If `sessionMode === 'live'`: open WebSocket to `{WS_URL}?sessionId={id}`
4. WebSocket pushes events; each updates the relevant panel's state
5. On any new lap (`/laps` poll or WS `lap.complete`), append to `LapTimeChart`

**WebSocket message shape (server → client):**
```json
{ "type": "position.update",     "data": { "driver_number": 1, "position": 2, "ts": "..." } }
{ "type": "car_data.update",     "data": { "driver_number": 1, "speed": 348, "gear": 8, "drs": true, "throttle": 100, "brake": 0 } }
{ "type": "race_control.event",  "data": { "category": "Flag", "flag": "YELLOW", "message": "...", "ts": "..." } }
{ "type": "flag.change",         "data": { "flag": "RED" } }
{ "type": "lap.complete",        "data": { "driver_number": 1, "lap_number": 35, "lap_duration": 84.234 } }
```

**Reconnection protocol:** on WS close, attempt reconnect with exponential backoff. On reconnect, REST re-fetch to fill the gap, then resume WS stream. Show overlay banner if gap > 30s of missing data.

---

### 6.6 Empty / Loading / Error Conventions

- **Loading:** skeleton (gray pulse blocks matching final shape), never spinners — keeps layout stable
- **Empty:** muted gray text, single sentence, no iconography
- **Error:** red-tinted card with copy + "Retry" button, scoped to failing panel only
- **Stale (reconnecting/disconnected):** data frozen + dimmed 50%; `TopBar` status indicator carries the explanation

---

### 6.7 Excalidraw Mockup Checklist

Before writing any React code, produce these frames in Excalidraw:

- [ ] **Frame 1 — Live race view (default):** all five components populated, green `LIVE` badge, green flag
- [ ] **Frame 2 — Historical view:** `ARCHIVE` badge, `LapTimeChart` with a selected lap highlighted, scrubbed state reflected in tower + telemetry
- [ ] **Frame 3 — Loading state:** `TopBar` populated, other panels show skeletons, yellow connecting dot
- [ ] **Frame 4 — Reconnecting state:** yellow dot, panels dimmed, retry countdown visible
- [ ] **Frame 5 — Disconnected state:** red dot, panels frozen + dimmed, manual retry button
- [ ] **Frame 6 — Initial state:** only session dropdown populated, empty-state copy elsewhere
- [ ] **Frame 7 — Error (per-panel):** one panel in red error card, others healthy
- [ ] **Frame 8 — Mobile collapse (stretch):** single-column stacked layout

**Annotations to add on every frame:**
- Data source per component (REST endpoint or WS event name)
- Update frequency where relevant (e.g., "position.update every 5s")
- State shown (live / historical / loading / reconnecting / etc.)

**Storage & export:**
- Keep Excalidraw source at `frontend/docs/wireframes.excalidraw` so it version-controls alongside the code
- Export PNG of Frame 1 (live view) for the README hero image and blog post

---

## 7. Build Phases

**IaC-first approach:** Terraform + GitHub Actions from day one. No console clicking for infrastructure. Write Terraform, push to GitHub, CI/CD deploys.

### Week 1: Foundation + Ingestion Pipeline

**Day 1-2: Repo + Terraform scaffold + CI/CD**
- Create GitHub repo with Terraform module structure (see Section 7)
- Set up GitHub Actions workflow: `deploy-infra.yml` (terraform plan/apply on push to main)
- Terraform: Kinesis Data Stream (1 shard), IAM roles, S3 backend for state
- Write poller Lambda (Python) that polls OpenF1 `/position` and `/car_data`
- Terraform: EventBridge rule (every 5s trigger), poller Lambda, IAM role
- Push to GitHub → CI/CD deploys

**Day 3-4: Verify ingestion + add break-it scenarios**
- Verify records land in Kinesis via CloudWatch metrics (IncomingRecords)
- Add DLQ for failed poller invocations (Terraform)
- Add retry logic for OpenF1 API errors
- Monitor Kinesis iterator age

**Day 5: Break-it**
- What happens when OpenF1 returns errors? (Verify retry logic)
- What happens when Kinesis throttles? (Observe ProvisionedThroughputExceeded)
- What if the poller Lambda times out? (Check timeout, verify DLQ receives events)

**Deliverable:** Data flowing OpenF1 → Lambda → Kinesis. All Terraform-managed. CI/CD working.

---

### Week 2: Processing + Storage

**Day 1-2: DynamoDB + consumer Lambda**
- Terraform: DynamoDB tables (Sessions, Positions, Laps, RaceControl, Connections)
- Write consumer Lambda: reads from Kinesis, transforms, writes to DynamoDB
- Terraform: Kinesis event source mapping, consumer Lambda, IAM role
- Enable DynamoDB Streams on Positions table
- Add poller endpoints: `/laps`, `/race_control`, `/weather`

**Day 3-4: Terraform modules + verify data flow**
- Refactor Terraform into modules (ingestion/, processing/, storage/)
- Verify end-to-end: OpenF1 → Kinesis → Lambda → DynamoDB
- Add idempotent write handling (DynamoDB conditional writes)

**Day 5: Break-it**
- What happens with DynamoDB write throttles? (Switch to on-demand)
- Kill the consumer Lambda — does data back up in Kinesis? (Check iterator age alarm)
- What if duplicate records arrive? (Verify idempotency)

**Deliverable:** OpenF1 data flowing through Kinesis into DynamoDB. Modular Terraform.

---

### Week 3: API Layer + WebSocket + Frontend

**Day 1-2: REST + WebSocket APIs**
- Terraform: REST API Gateway with routes (`GET /sessions`, `GET /sessions/{id}`, `GET /drivers/{id}`)
- Write API Lambda functions (Python) querying DynamoDB
- Terraform: WebSocket API Gateway ($connect, $disconnect, $default routes)
- Write connection manager Lambda + push Lambda (DynamoDB Streams → WebSocket fanout)
- Terraform: all Lambda functions, IAM roles, API Gateway resources

**Day 3-4: Frontend**
- Scaffold React app (Vite + React)
- Build components: Position Tower, Driver Cards, Lap Time Chart, Race Engineer chat shell, Session Selector
- Connect to WebSocket API for live updates
- Connect to REST API for historical data
- Terraform: S3 bucket, CloudFront distribution, OAC policy
- GitHub Actions: `deploy-frontend.yml` (build React, sync to S3, invalidate cache)

**Day 5: Break-it**
- WebSocket client disconnects without $disconnect? (Verify TTL cleanup)
- Load dashboard during non-race weekend? (Should show historical data gracefully)
- WebSocket disconnects mid-race? (Test auto-reconnect logic)

**Deliverable:** Working dashboard accessible via CloudFront URL. REST + WebSocket APIs live.

---

### Week 4: Monitoring + Polish + Demo

**Day 1-2: Observability**
- Terraform: CloudWatch dashboard with panels:
  - Lambda invocations, errors, duration (all functions)
  - Kinesis iterator age, incoming/outgoing records
  - DynamoDB read/write capacity, throttles
  - API Gateway request count, 4xx/5xx rates
  - WebSocket connection count
- Terraform: Alarms (Lambda error rate > 5%, Kinesis iterator age > 60s, DynamoDB throttles > 0) → SNS
- Add X-Ray tracing to Lambda functions

**Day 3: Break-it**
- Intentionally throttle DynamoDB — do alarms fire?
- Introduce a bug in transformer Lambda — does error alarm trigger?
- Verify `terraform destroy` tears everything down cleanly

**Day 4-5: Polish + Demo Prep**
- Load test with historical OpenF1 data (replay a past race weekend)
- Record demo video showing dashboard updating during a session
- Write README (architecture diagram, setup instructions, screenshots, cost report)
- Verify full CI/CD: push a change, watch GitHub Actions deploy

**Deliverable:** Portfolio-ready project. Terraform deploy/destroy clean. CI/CD pipeline working. Demo recorded.

---

## 8. Terraform Module Structure

```
f1-telemetry-dashboard/
├── terraform/
│   ├── main.tf              # Provider, backend config
│   ├── variables.tf          # Environment, region, project name
│   ├── outputs.tf            # CloudFront URL, API endpoints, WebSocket URL
│   ├── modules/
│   │   ├── ingestion/
│   │   │   ├── main.tf       # Kinesis stream, poller Lambda, EventBridge rule
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── processing/
│   │   │   ├── main.tf       # Transformer Lambda, Kinesis consumer, DLQ
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── storage/
│   │   │   ├── main.tf       # DynamoDB tables, streams, GSIs
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── api/
│   │   │   ├── main.tf       # REST API Gateway, WebSocket API, Lambdas
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── frontend/
│   │   │   ├── main.tf       # S3 bucket, CloudFront, OAC
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   └── monitoring/
│   │       ├── main.tf       # CloudWatch dashboard, alarms, SNS
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── environments/
│       └── dev/
│           ├── main.tf       # Module calls with dev values
│           └── terraform.tfvars
├── lambdas/
│   ├── poller/               # OpenF1 API poller
│   ├── transformer/          # Kinesis → DynamoDB processor
│   ├── api_sessions/         # REST: GET /sessions
│   ├── api_drivers/          # REST: GET /drivers
│   ├── ws_connect/           # WebSocket $connect
│   ├── ws_disconnect/        # WebSocket $disconnect
│   └── ws_push/              # DynamoDB Streams → WebSocket fanout
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── .github/
│   └── workflows/
│       ├── deploy-infra.yml  # Terraform plan/apply on push to main
│       └── deploy-frontend.yml # Build React, sync to S3, invalidate cache
└── README.md
```

---

## 9. Cost Estimate

| Service | Free Tier | Expected Usage | Estimated Cost |
|---------|-----------|----------------|----------------|
| Lambda | 1M requests/month, 400K GB-seconds | ~500K invocations/month | $0 (free tier) |
| DynamoDB | 25 RCU, 25 WCU, 25 GB | On-demand: ~2M writes/month | $2-5/month |
| Kinesis | Not free tier | 1 shard, ~720 shard-hours | ~$11/month |
| API Gateway (REST) | 1M calls/month | ~100K requests/month | $0 (free tier) |
| API Gateway (WS) | 1M messages/month | ~500K messages/month | $0 (free tier) |
| S3 | 5 GB, 20K GET | Frontend assets ~50 MB | $0 (free tier) |
| CloudFront | 1 TB transfer, 10M requests | ~5 GB/month | $0 (free tier) |
| CloudWatch | 10 custom metrics, 5 GB logs | Dashboard + alarms | $3-5/month |
| EventBridge | Free for AWS events | Scheduled rules | $0 |

**Total estimated cost: ~$15-20/month** during active development.
**When not in use:** Stop the EventBridge rule and delete the Kinesis stream. Cost drops to ~$0-3/month (DynamoDB storage only).

> **Tip:** Use `terraform destroy` between race weekends to avoid idle costs. Redeploy with `terraform apply` before the next session.

---

## 10. Stretch Goals (After MVP)

These naturally extend this project into a broader multi-source dashboard:

| Priority | Addition | New Services |
|----------|----------|--------------|
| 1 | Add Reddit/Twitter F1 sentiment | EventBridge, Comprehend |
| 2 | Add news feed ingestion | EventBridge, Lambda |
| 3 | Full-text search across all data | OpenSearch |
| 4 | Track map with car positions | AWS Location Service |
| 5 | Historical analytics (past seasons) | S3 data lake, Glue ETL |
| 6 | Race outcome predictions | SageMaker |

Each stretch goal adds 1-2 new AWS services while keeping the existing pipeline intact. This is the upgrade path to a broader multi-source dashboard.

---

## 11. Definition of Done

- [ ] OpenF1 data flows through Kinesis → Lambda → DynamoDB during a live or replayed session
- [ ] REST API returns session, driver, and lap data
- [ ] WebSocket pushes position updates to connected dashboard clients
- [ ] React dashboard displays live position tower, driver cards, lap chart, and race engineer chat shell
- [ ] Frontend served via S3 + CloudFront
- [ ] CloudWatch dashboard shows health of all components
- [ ] At least one alarm configured and tested
- [ ] All infrastructure managed by Terraform (full deploy and destroy works cleanly)
- [ ] GitHub Actions deploys infrastructure and frontend on push to main
- [ ] README with architecture diagram, setup instructions, and screenshots
- [ ] Demo recorded (live or replayed race weekend)
