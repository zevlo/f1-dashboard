# F1 Dashboard

Real-time F1 telemetry dashboard on AWS. Ingests live [OpenF1](https://openf1.org/) telemetry, supports client-side replay of historical sessions, and pairs the timing screen with a Bedrock AgentCore "Race Engineer" chat panel. Serverless, event-driven, fully Infrastructure-as-Code.

> **Status: v2 rebuild in progress.** This repo replaces `zevlo/f1-telemetry-dashboard` with the same goal but a cleaner architecture and a UX-first frontend. See [`docs/v2-build-plan.md`](docs/v2-build-plan.md) for the full plan. Until v2 ships, the old repo at https://github.com/zevlo/f1-telemetry-dashboard remains the source of truth for the live deployment.

---

## What's different from v1

| Area | v1 (old repo) | v2 (this repo) |
|---|---|---|
| Driver metadata | Per-driver `GET /drivers/{n}`, lazy-fetched on click → names didn't show until clicked | New `Drivers` DynamoDB table + bulk `GET /sessions/{key}/drivers`, prefetched on session load |
| Frontend cache | Custom `usePanelData` hook, no shared cache, every click re-fetched | TanStack Query + Zustand — driver click is local state only, zero network |
| Replays | Server-side replay cursor in poller Lambda; transport controls round-trip to backend | Client-side playback from one bulk REST fetch — instant scrub/play/pause/speed |
| Right panel | Stubbed chat shell | Bedrock AgentCore "Race Engineer" (Amazon Nova Pro), streaming via WS, telemetry-lookup tools |
| Live mode | WS fanout via DynamoDB Streams (unchanged) | WS fanout via DynamoDB Streams (kept as-is — it worked) |
| Backend | 7 Lambdas, 5 DDB tables, server-side replay cursor | 9 Lambdas (added `api-replay` + `ws-agent`), 6 DDB tables (added `Drivers`), no server-side replay cursor |

## Architecture (target)

```
                          ┌──────────────────────────────────────────┐
                          │               INGESTION                  │
    OpenF1 API ──────────►│  EventBridge (60s) → poller Lambda       │
    /position             │   ├── live mode:    auto-discover active │
    /car_data             │   │                 session, ~5s cadence │
    /race_control         │   │                 + upsert 20 drivers  │
    /laps                 │   └── (replay mode removed — client-side)│
    /sessions             │                  └──► Kinesis Data Stream│
    /drivers              └──────────────────┬───────────────────────┘
                                            │
                                            ▼
                          ┌──────────────────────────────────────────┐
                          │              PROCESSING                  │
                          │  transformer Lambda (Kinesis consumer)   │
                          │   ├── normalize + envelope by source     │
                          │   └── idempotent put → DynamoDB          │
                          └──────────────────┬───────────────────────┘
                                            │
                                            ▼
                          ┌──────────────────────────────────────────┐
                          │                STORAGE                   │
                          │  DynamoDB (on-demand, PITR, Streams)     │
                          │   ├── Sessions   (PK: session_key)       │
                          │   ├── Drivers    (PK: session_key,       │
                          │   │                SK: driver_number)    │
                          │   ├── Positions  (PK: session_key)       │
                          │   ├── CarData    (PK: session#driver)    │
                          │   ├── Laps       (PK: session#driver)    │
                          │   └── RaceControl(PK: session_key)       │
                          └──────┬───────────────────────┬───────────┘
                                 │                       │
                   (query)       ▼                       ▼ (DynamoDB Streams)
                          ┌──────────────────┐   ┌───────────────────────┐
                          │  REST API GW     │   │ ws-push Lambda        │
                          │  /sessions …     │   │  → WebSocket fanout   │
                          │  /sessions/{k}/  │   │  (live mode only)     │
                          │   drivers        │   │                       │
                          │  /sessions/{k}/  │   │ ws-agent Lambda       │
                          │   replay         │   │  → Bedrock AgentCore  │
                          │  /drivers/{n}    │   │    stream relay       │
                          └────────┬─────────┘   └───────────┬───────────┘
                                   │                         │
                                   ▼                         ▼
                          ┌──────────────────────────────────────────┐
                          │                DELIVERY                  │
                          │  React 19 + Vite + TanStack Query +      │
                          │  Zustand → S3 + CloudFront (OAC)         │
                          │   REST for initial load + bulk replay,   │
                          │   WebSocket for live ticks + agent       │
                          │   streaming                              │
                          └──────────────────────────────────────────┘
```

## Stack
- **Ingestion:** EventBridge (60s) → poller Lambda (live mode only) → Kinesis Data Stream
- **Processing:** transformer Lambda (Kinesis consumer) → DynamoDB (idempotent puts)
- **Storage:** DynamoDB — 6 telemetry tables (on-demand, PITR, Streams) + WebSocket Connections table
- **Delivery:** API Gateway REST (queries + bulk replay) + WebSocket (live fanout + agent streaming)
- **Agent:** Bedrock AgentCore (Amazon Nova Pro) + `ws-agent` Lambda relay
- **Frontend:** React 19 + Vite + TanStack Query + Zustand + Tailwind 4 + Recharts → S3 + CloudFront (OAC)
- **DNS:** Route 53 + ACM → `f1.zevlo.net` (+ `api.` / `ws.` subdomains)
- **Ops:** CloudWatch dashboard + SNS alarms
- **IaC:** Terraform + GitHub Actions CI/CD (OIDC, no static keys)

Region: `us-east-1`. State: S3 `f1-telemetry-tf-state` / `dev/terraform.tfstate` (lockfile + encrypt).

## Live endpoints (post-rebuild)
After Phase 6 cutover, these will be the same URLs as v1:

| Output | URL |
|---|---|
| `dashboard_url` | https://f1.zevlo.net |
| `api_base_url` | https://api.f1.zevlo.net/v1 |
| `websocket_url` | wss://ws.f1.zevlo.net/v1 |

REST routes (target):
- `GET /sessions` — list sessions
- `GET /sessions/{sessionKey}` — session metadata
- `GET /sessions/{sessionKey}/drivers` — **all 20 drivers at once** (fixes the v1 "names don't show" bug)
- `GET /sessions/{sessionKey}/replay` — **bulk positions + laps + race-control + telemetry summary for client-side playback**
- `GET /sessions/{sessionKey}/positions` — position samples
- `GET /sessions/{sessionKey}/race-control` — flags / incidents
- `GET /sessions/{sessionKey}/laps?driver=<n>&driver=<n>…` — lap times (filter by driver)
- `GET /drivers/{driverNumber}` — driver metadata (proxies OpenF1)

WebSocket events (target):
- Live mode: `position.update`, `car_data.update`, `race_control.event`, `flag.change`, `lap.complete`
- Agent: client sends `{action: 'agent.ask', text, sessionKey, driverNumber}`, server streams back `{type: 'agent.token', ...}` + `{type: 'agent.done', ...}`

## Build status
- [x] Phase 0 — pre-flight snapshot of v1 (at `/var/folders/.../f1-v2-snapshot`)
- [x] Phase 1 — new repo + skeleton (this commit)
- [x] Phase 1.5 — update `github-oidc-f1-telemetry` role trust to include `zevlo/f1-dashboard` (now `repo:zevlo/f1-*:*`, forward-compatible)
- [x] Phase 2 — Terraform: `state rm` ACM cert (Route 53 zone was already a data source), `destroy`, rebuild with `Drivers` table + new endpoints (162 added, 0 destroyed)
- [x] Phase 3 — Lambdas: rewrote poller + api-drivers; added api-replay + ws-agent (stub); carried transformer/api-sessions/ws-connect/ws-disconnect/ws-push from v1
- [x] Phase 4 — Frontend: React + Vite + TanStack Query + Zustand + Tailwind
- [x] Phase 5 — AgentCore integration (Amazon Nova Pro)
- [ ] Phase 6 — Big-bang PR to main → CI apply → CloudFront invalidation → verify at https://f1.zevlo.net
- [ ] Phase 7 — Delete old `zevlo/f1-telemetry-dashboard` repo

See [`docs/v2-build-plan.md`](docs/v2-build-plan.md) for the full plan with phase-level detail.

## Project layout (target)
```
terraform/
  environments/dev/          # dev entrypoint (main.tf, variables.tf, outputs.tf)
  modules/{ingestion,processing,storage,api,dns,frontend,monitoring,agent}/
lambdas/{poller,transformer,api-sessions,api-drivers,api-replay,
         ws-connect,ws-disconnect,ws-push,ws-agent}/
frontend/                    # React + Vite (src/, docs/)
.github/workflows/deploy.yml # CI/CD (OIDC → infra job → frontend job)
docs/                        # planning + reference docs
```

## Reference
- [`docs/v2-build-plan.md`](docs/v2-build-plan.md) — full rebuild plan
- [`docs/f1-telemetry-dashboard-v1-reference.md`](docs/f1-telemetry-dashboard-v1-reference.md) — v1 architecture (for context)
- [`docs/f1-race-engineer-agent.md`](docs/f1-race-engineer-agent.md) — AgentCore planning
- [`AGENTS.md`](AGENTS.md) — OpenF1 quirks, idempotency rules, agent build instructions
