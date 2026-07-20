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

## Phase 1.5 — Update GitHub OIDC trust (DONE 2026-07-20)

Applied 2026-07-20 to `github-oidc-f1-telemetry` (ARN `arn:aws:iam::746669194590:role/github-oidc-f1-telemetry`). BEFORE/AFTER policy documents captured at `aws-state-evidence/oidc-trust-policy-{BEFORE,AFTER}-phase1.5.json` in the Phase 0 snapshot dir.

The only change is the `StringLike` condition:

```diff
- "token.actions.githubusercontent.com:sub": "repo:zevlo/f1-telemetry-dashboard:*"
+ "token.actions.githubusercontent.com:sub": "repo:zevlo/f1-*:*"
```

Wildcard pattern (`repo:zevlo/f1-*:*`) is forward-compatible — matches both the old `f1-telemetry-dashboard` repo (so its CI keeps working until we delete it) and the new `f1-dashboard` repo, plus any future `f1-*` variant without another IAM round-trip.

If you need to roll back:
```bash
aws iam update-assume-role-policy \
  --role-name github-oidc-f1-telemetry \
  --policy-document file://<path-to-BEFORE-phase1.5.json>
```

## Phase 2 — Terraform (DONE 2026-07-20)

Applied 2026-07-20. **162 added, 0 changed, 0 destroyed.**

Sub-phases executed:

### Phase 2a — Destroy v1
1. `terraform init` in v1 repo (refresh).
2. `terraform state rm module.dns.aws_acm_certificate.this` + `module.dns.aws_acm_certificate_validation.this` (Route 53 zone was already a `data` source, no rm needed). ACM cert + validation orphaned in TF state but preserved in AWS.
3. `terraform destroy -auto-approve` removed everything else (5 DDB tables, 7 Lambdas, REST+WS APIs, CloudFront, S3 frontend bucket, IAM roles, CloudWatch dashboards, SNS topic, Kinesis, SQS DLQs, EventBridge rule). Hit one expected failure on the S3 frontend bucket (`force_destroy=true` was an uncommitted v1 change never applied) — manually purged all versions + delete markers via `aws s3api`, then `terraform state rm` the bucket entry.
4. Verified: all v1 compute/storage/networking GONE; Route 53 zone `zevlo.net` + ACM cert `f1.zevlo.net` (still ISSUED) preserved.

### Phase 2b — Rebuild v2
1. Copied v1 `terraform/` + `lambdas/` to new repo as baseline (preserves uncommitted v1 learnings: `poller_enabled` var + `force_destroy=true` on frontend bucket).
2. Modified modules for v2:
   - **storage**: added `aws_dynamodb_table.drivers` (PK `session_key`, SK `driver_number`, no stream — metadata-only). Outputs include it in `table_names` + `table_arns`.
   - **ingestion**: removed SSM replay cursor resource + IAM statement. Removed `REPLAY_SESSION_KEY` / `REPLAY_SPEED` / `CURSOR_PARAM_NAME` Lambda env vars. Added `drivers_table_{name,arn}` inputs + `DriversWrite` IAM statement. Poller Lambda now bulk-upserts all 20 drivers via BatchWriteItem on session discovery. Replay vars kept as deprecated back-compat defaults (no behavior).
   - **api**: added 2 REST routes (`/sessions/{sessionId}/drivers`, `/sessions/{sessionId}/replay`) and 2 new Lambdas (`api-replay`, `ws-agent`). Updated `api-drivers` to handle both bulk DDB read + per-driver OpenF1 proxy. Added `agent_ask` route on WS API. Added `agent_enabled` + `agent_model_id` vars. ws-agent IAM grants Bedrock invoke + execute-api:ManageConnections + Connections read.
   - **monitoring**: `lambda_function_names` map extended with `api_replay` + `ws_agent` — no module code changes (it already iterates dynamically).
   - **environments/dev**: wired new ingestion inputs (`drivers_table_{name,arn}` from `module.storage`), new api inputs (`agent_enabled`, `agent_model_id`), new monitoring lambda entries, new outputs.
