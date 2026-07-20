# AGENTS.md

Working agreement for any agent (or human) touching this repo. Read before editing.

> **Project context:** F1 telemetry dashboard, v2 rebuild. Live AWS deployment at https://f1.zevlo.net. See [`README.md`](./README.md) for the high-level architecture and [`docs/v2-build-plan.md`](./docs/v2-build-plan.md) for current phase. The previous repo (`zevlo/f1-telemetry-dashboard`) was deleted and rebuilt clean here because the UX was too slow and the data model didn't support bulk driver lookups.

## Non-negotiable rules

1. **Never commit secrets.** AWS creds live in OIDC + GitHub Actions, never in the repo. `.env*` files are gitignored.
2. **Every Lambda write to DynamoDB must be idempotent.** Use conditional puts on a deterministic primary key (see §Idempotency below).
3. **Driver metadata is bulk, not lazy.** Never fetch `/drivers/{n}` one-at-a-time from the frontend. Use `GET /sessions/{key}/drivers` (returns all 20 in one call).
4. **Replays are client-side.** Do not reintroduce a server-side replay cursor. The poller runs in live mode only.
5. **Driver click is local-only.** Never trigger a network request when the user clicks a driver in the tower. Mutate Zustand state only.
6. **Don't add comments unless asked.** Match existing style. Self-documenting names beat comments.
7. **Terraform changes run through CI.** Don't `terraform apply` from your workstation against `dev` unless explicitly told to. `plan` locally all you want.
8. **Don't delete the Route 53 `zevlo.net` zone or the ACM cert for `f1.zevlo.net`.** Both predate this project; deleting them affects other things in the account.

## OpenF1 API quirks

Base URL: `https://api.openf1.org/v1` — free, no auth.

- **Rate limit:** ~3 req/s, 30 req/min. Batch where possible. Cache `/sessions` and `/drivers` (they don't change mid-session).
- **Pagination:** none. Use `?date>={ts}` filters to fetch only new records. Unbounded queries return everything and will rate-limit you.
- **Floats:** OpenF1 returns floats for speed/rpm/etc. boto3 DynamoDB rejects Python `float` — convert to `Decimal` in the transformer before `put_item`.
- **Session discovery:** `?session_key=latest` returns the active session if a race weekend is live. Outside race weekends, returns the most recent session. The poller uses this in live mode.
- **Driver numbers are session-scoped.** The same `driver_number` maps to different people across sessions (rare but happens with reserve drivers). Always scope by `session_key`.
- `/laps` is the heavy endpoint. Don't fetch per-cycle in the poller — fetch once per invocation max. v1 had a bug where it fetched per-cycle and flooded Kinesis.
- `/position` and `/car_data` sample at ~3.5s, not exactly 5s. The poller's overlap window (`LIVE_OVERLAP_SECONDS`) absorbs the drift; the transformer dedupes via conditional put.

## Idempotency rules

Every per-sample write to DynamoDB must use a conditional put on a deterministic key. The transformer is the dedupe boundary; everything upstream is allowed to send duplicates.

| Table | PK | SK (if any) | Conditional put on |
|---|---|---|---|
| Sessions | `session_key` | — | `attribute_not_exists(session_key)` |
| Drivers | `session_key` | `driver_number` | `attribute_not_exists(session_key) AND attribute_not_exists(driver_number)` |
| Positions | `session_key` | `ts#driver_number` | `attribute_not_exists(session_key) AND attribute_not_exists(ts_driver)` |
| CarData | `session_key#driver_number` | `ts` | `attribute_not_exists(pk_attr) AND attribute_not_exists(ts)` |
| Laps | `session_key#driver_number` | `lap_number` | `attribute_not_exists(pk_attr) AND attribute_not_exists(lap_number)` |
| RaceControl | `session_key` | `ts` | `attribute_not_exists(session_key) AND attribute_not_exists(ts)` |

Conditional put failures are **expected** and **not errors** — they mean the duplicate was already written. Log them at DEBUG, count them in the transformer's `deduped` metric, and move on. Don't retry.

## Frontend cache contract

- All server state goes through TanStack Query. Keys are stable tuples: `['sessions']`, `['session', sessionKey]`, `['drivers', sessionKey]`, `['replay', sessionKey]`, `['laps', sessionKey, ...driverNumbers]`, `['driver', driverNumber]`.
- All UI state (selected session/driver, comparison drivers, replay clock) goes through Zustand stores in `frontend/src/store/`.
- The WebSocket hook merges live ticks into the TanStack Query cache via `queryClient.setQueryData`. Never duplicate server state in Zustand.
- Replays don't refetch on scrub. The scrub clock is in `replayStore`; all components derive visible state via pure `derive/*` functions over the bulk-replay payload.

## Performance budget

| Interaction | Target | Tool |
|---|---|---|
| Driver click → telemetry panel updates | <100 ms | Zustand subscribe (no network) |
| Session switch → first meaningful paint | <500 ms | TanStack Query cache (stale-while-revalidate) |
| Session switch → full data | <1.5 s | Parallel REST prefetch |
| Live WS tick → tower update | no frame drops | `queryClient.setQueryData` (in-place mutation) |
| Replay scrub → all panels reflect new moment | <16 ms | Local clock + memoized derive functions |

## Testing

- **Lambdas:** pytest unit tests for every handler. Poller driver-discovery and transformer idempotency are mandatory. Run with `cd lambdas/<name> && python test_handler.py`.
- **Frontend:** Vitest unit tests for `derive/*` pure functions and TanStack Query hooks (MSW for HTTP mocks). Playwright smoke for: page loads, session switch, driver click doesn't refetch, agent chat returns a streamed reply.
- **No coverage bar.** Tests must pass in CI. Don't add tests for the sake of coverage.

## CI/CD

- `.github/workflows/deploy.yml` triggers on push to `main` touching `terraform/**`, `lambdas/**`, or `frontend/**`.
- OIDC assume `github-oidc-f1-telemetry` role → `terraform plan` → `terraform apply -auto-approve` (infra job) → `npm ci && vite build && aws s3 sync && CloudFront invalidation` (frontend job, sequenced after infra).
- Both jobs use short-lived OIDC credentials. **No static AWS keys in the repo, ever.**

## When in doubt

- Read the existing pattern in the nearest neighbor file.
- Match conventions, don't invent new ones.
- Ask before adding a new dependency or a new AWS service.
