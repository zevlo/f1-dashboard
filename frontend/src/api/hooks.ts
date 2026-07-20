// TanStack Query hooks. Stable cache keys per the AGENTS.md contract.
//
// Keys:
//   ['sessions']                                  — list (prefetch on mount)
//   ['session', sessionKey]                       — single session metadata
//   ['drivers', sessionKey]                       — bulk drivers (v2 key endpoint)
//   ['replay', sessionKey]                        — bulk replay payload
//   ['positions', sessionKey]                     — historical positions
//   ['race-control', sessionKey]                  — historical race control
//   ['laps', sessionKey, ...driverNumbers]        — laps filtered to drivers
//
// The WS hook merges live ticks into the ['positions'], ['race-control'],
// and ['laps'] entries via queryClient.setQueryData when in live mode.

import { useQuery, type UseQueryOptions } from '@tanstack/react-query'
import { api } from './client'
import type {
  Driver,
  Lap,
  PositionSample,
  RaceControlEvent,
  ReplayPayload,
  Session,
} from '../types'

// Common query option defaults — short-circuit retries on 4xx (no point
// retrying a 404). React Query already knows to retry network errors.
const noRetryOn4xx: Pick<UseQueryOptions, 'retry'> = {
  retry: (failureCount, error) => {
    if (/^4\d\d /.test(error.message)) return false
    return failureCount < 1
  },
}

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.listSessions(),
    ...noRetryOn4xx,
  })
}

export function useSession(sessionKey: string | null) {
  return useQuery({
    queryKey: ['session', sessionKey],
    queryFn: () => api.getSession(sessionKey!),
    enabled: !!sessionKey,
    ...noRetryOn4xx,
  })
}

export function useDrivers(sessionKey: string | null) {
  return useQuery({
    queryKey: ['drivers', sessionKey],
    queryFn: () => api.getDrivers(sessionKey!),
    enabled: !!sessionKey,
    ...noRetryOn4xx,
  })
}

export function useReplay(sessionKey: string | null) {
  return useQuery({
    queryKey: ['replay', sessionKey],
    queryFn: () => api.getReplay(sessionKey!),
    enabled: !!sessionKey,
    // Replay payload is large; give it a longer stale time so scrubbing back
    // and forth doesn't re-trigger a network fetch.
    staleTime: 5 * 60_000,
    ...noRetryOn4xx,
  })
}

export function usePositions(sessionKey: string | null) {
  return useQuery({
    queryKey: ['positions', sessionKey],
    queryFn: () => api.getPositions(sessionKey!),
    enabled: !!sessionKey,
    ...noRetryOn4xx,
  })
}

export function useRaceControl(sessionKey: string | null) {
  return useQuery({
    queryKey: ['race-control', sessionKey],
    queryFn: () => api.getRaceControl(sessionKey!),
    enabled: !!sessionKey,
    ...noRetryOn4xx,
  })
}

export function useLaps(sessionKey: string | null, driverNumbers: number[]) {
  const key = [...(driverNumbers)].sort((a, b) => a - b)
  return useQuery({
    queryKey: ['laps', sessionKey, ...key],
    queryFn: () => api.getLaps(sessionKey!, driverNumbers),
    enabled: !!sessionKey && driverNumbers.length > 0,
    ...noRetryOn4xx,
  })
}

export type SessionsQuery = ReturnType<typeof useSessions>
export type SessionQuery = ReturnType<typeof useSession>
export type DriversQuery = ReturnType<typeof useDrivers>
export type ReplayQuery = ReturnType<typeof useReplay>
export type PositionsQuery = ReturnType<typeof usePositions>
export type RaceControlQuery = ReturnType<typeof useRaceControl>
export type LapsQuery = ReturnType<typeof useLaps>

// Re-export types for downstream consumers.
export type { Driver, Lap, PositionSample, RaceControlEvent, ReplayPayload, Session }