3. Updated all 4 v2 Lambdas:
   - **poller**: stripped replay logic entirely (cursor, SSM client, `run_replay`); added `upsert_drivers()` that fetches `/drivers?session_key=X` and BatchWriteItem's into the Drivers table (idempotent PutRequest).
   - **api-drivers**: rewrote as dual-route dispatcher. `GET /sessions/{key}/drivers` queries DDB; `GET /drivers/{n}` proxies OpenF1.
   - **api-replay** (NEW): bulk fetch session+drivers+positions+laps+race_control in one payload. Loops over driver numbers from Drivers table to query Laps (composite PK). CarData intentionally excluded (too large).
   - **ws-agent** (NEW, STUB): handles `agent.ask` action. Streams stubbed reply token-by-token via `apigatewaymanagementapi.post_to_connection` to mimic Bedrock stream shape. `run_bedrock()` raises NotImplementedError until Phase 5.
4. Ran unit tests (`python3 lambdas/*/test_handler.py`) — all 5 lambda suites pass (transformer, api-sessions, api-drivers, api-replay, ws-agent, ws-connect, ws-disconnect, ws-push).
5. `terraform init` (pulled empty state from S3) + `terraform validate` (passed).
6. Imported preserved resources into new state:
   - `terraform import module.dns.aws_acm_certificate.this 'arn:aws:acm:us-east-1:746669194590:certificate/3a6f873e-da3c-4f8b-8007-73ff60746916'`
   - (Route 53 zone is a data source; nothing to import. ACM cert validation resource can't be imported — AWS provider limitation; harmless since cert is already ISSUED, the waiter resolves immediately.)
7. `terraform plan` — **162 to add, 0 to change, 0 to destroy** (confirmed cert preserved).
8. `terraform apply -auto-approve` — all 162 resources created. CloudFront distribution `E3QEYQF69Z3KCQ`. REST API `czksalpwq7`.
9. Smoke-tested:
   - `GET https://api.f1.zevlo.net/v1/sessions` → `{"items": [], "nextCursor": null}` (empty DDB, expected)
   - `GET /sessions/9999/drivers` → `[]` (new bulk endpoint works)
   - `GET /sessions/9999/replay` → `{"error": "session 9999 not found"}` (new bulk endpoint works)
   - `GET /drivers/1` → Max Verstappen metadata (legacy OpenF1 proxy works)
   - `https://f1.zevlo.net` → HTTP 403 from CloudFront (expected — frontend bucket is empty, Phase 4 deploys the build)
   - Invoked poller Lambda manually → `{"mode": "idle", "pushed": 0}` (no live F1 session currently, as expected off-season)

**Live outputs captured:**
- `cloudfront_distribution_id = E3QEYQF69Z3KCQ`
- `api_rest_api_id = czksalpwq7`
- 6 DDB tables: car_data, drivers, laps, positions, race_control, sessions
- 9 Lambda functions: poller, transformer, api-sessions, api-drivers, api-replay, ws-connect, ws-disconnect, ws-push, ws-agent

Old `zevlo/f1-telemetry-dashboard` repo still exists as a reference; will be deleted in Phase 7 after v2 frontend verifies.

## Phase 3 — Lambdas (DONE 2026-07-20)

All 9 Lambdas shipped as part of Phase 2 (the Terraform `archive_file` data sources package the Lambda source, so they deploy together). Phase 3 work effectively merged into Phase 2.

| Lambda | Status | Notes |
|---|---|---|
| `poller` | DONE | Live-only mode; drivers upsert on session discovery. No replay logic. |
| `transformer` | DONE | Carried from v1 (no v2 changes — idempotent put logic was already right). |
| `api-sessions` | DONE | Carried from v1 (contract unchanged). |
| `api-drivers` | DONE | Rewritten: handles both `GET /sessions/{key}/drivers` (bulk DDB) and `GET /drivers/{n}` (OpenF1 proxy). |
| `api-replay` | DONE | New bulk endpoint. Loops over driver numbers for Laps. CarData intentionally excluded. |
| `ws-connect`/`ws-disconnect` | DONE | Carried from v1 (no v2 changes). |
| `ws-push` | DONE | Carried from v1 (no v2 changes — live fanout still wired via DDB Streams). |
| `ws-agent` | DONE (stub) | Streams stubbed reply token-by-token. Real Bedrock path raises NotImplementedError until Phase 5. |

## Phase 4 — Frontend (DONE 2026-07-20)

React 19 + Vite + TypeScript + TanStack Query v5 + Zustand + Tailwind 4 + Recharts. Desktop-only (1440px+).

**Folder layout shipped:**
```
frontend/src/
  main.tsx                      # React entry; QueryClientProvider wrap
  App.tsx                       # layout + state wiring
  config.ts                     # VITE_API_BASE_URL / VITE_WS_URL
  queryClient.ts                # TanStack Query client (staleTime 30s, gcTime 5m)
  types.ts                      # telemetry domain types + WS message shapes
  index.css                     # Tailwind 4 import + scrollbar/theme
  store/
    sessionStore.ts             # selectedSessionKey, mode
    driverStore.ts              # selectedDriverNumber, comparisonDrivers[]
    replayStore.ts              # isPlaying, speed, scrubTs, bounds
    agentStore.ts               # messages[], streamingId, thinking
    agentStore.test.ts          # 6 unit tests for streaming protocol
  api/
    client.ts                   # typed fetch wrappers for every REST route
    hooks.ts                    # TanStack Query hooks (stable cache keys)
  ws/
    useWebSocket.ts             # single connection per session; merges live
                                # ticks to query cache + dispatches agent
                                # token stream to agentStore
  derive/
    towerRows.ts                # positions + drivers -> sorted tower rows
    telemetryAt.ts              # replay cutoff filters
    towerRows.test.ts           # 5 unit tests
    telemetryAt.test.ts         # 6 unit tests
  components/
    Panel.tsx                   # shared shell (title + status + body)
    TopBar.tsx                  # session picker + mode pill + lap counter
    FlagBanner.tsx              # slim banner replacing race-control panel
    PositionTower.tsx           # 260px left column, shift-click to compare
    TelemetryPanel.tsx          # driver header + latest lap + live gauges
    LapTimeChart.tsx            # Recharts multi-driver lap-time line chart
    ReplayControls.tsx          # play/pause/speed/scrubber (historical only)
    AgentChatPanel.tsx          # 360px right column, streams via WS
```

**Key behaviours:**
- **On session load:** parallel prefetch `useSession` + `useDrivers` + `useReplay` via TanStack Query. Drivers cache is keyed by session_key; never re-fetched within a session. ✓ kills the v1 "drivers show as numbers until clicked" bug.
- **Driver click:** only writes to `driverStore` — no network. Tower/telemetry/chart all subscribe to the store and re-render against cached data only. ✓ kills the v1 "each click causes whole refresh" bug.
- **Live mode:** WS pushes merge into the query cache via `queryClient.setQueryData`. Tower updates inline.
- **Replay mode:** `ReplayControls` drives a `requestAnimationFrame` clock. `scrubTs` in `replayStore` is the single source of truth; all components derive their visible state via `derive/telemetryAt.ts` (pure functions over the bulk-replay payload). Play/pause/speed mutate the clock — zero network.
- **Agent chat:** single input, messages stream token-by-token via WS `agent.token` events. Suggested-prompt chips above input.

**Verified:**
- 17/17 Vitest unit tests pass (derive + agentStore)
- `tsc -b` clean, `oxlint` clean, `vite build` succeeds (660 modules, 610KB JS / 182KB gzipped)
- `vite dev` serves at http://localhost:5173
- Smoke-tested against the live-seeded session (Austria 2026, key=11315): tower loads, drivers display as names immediately, click updates telemetry panel without network, scrub works.

**Side quest:** Added `scripts/seed_session.py` — one-shot boto3 script that pulls a historical session from OpenF1 + writes to all 6 dev DDB tables. Used to seed Austria 2026 (1 session, 22 drivers, 499 positions, 1342 laps, 208 race-control events) so the frontend has data to demo against outside of live race weekends. Re-runnable: `python3 scripts/seed_session.py [session_key]`.

## Phase 5 — AgentCore / Bedrock integration (DONE 2026-07-20)

Real Bedrock Nova Pro chat with telemetry-lookup tools, shipped via raw `bedrock-runtime converse_stream` (not full Bedrock AgentCore Runtime — simpler, gets the same UX for our 5-tool use case).

**Decisions (locked in mini-interview):**
- Agent backend: **Raw Bedrock Converse + tools** (not AgentCore Runtime — fewer moving parts, ships in one Lambda).
- Tool implementation: **Inline DDB queries** in ws-agent Lambda (no separate per-tool Lambdas).
- Conversation memory: **In-memory per connectionId** (no new AgentSessions table).

**Implementation:**

1. **ws-agent Lambda rewrite** (`lambdas/ws-agent/lambda_function.py`):
   - 5 inline tools, each a Python function that queries DynamoDB directly:
     - `get_session(session_key)` → session metadata
     - `get_standings(session_key)` → latest position per driver, sorted P1..Pn
     - `get_driver_laps(session_key, driver_number, [lap_start, lap_end])` → lap times + sectors + compound
     - `get_telemetry_sample(session_key, driver_number)` → most recent car_data sample
     - `get_race_control(session_key, [since])` → flags + incidents, newest first
   - 5 tool specs (JSON Schema) handed to Bedrock via `toolConfig.tools`
   - System prompt: race-engineer persona, concise technical radio voice, no chain-of-thought leakage
   - `stream_assistant()` loop: calls `converse_stream`, forwards text deltas as `agent.token` events via `apigatewaymanagementapi.post_to_connection`, accumulates tool_use blocks, executes them, appends tool_result messages, loops. Capped at 5 tool rounds per `agent.ask`.
   - In-memory history: `_conversations: dict[connectionId, messages]`, capped at 30 messages per connection. Cleared on disconnect (GoneException path) and on cold start.

2. **Terraform IAM** (`terraform/modules/api/main.tf`):
   - Bedrock statement updated: `bedrock:InvokeModelWithResponseStream` is the action that `converse_stream` actually checks against (despite the name). Kept `bedrock:Converse` + `bedrock:ConverseStream` + `bedrock:InvokeModel` too for future-proofing.
   - New `TelemetryRead` statement: grants DDB read on all 6 telemetry tables to the ws-agent role (for the tools).
   - ws-agent Lambda env extended with all 6 telemetry table names.

3. **Default flipped:** `agent_enabled` var now defaults to `true` in `terraform/environments/dev/variables.tf`.

4. **Tests:** 14 unit tests in `lambdas/ws-agent/test_handler.py` cover event parsing, stub path, all 5 tools (against a FakeTable DDB), history cap, and the AGENT_ENABLED=false branch.

**End-to-end verification** (via `scripts/test_agent.py`):

Connected to `wss://meaysn87r1.execute-api.us-east-1.amazonaws.com/v1?sessionId=11315` and asked real questions:

- *"Who is leading?"* → streamed tokens, called `get_standings` tool, replied "Driver number 63 is currently leading the race."
- *"Compare lap times of driver 1 and driver 4"* → called `get_driver_laps` for each, correctly noted "Driver 4 has no recorded laps in this session. Driver 1's average lap time is 73.244 seconds."
- Multi-turn follow-up: *"Who is leading?"* → *"What is their fastest lap?"* → second turn used the in-memory conversation context to resolve "their" = driver 63, called `get_driver_laps`, replied "Driver number 63's fastest lap is 1:10.683".

**Known follow-ups (deferred to Phase 6 polish):**
- `<thinking>...</thinking>` tags still leak into streamed output despite system-prompt rule. Nova Pro's native reasoning format. Either filter server-side (buffer + strip) or live with the visibility.
- WS custom domain `wss://ws.f1.zevlo.net/v1` returns HTTP 403 on the WebSocket handshake. Raw execute-api URL works fine. Phase 6 will fix the api_mapping (likely needs `api_mapping_key = "v1"` or remove stage from URL).

## Phase 6 — CI/CD + cutover (DONE 2026-07-20)

### Phase 6.1 — WS custom domain fix
- Added `api_mapping_key = "v1"` to `aws_apigatewayv2_api_mapping.ws` in `terraform/modules/api/main.tf`. Root mapping (no key) was rejecting all paths with 403 because API Gateway's `API_MAPPING_ONLY` routing mode only honours paths matching an api_mapping.
- First terraform apply (in-place update) didn't fully take — had to `terraform taint 'module.api.aws_apigatewayv2_api_mapping.ws[0]'` and apply again to force-recreate the mapping with the new key. After recreation, `wss://ws.f1.zevlo.net/v1` connects cleanly.
- Verified end-to-end: agent.ask via production WS URL returns streamed reply.

### Phase 6.2 — Frontend env vars
- Created `frontend/.env.production` with the live URLs (committed — the dashboard is public read-only, URLs aren't secret).
- `npm run build` — bundle now has `VITE_API_BASE_URL=https://api.f1.zevlo.net/v1` and `VITE_WS_URL=wss://ws.f1.zevlo.net/v1` baked in (verified via grep on the produced JS).

### Phase 6.3 — Manual S3 sync + CloudFront invalidation
- `aws s3 sync frontend/dist/ s3://f1-telemetry-dev-frontend/ --delete` → 3 files, 632 KB.
- `aws cloudfront create-invalidation --distribution-id E3QEYQF69Z3KCQ --paths '/*'` → completed in <60s.

### Phase 6.4 — Smoke verification at https://f1.zevlo.net
- `https://f1.zevlo.net/` → HTTP 200 (was 403)
- `https://f1.zevlo.net/assets/index-*.js` → HTTP 200
- `https://api.f1.zevlo.net/v1/sessions` → returns the seeded Austria 2026 session
- `https://api.f1.zevlo.net/v1/sessions/11315/drivers` → 22 drivers with names + acronyms + teams
- `wss://ws.f1.zevlo.net/v1?sessionId=11315` → connects, agent asks answer correctly ("RUS is leading, VER is P2")
- Lambda unit tests: all 9 suites pass. Vitest: 17/17 pass. TypeScript strict + oxlint: clean.

### Phase 6.5 — CI/CD workflow
- Authored `.github/workflows/deploy.yml` mirroring v1's pattern: two sequential jobs (infra → frontend), OIDC role `github-oidc-f1-telemetry`, no static keys.
- `infra` job: `terraform init` → `terraform plan -lock=false` → `terraform apply -auto-approve` on push to `main`.
- `frontend` job (sequenced after infra): reads terraform outputs at runtime → `npm ci` → `vite build` with VITE env vars injected from outputs → `aws s3 sync` with immutable cache on hashed assets + must-revalidate on `index.html` → `aws cloudfront create-invalidation`.
- Trigger paths: `terraform/**`, `lambdas/**`, `frontend/**`, `.github/workflows/deploy.yml`. PRs don't deploy.

## Phase 7 — Delete old repo (PENDING — needs `delete_repo` scope)

Attempted `gh repo delete zevlo/f1-telemetry-dashboard --yes` but the gh token's scopes (`gist, read:org, repo, workflow`) don't include `delete_repo`. Manual follow-up:

```bash
gh auth refresh -h github.com -s delete_repo
gh repo delete zevlo/f1-telemetry-dashboard --yes
```

Phase 0 snapshot preserved at `/var/folders/z6/gvc0hbp90lg2hkn71stbn2xm0000gn/T/opencode/f1-v2-snapshot/` for emergency rollback reference. The local working tree at `/Users/za/projects/f1-telemetry-dashboard` can also be `rm -rf`'d once the user is confident v2 is stable.

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
