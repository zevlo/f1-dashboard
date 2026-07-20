import { useCallback, useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { config } from './config'
import { useSession, useReplay, useDrivers } from './api/hooks'
import { useWebSocket } from './ws/useWebSocket'
import { useSessionStore } from './store/sessionStore'
import { useDriverStore } from './store/driverStore'
import { useReplayStore } from './store/replayStore'

import { TopBar } from './components/TopBar'
import { FlagBanner } from './components/FlagBanner'
import { PositionTower } from './components/PositionTower'
import { TelemetryPanel } from './components/TelemetryPanel'
import { LapTimeChart } from './components/LapTimeChart'
import { ReplayControls } from './components/ReplayControls'
import { AgentChatPanel } from './components/AgentChatPanel'

import { deriveTowerRows } from './derive/towerRows'
import {
  lapsAtOrBefore,
  latestLapForDriver,
  positionsAtOrBefore,
  raceControlAtOrBefore,
} from './derive/telemetryAt'

export function App() {
  const queryClient = useQueryClient()

  // Session + driver + replay state (Zustand).
  const sessionKey = useSessionStore((s) => s.sessionKey)
  const setSession = useSessionStore((s) => s.setSession)
  const setMode = useSessionStore((s) => s.setMode)
  const clearSession = useSessionStore((s) => s.clear)

  const selectedDriverNumber = useDriverStore((s) => s.selectedDriverNumber)
  const comparisonDrivers = useDriverStore((s) => s.comparisonDrivers)
  const clearDrivers = useDriverStore((s) => s.clear)

  const scrubTs = useReplayStore((s) => s.scrubTs)
  const setBounds = useReplayStore((s) => s.setBounds)
  const setReplayMode = useReplayStore((s) => s.setMode)
  const resetReplay = useReplayStore((s) => s.reset)

  // Bulk fetches. Drivers + replay are prefetched in parallel on session load.
  const sessionQuery = useSession(sessionKey)
  const driversQuery = useDrivers(sessionKey)
  const replayQuery = useReplay(sessionKey)

  // Derive mode from session status.
  const session = sessionQuery.data ?? null
  const mode = session ? (session.status === 'active' ? 'live' : 'historical') : null

  useEffect(() => {
    if (mode) {
      setMode(mode)
      setReplayMode(mode)
    }
  }, [mode, setMode, setReplayMode])

  // When a session loads, set the replay clock's bounds to its date_start/end.
  useEffect(() => {
    if (session) {
      setBounds([session.date_start ?? '', session.date_end ?? ''])
    } else {
      setBounds(null)
    }
    resetReplay()
  }, [session, setBounds, resetReplay])

  // WebSocket — only in live mode (historical mode is client-side playback).
  const wsUrl =
    mode === 'live' && sessionKey && config.wsUrl
      ? `${config.wsUrl}?sessionId=${encodeURIComponent(sessionKey)}`
      : null

  const handleWsReconnect = useCallback(() => {
    // Refetch the per-session bulk data to fill gaps left while disconnected.
    if (sessionKey) {
      queryClient.invalidateQueries({ queryKey: ['positions', sessionKey] })
      queryClient.invalidateQueries({ queryKey: ['race-control', sessionKey] })
      queryClient.invalidateQueries({ queryKey: ['laps', sessionKey] })
    }
  }, [queryClient, sessionKey])

  const { status: connectionStatus, send, retry: retryConnection } = useWebSocket({
    url: wsUrl,
    onReconnect: handleWsReconnect,
  })

  const wsReady = connectionStatus === 'connected'
  const dimmed = connectionStatus === 'reconnecting' || connectionStatus === 'disconnected'

  // Build the driver map from the bulk drivers query. The tower + chart +
  // telemetry panel all look up metadata from this map (single source of truth).
  const drivers = useMemo(() => {
    const m = new Map<number, NonNullable<typeof driversQuery.data>[number]>()
    for (const d of driversQuery.data ?? []) m.set(d.driver_number, d)
    return m
  }, [driversQuery.data])

  // Derived data — derived against the replay payload (preferred) or the
  // per-route queries (fallback for live mode where we don't fetch the bulk).
  const positions = useMemo(() => {
    if (replayQuery.data) return replayQuery.data.positions
    return []
  }, [replayQuery.data])

  const allLaps = useMemo(() => {
    if (replayQuery.data) return replayQuery.data.laps
    return []
  }, [replayQuery.data])

  const raceControl = useMemo(() => {
    if (replayQuery.data) return replayQuery.data.race_control
    return []
  }, [replayQuery.data])

  // Filter to the current scrub moment (replay mode only — live mode passes
  // null cutoff, which leaves arrays unfiltered).
  const cutoffTs = mode === 'historical' ? scrubTs : null

  const visiblePositions = useMemo(
    () => positionsAtOrBefore(positions, cutoffTs),
    [positions, cutoffTs],
  )
  const visibleLaps = useMemo(
    () => lapsAtOrBefore(allLaps, cutoffTs),
    [allLaps, cutoffTs],
  )
  const visibleRaceControl = useMemo(
    () => raceControlAtOrBefore(raceControl, cutoffTs),
    [raceControl, cutoffTs],
  )

  const towerRows = useMemo(
    () => deriveTowerRows(visiblePositions, drivers, null),
    [visiblePositions, drivers],
  )

  // Driver metadata for the focused driver.
  const focusedDriver = selectedDriverNumber != null ? drivers.get(selectedDriverNumber) ?? null : null

  // Latest lap for the focused driver at the current moment.
  const latestLapForFocused = useMemo(() => {
    if (selectedDriverNumber == null) return null
    return latestLapForDriver(visibleLaps, selectedDriverNumber)
  }, [visibleLaps, selectedDriverNumber])

  // Current lap counter (latest lap across all drivers in the visible window).
  const currentLap = useMemo(() => {
    if (visibleLaps.length === 0) return null
    return Math.max(...visibleLaps.map((l) => l.lap_number ?? 0))
  }, [visibleLaps])

  // Drivers to plot in the lap chart: focused first, then comparisons.
  const chartDrivers = useMemo(() => {
    const set = new Set<number>()
    if (selectedDriverNumber != null) set.add(selectedDriverNumber)
    for (const d of comparisonDrivers) set.add(d)
    return [...set]
  }, [selectedDriverNumber, comparisonDrivers])

  // Current flag at the scrub moment (replay) or via WS (live — handled by FlagBanner).
  const currentFlag = useMemo(() => {
    if (mode !== 'historical') return null
    const withFlag = visibleRaceControl.filter((e) => e.flag)
    return withFlag.length > 0 ? withFlag[withFlag.length - 1].flag : null
  }, [visibleRaceControl, mode])
  const currentFlagMessage = useMemo(() => {
    if (mode !== 'historical' || visibleRaceControl.length === 0) return null
    return visibleRaceControl[visibleRaceControl.length - 1]?.message ?? null
  }, [visibleRaceControl, mode])

  // Session switch handler — clears all dependent UI state.
  const handleSessionChange = useCallback(
    (newSessionKey: string | null) => {
      if (newSessionKey === null) {
        clearSession()
      } else {
        setSession(newSessionKey, null) // mode gets set when session query resolves
      }
      clearDrivers()
      resetReplay()
    },
    [setSession, clearSession, clearDrivers, resetReplay],
  )

  return (
    <div className="flex h-screen flex-col bg-zinc-950 text-zinc-100">
      <TopBar
        selectedSessionKey={sessionKey}
        session={session}
        sessionLoading={sessionQuery.isLoading}
        mode={mode}
        connectionStatus={connectionStatus}
        currentLap={currentLap}
        onSessionChange={handleSessionChange}
        onRetryConnection={retryConnection}
      />

      <FlagBanner flag={currentFlag} message={currentFlagMessage} />

      <main className="flex min-h-0 flex-1 gap-2 p-2">
        <PositionTower
          rows={towerRows}
          drivers={drivers}
          loading={replayQuery.isLoading || driversQuery.isLoading}
          hasSession={!!sessionKey}
          selectedDriverNumber={selectedDriverNumber}
          comparisonDrivers={comparisonDrivers}
          dimmed={dimmed}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="min-h-0 flex-1">
            <TelemetryPanel
              driver={focusedDriver}
              driverLoading={driversQuery.isLoading}
              telemetry={null}
              latestLap={latestLapForFocused}
              hasSession={!!sessionKey}
              mode={mode}
              dimmed={dimmed}
            />
          </div>
          <div className="min-h-0 flex-1">
            <LapTimeChart
              laps={visibleLaps}
              chartDrivers={chartDrivers}
              drivers={drivers}
              highlightLap={latestLapForFocused?.lap_number ?? null}
              hasSession={!!sessionKey}
              loading={replayQuery.isLoading}
              dimmed={dimmed}
            />
          </div>
        </div>

        <AgentChatPanel send={send} wsReady={wsReady} />
      </main>

      <ReplayControls latestLap={currentLap} />
    </div>
  )
}
