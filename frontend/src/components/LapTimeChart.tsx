import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Panel, type PanelStatus } from './Panel'
import type { Driver, Lap } from '../types'

interface LapTimeChartProps {
  laps: Lap[]
  // Focused driver + comparison drivers (focused is first element).
  chartDrivers: number[]
  drivers: Map<number, Driver>
  // Lap currently being viewed (scrub position). Null = "show latest".
  highlightLap: number | null
  hasSession: boolean
  loading: boolean
  dimmed: boolean
}

interface ChartPoint {
  lap: number
  [driverKey: string]: number | string
}

const DRIVER_LINE_COLORS = ['#fbbf24', '#38bdf8', '#a78bfa'] // amber, sky, violet

export function LapTimeChart({
  laps,
  chartDrivers,
  drivers,
  highlightLap,
  hasSession,
  loading,
  dimmed,
}: LapTimeChartProps) {
  const status: PanelStatus = !hasSession
    ? 'idle'
    : loading && laps.length === 0
      ? 'loading'
      : 'ready'

  const data = useMemo<ChartPoint[]>(() => {
    if (chartDrivers.length === 0) return []
    // Find lap range (max lap_number across all chart drivers).
    const maxLap = Math.max(0, ...laps.map((l) => l.lap_number ?? 0))
    if (maxLap === 0) return []

    // Index laps by (driver, lap_number) for quick lookup.
    const byDriverLap = new Map<string, number>()
    for (const l of laps) {
      const driverNum = parseDriverNumber(l.session_driver)
      if (driverNum == null) continue
      if (!chartDrivers.includes(driverNum)) continue
      if (l.lap_duration == null) continue
      byDriverLap.set(`${driverNum}#${l.lap_number}`, l.lap_duration)
    }

    // Build chart points: one per lap_number across all chart drivers.
    const out: ChartPoint[] = []
    for (let lap = 1; lap <= maxLap; lap++) {
      const point: ChartPoint = { lap }
      for (const d of chartDrivers) {
        const key = `${d}#${lap}`
        const v = byDriverLap.get(key)
        if (v != null) point[`d${d}`] = v
      }
      out.push(point)
    }
    return out
  }, [laps, chartDrivers])

  return (
    <Panel
      title="Lap Times"
      status={dimmed ? 'stale' : status}
      idleMessage="Lap times appear once a session + driver are picked"
      skeleton={<div className="h-full p-3"><div className="h-full animate-pulse rounded bg-zinc-800/80" /></div>}
      bodyClassName="p-2"
    >
      <div className={`h-full ${dimmed ? 'opacity-60' : ''}`}>
        {chartDrivers.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-zinc-500">
            Click a driver in the tower to plot their lap times
          </div>
        ) : data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-zinc-500">
            No lap data yet
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
              <XAxis
                dataKey="lap"
                type="number"
                domain={[1, 'dataMax']}
                tick={{ fill: '#71717a', fontSize: 10 }}
                stroke="#3f3f46"
              />
              <YAxis
                domain={['auto', 'auto']}
                reversed
                tick={{ fill: '#71717a', fontSize: 10 }}
                stroke="#3f3f46"
                tickFormatter={(v: number) => formatLapDuration(v)}
                width={56}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#18181b',
                  border: '1px solid #3f3f46',
                  borderRadius: 6,
                  fontSize: 11,
                }}
                labelStyle={{ color: '#a1a1aa' }}
                formatter={(value, name) => {
                  const v = Number(value)
                  const driverNum = Number(String(name).slice(1))
                  const drv = drivers.get(driverNum)
                  const label = drv?.name_acronym ?? drv?.full_name ?? String(name)
                  return [formatLapDuration(v), label]
                }}
                labelFormatter={(label) => `Lap ${label}`}
              />
              {chartDrivers.map((d, idx) => {
                const drv = drivers.get(d)
                const color = drv?.team_colour ? `#${drv.team_colour}` : DRIVER_LINE_COLORS[idx % DRIVER_LINE_COLORS.length]
                return (
                  <Line
                    key={d}
                    type="monotone"
                    dataKey={`d${d}`}
                    stroke={color}
                    dot={false}
                    strokeWidth={2}
                    isAnimationActive={false}
                    connectNulls
                  />
                )
              })}
              {highlightLap != null && (
                <ReferenceLine x={highlightLap} stroke="#fafafa" strokeDasharray="2 2" />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </Panel>
  )
}

function parseDriverNumber(sessionDriver: string): number | null {
  const hashIdx = sessionDriver.lastIndexOf('#')
  if (hashIdx === -1) return null
  const n = Number(sessionDriver.slice(hashIdx + 1))
  return Number.isNaN(n) ? null : n
}

function formatLapDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(3)}s`
  const m = Math.floor(seconds / 60)
  const s = seconds - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}
