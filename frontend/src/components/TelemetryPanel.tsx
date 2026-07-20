import { useEffect, useState } from 'react'
import { Panel, SkeletonBlock, type PanelStatus } from './Panel'
import type { CarTelemetry, Driver, Lap } from '../types'

interface TelemetryPanelProps {
  driver: Driver | null
  driverLoading: boolean
  telemetry: CarTelemetry | null
  latestLap: Lap | null
  hasSession: boolean
  mode: 'live' | 'historical' | null
  dimmed: boolean
}

const SKELETON = (
  <div className="space-y-3 p-3">
    <SkeletonBlock className="h-16 w-full" />
    <div className="grid grid-cols-4 gap-2">
      {Array.from({ length: 8 }, (_, i) => (
        <SkeletonBlock key={i} className="h-14" />
      ))}
    </div>
  </div>
)

export function TelemetryPanel({
  driver,
  driverLoading,
  telemetry,
  latestLap,
  hasSession,
  mode,
  dimmed,
}: TelemetryPanelProps) {
  // In live mode, listen for `f1:car_data` events dispatched by the WS hook.
  const [liveTelemetry, setLiveTelemetry] = useState<CarTelemetry | null>(null)
  useEffect(() => {
    if (mode !== 'live') {
      setLiveTelemetry(null)
      return
    }
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<CarTelemetry>).detail
      // Only update if the event is for the focused driver.
      if (driver && detail.driver_number === driver.driver_number) {
        setLiveTelemetry(detail)
      }
    }
    window.addEventListener('f1:car_data', handler)
    return () => window.removeEventListener('f1:car_data', handler)
  }, [mode, driver])

  const activeTelemetry = liveTelemetry ?? telemetry

  const status: PanelStatus = !hasSession
    ? 'idle'
    : driverLoading && !driver
      ? 'loading'
      : !driver
        ? 'idle'
        : 'ready'

  const teamColor = driver?.team_colour ? `#${driver.team_colour}` : '#666666'

  return (
    <Panel
      title="Telemetry"
      status={dimmed ? 'stale' : status}
      idleMessage={
        !hasSession ? 'Pick a session, then a driver' : 'Click a driver in the tower to focus'
      }
      skeleton={SKELETON}
      headerExtra={
        driver ? (
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ backgroundColor: teamColor }}
            />
            <span className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">
              {driver.name_acronym || driver.full_name}
            </span>
          </span>
        ) : null
      }
      bodyClassName="overflow-y-auto"
    >
      {driver && (
        <div className={`flex h-full flex-col gap-3 p-3 ${dimmed ? 'opacity-60' : ''}`}>
          {/* Driver header */}
          <div className="flex items-center gap-3">
            {driver.headshot_url ? (
              <img
                src={driver.headshot_url}
                alt=""
                className="h-12 w-12 rounded-full bg-zinc-800 object-cover"
                onError={(e) => {
                  ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                }}
              />
            ) : (
              <div
                className="flex h-12 w-12 items-center justify-center rounded-full text-sm font-bold"
                style={{ backgroundColor: teamColor }}
              >
                {driver.name_acronym?.[0] ?? driver.driver_number}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-base font-semibold text-zinc-100">
                {driver.full_name}
              </div>
              <div className="truncate text-xs text-zinc-500">
                {driver.team_name} · {driver.country_code}
              </div>
            </div>
          </div>

          {/* Latest lap */}
          {latestLap && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-2.5">
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Lap {latestLap.lap_number}
                </span>
                {latestLap.compound && (
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[9px] uppercase text-zinc-300">
                    {latestLap.compound}
                  </span>
                )}
              </div>
              <div className="tnum text-2xl font-semibold text-zinc-100">
                {formatLapDuration(latestLap.lap_duration)}
              </div>
              <div className="mt-1.5 grid grid-cols-3 gap-2 text-[11px]">
                <Sector label="S1" value={latestLap.sector_1} />
                <Sector label="S2" value={latestLap.sector_2} />
                <Sector label="S3" value={latestLap.sector_3} />
              </div>
            </div>
          )}

          {/* Live telemetry gauges (live mode only) */}
          {mode === 'live' ? (
            activeTelemetry ? (
              <div className="grid grid-cols-4 gap-2">
                <Gauge label="Speed" value={activeTelemetry.speed != null ? `${Math.round(activeTelemetry.speed)}` : '—'} unit="km/h" />
                <Gauge label="Gear" value={activeTelemetry.n_gear != null ? `${activeTelemetry.n_gear}` : '—'} />
                <Gauge label="RPM" value={activeTelemetry.rpm != null ? `${activeTelemetry.rpm}` : '—'} />
                <Gauge
                  label="DRS"
                  value={
                    activeTelemetry.drs != null
                      ? drsLabel(activeTelemetry.drs)
                      : '—'
                  }
                />
                <Bar label="Throttle" value={activeTelemetry.throttle ?? 0} color="bg-emerald-500" />
                <Bar
                  label="Brake"
                  value={activeTelemetry.brake ? 100 : 0}
                  color="bg-rose-500"
                  display={activeTelemetry.brake ? 'ON' : 'OFF'}
                />
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-zinc-800 p-3 text-center text-[11px] text-zinc-500">
                Waiting for live telemetry…
              </div>
            )
          ) : (
            <div className="rounded-md border border-dashed border-zinc-800 p-3 text-center text-[11px] text-zinc-500">
              Live telemetry traces aren't available in replay mode.
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

function Sector({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div>
      <div className="text-[9px] uppercase text-zinc-500">{label}</div>
      <div className="tnum text-zinc-200">{value != null ? `${value.toFixed(3)}s` : '—'}</div>
    </div>
  )
}

function Gauge({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="tnum text-lg font-semibold text-zinc-100">
        {value}
        {unit && <span className="ml-1 text-[10px] font-normal text-zinc-500">{unit}</span>}
      </div>
    </div>
  )
}

function Bar({
  label,
  value,
  color,
  display,
}: {
  label: string
  value: number
  color: string
  display?: string
}) {
  return (
    <div className="col-span-2 rounded-md border border-zinc-800 bg-zinc-950/50 p-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</span>
        <span className="tnum text-[10px] text-zinc-400">{display ?? `${Math.round(value)}%`}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div className={`h-full ${color} transition-all`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  )
}

function formatLapDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds.toFixed(3)}s`
  const m = Math.floor(seconds / 60)
  const s = seconds - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}

function drsLabel(code: number): string {
  // OpenF1 DRS codes: 0=off, 1=available, 2=in-zone, 3=active, 8=manually disabled
  if (code === 3) return 'ON'
  if (code === 2) return 'ZONE'
  if (code === 1) return 'AVAIL'
  if (code === 8) return 'OFF'
  return String(code)
}
