// Derive the dashboard state at a given moment in a replay.
//
// In replay mode the dashboard has the full bulk payload in memory. Each
// panel asks "what should I show at scrubTs?". This module centralises that
// derivation as pure functions, so the components stay declarative and the
// scrub clock can advance without prop cascades.

import type { Lap, PositionSample, RaceControlEvent } from '../types'

// Latest sample at or before cutoffTs. Returns null if no samples yet.
export function latestBefore<T extends { date?: string | null; date_start?: string | null }>(
  samples: T[],
  cutoffTs: string | null,
): T | null {
  if (samples.length === 0) return null
  if (!cutoffTs) return samples[samples.length - 1]
  let lo = 0
  let hi = samples.length - 1
  let result: T | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const sampleTs = samples[mid].date ?? samples[mid].date_start ?? ''
    if (sampleTs <= cutoffTs) {
      result = samples[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return result
}

// Filter helpers — slice the bulk payload to "everything up to cutoffTs".
// Each assumes the input array is sorted ascending by the relevant ts field.
// The API returns them that way; if you have unsorted input, sort first.

export function positionsAtOrBefore(
  positions: PositionSample[],
  cutoffTs: string | null,
): PositionSample[] {
  if (!cutoffTs) return positions
  // positions are sorted by ts_driver (lexicographic on ts#driver).
  // We need a linear filter because the SK is composite.
  return positions.filter((p) => p.date <= cutoffTs)
}

export function lapsAtOrBefore(laps: Lap[], cutoffTs: string | null): Lap[] {
  if (!cutoffTs) return laps
  return laps.filter((l) => (l.date_start ?? '') <= cutoffTs)
}

export function raceControlAtOrBefore(
  events: RaceControlEvent[],
  cutoffTs: string | null,
): RaceControlEvent[] {
  if (!cutoffTs) return events
  return events.filter((e) => (e.timestamp ?? '') <= cutoffTs)
}

// Latest position per driver, given a (possibly filtered) sample list.
// Returns a Map<driver_number, position> for quick lookup in the tower.
export function latestPositionPerDriver(
  positions: PositionSample[],
): Map<number, PositionSample> {
  const map = new Map<number, PositionSample>()
  for (const p of positions) {
    const prev = map.get(p.driver_number)
    if (!prev || p.date > prev.date) {
      map.set(p.driver_number, p)
    }
  }
  return map
}

// Latest lap number for a driver, given a (possibly filtered) lap list.
export function latestLapForDriver(laps: Lap[], driverNumber: number): Lap | null {
  let latest: Lap | null = null
  for (const l of laps) {
    if (!l.session_driver.endsWith(`#${driverNumber}`)) continue
    if (!latest || (l.lap_number ?? 0) > (latest.lap_number ?? 0)) {
      latest = l
    }
  }
  return latest
}
