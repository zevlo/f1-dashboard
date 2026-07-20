import { QueryClient } from '@tanstack/react-query'

// TanStack Query client — tuned for telemetry cadence.
//
// - staleTime 30s on telemetry data: the bulk replay payload is immutable
//   (historical session), so a half-minute TTL avoids refetching on every
//   mount without holding stale data forever in live mode.
// - gcTime 5min: keep bulk replay payload around while the user may switch
//   tabs / come back to a session they just looked at.
// - retry 1: telemetry APIs are either fast (DDB query) or failing (Lambda
//   cold start) — don't hammer retries.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})
