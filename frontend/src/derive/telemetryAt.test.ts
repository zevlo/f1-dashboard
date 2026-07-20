import { describe, expect, it } from 'vitest'
import {
  lapsAtOrBefore,
  latestLapForDriver,
  positionsAtOrBefore,
  raceControlAtOrBefore,
} from './telemetryAt'
import type { Lap, PositionSample, RaceControlEvent } from '../types'

function mkPos(driver: number, pos: number, ts: string): PositionSample {
  return {
    session_key: '1',
    ts_driver: `${ts}#${driver}`,
    driver_number: driver,
    position: pos,
    date: ts,
  }
}

function mkLap(driver: number, lap: number, date_start: string, duration: number): Lap {
  return {
    session_driver: `1#${driver}`,
    lap_number: lap,
    date_start,
    lap_duration: duration,
    sector_1: null,
    sector_2: null,
    sector_3: null,
    is_pit_out_lap: false,
    compound: null,
  }
}

function mkRc(ts: string, flag: string | null, msg: string): RaceControlEvent {
  return {
    session_key: '1',
    timestamp: ts,
    category: 'Flag',
    flag,
    message: msg,
    driver_number: null,
  }
}

describe('positionsAtOrBefore', () => {
  it('returns all when cutoffTs is null (live mode)', () => {
    const p = [mkPos(1, 1, '2026-01-01T00:00:00'), mkPos(1, 2, '2026-01-01T00:00:05')]
    expect(positionsAtOrBefore(p, null)).toHaveLength(2)
  })
  it('filters to samples at or before cutoff', () => {
    const p = [
      mkPos(1, 1, '2026-01-01T00:00:00'),
      mkPos(1, 2, '2026-01-01T00:00:05'),
      mkPos(1, 3, '2026-01-01T00:00:10'),
    ]
    const out = positionsAtOrBefore(p, '2026-01-01T00:00:05')
    expect(out).toHaveLength(2)
    expect(out.map((x) => x.position)).toEqual([1, 2])
  })
})

describe('lapsAtOrBefore', () => {
  it('filters by date_start', () => {
    const laps = [
      mkLap(1, 1, '2026-01-01T00:01:00', 90),
      mkLap(1, 2, '2026-01-01T00:02:30', 91),
      mkLap(1, 3, '2026-01-01T00:04:00', 92),
    ]
    const out = lapsAtOrBefore(laps, '2026-01-01T00:03:00')
    expect(out).toHaveLength(2)
  })
})

describe('raceControlAtOrBefore', () => {
  it('filters by timestamp', () => {
    const events = [
      mkRc('2026-01-01T00:00:00', 'GREEN', 'Go'),
      mkRc('2026-01-01T00:30:00', 'YELLOW', 'Slow'),
      mkRc('2026-01-01T01:00:00', 'RED', 'Stop'),
    ]
    const out = raceControlAtOrBefore(events, '2026-01-01T00:45:00')
    expect(out.map((e) => e.flag)).toEqual(['GREEN', 'YELLOW'])
  })
})

describe('latestLapForDriver', () => {
  it('returns the highest lap_number for the given driver', () => {
    const laps = [
      mkLap(1, 1, '2026-01-01T00:01:00', 90),
      mkLap(2, 1, '2026-01-01T00:01:01', 91),
      mkLap(1, 2, '2026-01-01T00:02:30', 90),
      mkLap(2, 2, '2026-01-01T00:02:31', 91),
      mkLap(1, 3, '2026-01-01T00:04:00', 90),
    ]
    expect(latestLapForDriver(laps, 1)?.lap_number).toBe(3)
    expect(latestLapForDriver(laps, 2)?.lap_number).toBe(2)
  })
  it('returns null when driver has no laps', () => {
    const laps = [mkLap(1, 1, '2026-01-01T00:01:00', 90)]
    expect(latestLapForDriver(laps, 99)).toBeNull()
  })
})
