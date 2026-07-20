// Typed fetch wrappers for every REST endpoint. Used by the TanStack Query
// hooks in hooks.ts. Throws on non-2xx so React Query surfaces the error.

import { config } from '../config'
import type { Driver, Lap, PositionSample, RaceControlEvent, ReplayPayload, Session } from '../types'

export interface SessionsResponse {
  items: Session[]
  nextCursor: string | null
}

const BASE = config.apiBaseUrl

async function getJSON<T>(path: string): Promise<T> {
  if (!BASE) {
    throw new Error('VITE_API_BASE_URL not configured')
  }
  const r = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
  })
  if (!r.ok) {
    let detail = ''
    try {
      detail = (await r.json()).error ?? ''
    } catch {
      // response had no JSON body
    }
    throw new Error(`${r.status} ${r.statusText}${detail ? `: ${detail}` : ''}`)
  }
  return r.json() as Promise<T>
}

export const api = {
  listSessions: () => getJSON<SessionsResponse>('/sessions'),

  getSession: (sessionKey: string) => getJSON<Session>(`/sessions/${encodeURIComponent(sessionKey)}`),

  getDrivers: (sessionKey: string) =>
    getJSON<Driver[]>(`/sessions/${encodeURIComponent(sessionKey)}/drivers`),

  getReplay: (sessionKey: string) =>
    getJSON<ReplayPayload>(`/sessions/${encodeURIComponent(sessionKey)}/replay`),

  getPositions: (sessionKey: string) =>
    getJSON<PositionSample[]>(`/sessions/${encodeURIComponent(sessionKey)}/positions`),

  getRaceControl: (sessionKey: string) =>
    getJSON<RaceControlEvent[]>(`/sessions/${encodeURIComponent(sessionKey)}/race-control`),

  getLaps: (sessionKey: string, driverNumbers: number[]) => {
    const q = driverNumbers.map((n) => `driver=${n}`).join('&')
    return getJSON<Lap[]>(`/sessions/${encodeURIComponent(sessionKey)}/laps?${q}`)
  },

  getDriver: (driverNumber: number) =>
    getJSON<Driver>(`/drivers/${encodeURIComponent(driverNumber)}`),
} as const
