# F1 Dashboard v2 — Build Plan

**Created:** 2026-07-20
**Source:** kickoff interview + Phase 0 snapshot of v1 (`zevlo/f1-telemetry-dashboard`)
**Status:** Phase 1 complete. Phases 2–7 pending.

---

## Decisions captured in the kickoff interview

| Area | Decision |
|---|---|
| Wipe scope | Full nuke. New repo `zevlo/f1-dashboard`, fresh git history. Delete old repo after v2 verifies. |
| AWS reuse | Reuse account, Route 53 `zevlo.net` zone, ACM certs, S3 tfstate bucket, GitHub OIDC IdP. Nuke DynamoDB tables (data loss acceptable). |
| Frontend stack | React 19 + Vite + TypeScript + TanStack Query + Zustand + Tailwind 4 + Recharts. |
| Backend | All 7 v1 Lambdas rewritten. 2 added (`api-replay`, `ws-agent`). 6 DynamoDB tables (was 5, added `Drivers`). |
| Replay transport | Client-side. One bulk REST fetch, local clock for play/pause/speed. No server-side replay cursor. |
| Live transport | WebSocket via DynamoDB Streams (kept from v1, it worked). |
| Agent | Bedrock AgentCore runtime + `ws-agent` Lambda relay. Amazon Nova Pro. Telemetry-lookup tools only. |
| Right panel | AgentCore chat (replaces v1 race-control panel). Flags surface as a slim banner under TopBar. |
| Layout | 3 columns: PositionTower (left) / TelemetryPanel + LapTimeChart stacked (middle) / AgentChatPanel (right). TopBar + flag banner on top. |
| Visual | Broadcast timing-screen aesthetic. Dark, dense, team-color-coded. Desktop-only (1440px+). |
| Auth | Public dashboard, no login. |
| Domain | Reuse `f1.zevlo.net` + `api.` + `ws.` |
| Tests | Lambda pytest unit tests + Vitest for derive fn + Playwright smoke. No coverage bar. |
| CI/CD | Same pattern as v1: GitHub Actions + OIDC. Big-bang PR to main. |
| v1 cuts | Multi-driver comparison (keep, up to 2 extra), session picker (keep), tyre info (cut), DRS/speed traps (cut). |

## Pain points being fixed

| Pain | Root cause in v1 | Fix in v2 |
|---|---|---|
| Drivers show as numbers until clicked | Only endpoint was per-driver `/drivers/{n}`, lazy-fetched | New `Drivers` table + bulk `GET /sessions/{key}/drivers`; prefetched on session load via TanStack Query |
| Each click causes whole refresh | `usePanelData` re-fetched on dep change; no shared cache | TanStack Query with stable cache keys; driver click only mutates Zustand UI state — zero network |
| Live updates feel slow | Per-tick REST invalidation patterns | Keep WS for live mode (worked); replays are client-side, no transport round-trips |

---

## Phase 0 — Pre-flight snapshot (DONE 2026-07-20)

Captured at `/var/folders/z6/gvc0hbp90lg2hkn71stbn2xm0000gn/T/opencode/f1-v2-snapshot/`:

- Full repo working tree (excludes `.git`, `node_modules`, `.terraform`) — 648 KB
- Terraform state backup from S3 — 391 KB
- Terraform outputs JSON (all URLs/ARNs/table names)
- IAM/Route53/ACM evidence
- Git log + branches + remotes + uncommitted diff

**Critical findings flagged:**
1. Route 53 `zevlo.net` zone + ACM cert `f1.zevlo.net` ARE in v1 TF state. `terraform destroy` would delete them. **Must `terraform state rm` BEFORE destroy.**
2. `github-oidc-f1-telemetry` role trust is locked to `repo:zevlo/f1-telemetry-dashboard:*`. **Must update to include `repo:zevlo/f1-dashboard:*` BEFORE first v2 CI run.**

## Phase 1 — New repo + skeleton (DONE 2026-07-20)

- Created `zevlo/f1-dashboard` (public, matches v1 visibility)
- Cloned to `/Users/za/projects/f1-dashboard`
- Seeded: `.gitignore`, `README.md`, `AGENTS.md`, `docs/v2-build-plan.md`, `docs/f1-telemetry-dashboard-v1-reference.md`, `docs/f1-race-engineer-agent.md`, `docs/wireframe-v0-prompt.md`
- Directory skeleton: `terraform/{environments/dev,modules/*}/`, `lambdas/*`, `frontend/`, `.github/workflows/`

