# F1 Dashboard

Real-time F1 telemetry dashboard with a built-in AI race engineer. Live timing during race weekends, full-session replays year-round, and a chat panel that answers questions about the session using Bedrock.

**Live:** https://f1.zevlo.net

---

## Features

- **Live timing tower** — positions update in real time during race weekends via WebSocket fanout from DynamoDB Streams.
- **Replays with scrubber** — pick any past session, play/pause, cycle speed (1×/4×/10×), scrub the timeline. All client-side, no network round-trips during playback.
- **Driver-focused telemetry** — click any driver to focus; shift-click to layer comparisons on the lap-time chart. Updates are local state, never trigger a refetch.
- **Race Engineer chat** — ask questions in plain English ("Who's leading?", "Compare VER and NOR on sector 2", "What happened on lap 12?"). A Bedrock-backed agent streams the reply and can query the telemetry directly via tools.

## Tech stack

- **Frontend:** React + Vite + TanStack Query + Zustand + Tailwind CSS + Recharts
- **Backend:** Lambda + API Gateway (REST + WebSocket) + Kinesis + DynamoDB
- **AI:** Amazon Bedrock (Nova Pro) via `converse_stream` with 5 telemetry-lookup tools
- **Data source:** [OpenF1](https://openf1.org/) API
- **Infra:** Terraform + GitHub Actions (OIDC, no static keys) + S3/CloudFront + Route 53 + ACM

## API

Base URL: `https://api.f1.zevlo.net/v1`

| Route | Description |
|---|---|
| `GET /sessions` | List sessions |
| `GET /sessions/{key}` | Session metadata |
| `GET /sessions/{key}/drivers` | All 20 drivers (names, teams, colors) in one call |
| `GET /sessions/{key}/replay` | Bulk payload (positions + laps + race control + drivers) for client-side playback |
| `GET /sessions/{key}/positions` | Position samples |
| `GET /sessions/{key}/race-control` | Flags and incidents |
| `GET /sessions/{key}/laps?driver=N&driver=N…` | Lap times, filter by driver |
| `GET /drivers/{n}` | Driver metadata (OpenF1 proxy) |

WebSocket: `wss://ws.f1.zevlo.net/v1?sessionId=<session_key>`

Live events: `position.update`, `car_data.update`, `race_control.event`, `flag.change`, `lap.complete`

Agent: send `{"action": "agent.ask", "text": "...", "sessionKey": "...", "driverNumber": N}` — replies stream back as `agent.token` events followed by `agent.done`.

## Local development

```bash
# Frontend
cd frontend
npm install
cp .env.example .env.local    # fill in the API + WS URLs
npm run dev

# Lambda unit tests
python3 lambdas/<name>/test_handler.py
```

Frontend env vars (`VITE_API_BASE_URL`, `VITE_WS_URL`) come from Terraform outputs:

```bash
cd terraform/environments/dev
terraform output -raw api_base_url
terraform output -raw websocket_url
```

## Project layout

```
frontend/                     React + Vite app
lambdas/                      9 Lambda handlers (Python)
terraform/                    Infra (modules: ingestion, processing, storage, api, dns, frontend, monitoring)
.github/workflows/deploy.yml  CI/CD (infra → frontend, OIDC, no static keys)
docs/                         Planning + reference docs
```
