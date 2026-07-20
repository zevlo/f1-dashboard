// Derive the position tower rows at a given moment.
//
// Input: all position samples for a session (already sorted asc by date by
// the API), a map of driver_number -> Driver for name/colour lookup, and an
// optional cutoffTs. If cutoffTs is null (live mode), uses the latest sample
// per driver. If cutoffTs is set (replay scrub), uses the most recent sample
// at or before cutoffTs per driver.
//
// Output: array sorted by current position (P1 first). Each row carries the
// driver + position + gap to leader (in positions, not time — telemetry panel
// shows time gaps separately).

import type { Driver, PositionSample } from '../types'

export interface TowerRow {
  driver_number: number
  position: number
  // ISO ts of the underlying sample (so the UI can show "as of HH:MM:SS").
  ts: string
  // Lookup-friendly driver metadata. Falls back to a stub when the driver
  // isn't in the cache yet (rare — bulk fetch should populate all 20).
  driver: {
    full_name: string
    name_acronym: string
    team_name: string
    team_colour: string
  }
}

function driverStub(number: number) {
  return {
    full_name: `Driver ${number}`,
    name_acronym: String(number),
    team_name: '',
    team_colour: '666666',
  }
}

function driverView(d: Driver | undefined, number: number) {
  if (!d) return driverStub(number)
  return {
    full_name: d.full_name ?? driverStub(number).full_name,
    name_acronym: d.name_acronym ?? driverStub(number).name_acronym,
    team_name: d.team_name ?? '',
    team_colour: d.team_colour ?? '666666',
  }
}

export function deriveTowerRows(
  positions: PositionSample[],
  drivers: Map<number, Driver>,
  cutoffTs: string | null = null,
): TowerRow[] {
  if (positions.length === 0) return []

  // For each driver, find their latest sample at or before cutoffTs.
  const latestByDriver = new Map<number, PositionSample>()
  for (const p of positions) {
    if (cutoffTs && p.date > cutoffTs) continue
    const prev = latestByDriver.get(p.driver_number)
    if (!prev || p.date > prev.date) {
      latestByDriver.set(p.driver_number, p)
    }
  }

  const rows: TowerRow[] = []
  for (const [driverNumber, sample] of latestByDriver) {
    rows.push({
      driver_number: driverNumber,
      position: sample.position,
      ts: sample.date,
      driver: driverView(drivers.get(driverNumber), driverNumber),
    })
  }

  rows.sort((a, b) => a.position - b.position)
  return rows
}