## Phase 1.5 — Update GitHub OIDC trust (PENDING)

Before any v2 CI run, update the trust policy on `github-oidc-f1-telemetry` (ARN `arn:aws:iam::746669194590:role/github-oidc-f1-telemetry`) to include the new repo:

```bash
# Update the StringLike condition to allow both repos (forward-compatible)
aws iam update-assume-role-policy \
  --role-name github-oidc-f1-telemetry \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::746669194590:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:zevlo/f1-*:*"
        }
      }
    }]
  }'
```

## Phase 2 — Terraform (PENDING)

**Order matters.** Run all of this from the OLD repo's `terraform/environments/dev/` (since state currently lives there):

1. `terraform init` (refresh local .terraform)
2. Orphan the parent zone + ACM cert (so destroy doesn't delete them):
   ```
   terraform state rm module.dns.aws_route53_zone.parent
   terraform state rm module.dns.aws_acm_certificate.this
   terraform state rm module.dns.aws_acm_certificate_validation.this
   ```
3. `terraform destroy -auto-approve` (removes everything else — DDB tables, lambdas, APIs, CloudFront, frontend bucket)
4. Copy the now-pruned tfstate into the new repo (or rely on remote S3 state — `terraform init` in the new repo will pull it)

In the new repo:
5. Author new Terraform: same module structure as v1 + new `agent` module + `Drivers` table in storage module + new REST routes in api module + `ws-agent` Lambda route in api module + `api-replay` Lambda in api module.
6. Import the preserved zone + cert:
   ```
   terraform import module.dns.aws_route53_zone.parent Z065948732114TULELWJE
   terraform import module.dns.aws_acm_certificate.this 'arn:aws:acm:us-east-1:746669194590:certificate/3a6f873e-da3c-4f8b-8007-73ff60746916'
   ```
7. `terraform plan` — should show only adds (no changes to imported resources). Manually review.
8. `terraform apply` — recreates everything clean.

## Phase 3 — Lambdas (PENDING)

9 Lambdas total. v1 contracts documented in `docs/f1-telemetry-dashboard-v1-reference.md`.

| Lambda | Responsibility | Notes vs v1 |
|---|---|---|
| `poller` | **Live mode only.** EventBridge 60s trigger; auto-discover active session; loop internally at ~5s. On session discovery, also fetch + upsert all 20 drivers to `Drivers` table. | Drop `replay_session_key`, `replay_speed`, SSM cursor logic entirely. |
| `transformer` | Kinesis consumer, normalize, idempotent DDB put across 5 telemetry tables | Mostly unchanged from v1 (keep the conditional-put idempotency). |
| `api-sessions` | `GET /sessions`, `GET /sessions/{key}` | Unchanged contract. |
| `api-drivers` | `GET /sessions/{key}/drivers` — bulk Query DDB `Drivers` by PK | **New bulk endpoint.** Replaces per-driver lazy fetch. |
| `api-replay` | `GET /sessions/{key}/replay` — fan-out reads positions/laps/race-control/telemetry-summary from DDB, single response | **New.** Payload can be a few MB for a full session — acceptable per kickoff. |
| `ws-connect`/`ws-disconnect` | Connection table management | Unchanged. |
| `ws-push` | DynamoDB Streams → WS fanout for live mode only | Unchanged. |
| `ws-agent` | **New.** Parse `agent.ask` action, invoke Bedrock AgentCore stream, forward tokens back to `ConnectionId`. | Tools: `get_session`, `get_standings`, `get_driver_laps`, `get_telemetry_sample`, `get_race_control` (read-only). |

## Phase 4 — Frontend (PENDING)

**Stack:** Vite + React 19 + TypeScript + TanStack Query v5 + Zustand + Tailwind 4 + Recharts.

**Folder layout:**
```
frontend/src/
  main.tsx
  App.tsx
  queryClient.ts           # TanStack Query setup
  store/
    sessionStore.ts        # selectedSessionKey, mode
    driverStore.ts         # selectedDriverNumber, comparisonDrivers[]
    replayStore.ts         # isPlaying, speed, scrubTs
  api/
    client.ts              # fetch wrappers
    hooks.ts               # useSessions, useSession, useDrivers, useReplay, useLaps
  ws/
    useWebSocket.ts        # single connection per session
    types.ts
  components/
    TopBar.tsx
    FlagBanner.tsx
    PositionTower.tsx
    TelemetryPanel.tsx
    LapTimeChart.tsx
    ReplayControls.tsx
    AgentChatPanel.tsx
    Panel.tsx              # shared shell
  derive/
    towerRows.ts
    telemetryAt.ts         # client-side cutoff for replay
  types.ts
```

**Key behaviors:**
- **On session load:** parallel-prefetch `useSession`, `useDrivers`, `useReplay` via TanStack Query. Drivers cache is keyed by session_key; never re-fetched within a session.
- **Driver click:** only writes to `driverStore` — no network. Tower/telemetry/chart all subscribe to the store and re-render against cached data only.
- **Live mode:** WS pushes merge into the query cache via `queryClient.setQueryData`. Tower updates inline (no flash).
- **Replay mode:** `ReplayControls` drives a `requestAnimationFrame` clock. `scrubTs` in `replayStore` is the single source of truth; all components derive their visible state via `telemetryAt(data, scrubTs)`. Play/pause/speed mutate the clock — zero network.
- **Agent chat:** single input, messages stream token-by-token via WS `agent.token` events. Suggested-prompt chips above input ("Who's leading?", "Compare VER and NOR on sector 2", "What happened on lap 12?").

## Phase 5 — AgentCore integration (PENDING)

1. Define AgentCore agent with Amazon Nova Pro via Terraform `agent` module.
2. Define 5 tools in the agent spec — Lambda-backed (cleaner) preferred over inline DDB queries in `ws-agent`:
   - `get_session(session_key)` → session metadata
   - `get_standings(session_key)` → current positions (live) or at scrubTs (replay)
   - `get_driver_laps(session_key, driver_number, [lap_range])` → lap times + sectors
   - `get_telemetry_sample(session_key, driver_number, [ts])` → latest car_data sample
   - `get_race_control(session_key, [since_ts])` → flags / incidents
3. `ws-agent` Lambda uses `bedrock-agentcore` SDK `InvokeStream` API; pipes chunks to `apigatewaymanagementapi.post_to_connection(ConnectionId, {type: 'agent.token', ...})`.
4. Frontend renders assistant message in chunks as tokens arrive.
5. Conversation memory: in-memory per connectionId for v1 (lost on cold start). Promote to DDB `AgentSessions` table later if needed.

## Phase 6 — CI/CD + cutover (PENDING)

1. Author `.github/workflows/deploy.yml` (mirror v1: infra job → frontend job, OIDC, no static keys).
2. New OIDC role trust applied (Phase 1.5).
3. **Big-bang PR:** build everything on `feat/v2-rebuild` branch, do final review, merge to `main`. CI apply swaps S3 contents + CloudFront invalidation. Old repo stays available until v2 is verified live.
4. Verify: `terraform output dashboard_url` → open https://f1.zevlo.net → smoke test:
   - Live session loads (or replay session loads if off-season)
   - All 20 drivers show as names immediately (no click required)
   - Click a driver — telemetry updates, no network in DevTools
   - Switch sessions — first paint <500ms from cache
   - Scrub a replay — all panels reflect the new moment without network
   - Agent chat — type a question, tokens stream back
5. Once verified: delete `zevlo/f1-telemetry-dashboard` GitHub repo.

## Phase 7 — Tests + polish (PENDING)

- Lambda pytest: handler logic per lambda, especially poller driver-discovery + transformer idempotency.
- Frontend Vitest: `derive/*` pure functions + TanStack Query hooks with MSW.
- Playwright smoke: live loads, session switch, driver click doesn't refetch, agent chat returns a streamed reply.

---

## Open implementation questions (resolve when we hit each phase)

1. **AgentCore conversation memory** — in-memory per connection (lost on Lambda cold start) vs new `AgentSessions` DynamoDB table?
2. **Replay bulk endpoint payload size** — a full session's positions can be ~100k samples. Paginate, downsample to 1Hz, or accept the few-MB payload?
3. **Agent tool implementation** — Lambda function per tool (cleaner, more IAM boundary) vs inline DDB queries in `ws-agent` (fewer moving parts)?
4. **`api-replay` shape** — should it also include a downsampled telemetry time-series per driver for charting, or just positions/laps/race-control?
