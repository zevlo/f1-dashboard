import { describe, expect, it } from 'vitest'
import { deriveTowerRows } from './towerRows'
import type { Driver, PositionSample } from '../types'

function mkDriver(n: number, name: string, team: string, colour: string): Driver {
  return {
    session_key: '1',
    driver_number: n,
    full_name: name,
    broadcast_name: name,
    name_acronym: name.slice(0, 3).toUpperCase(),
    team_name: team,
    team_colour: colour,
    country_code: null,
    headshot_url: null,
  }
}

function mkPos(driver: number, pos: number, ts: string): PositionSample {
  return {
    session_key: '1',
    ts_driver: `${ts}#${driver}`,
    driver_number: driver,
    position: pos,
    date: ts,
  }
}

describe('deriveTowerRows', () => {
  it('returns empty for empty input', () => {
    expect(deriveTowerRows([], new Map(), null)).toEqual([])
  })

  it('uses the latest sample per driver in live mode (cutoffTs=null)', () => {
    const positions = [
      mkPos(1, 1, '2026-01-01T00:00:00'),
      mkPos(2, 2, '2026-01-01T00:00:00'),
      mkPos(1, 2, '2026-01-01T00:00:05'), // VER drops to P2
      mkPos(2, 1, '2026-01-01T00:00:05'), // NOR promotes to P1
    ]
    const drivers = new Map([
      [1, mkDriver(1, 'Max Verstappen', 'Red Bull', '3671C6')],
      [2, mkDriver(2, 'Lando Norris', 'McLaren', 'FF8000')],
    ])
    const rows = deriveTowerRows(positions, drivers, null)
    expect(rows).toHaveLength(2)
    expect(rows[0].driver_number).toBe(2) // NOR is now P1
    expect(rows[0].position).toBe(1)
    expect(rows[1].driver_number).toBe(1) // VER is now P2
    expect(rows[1].position).toBe(2)
  })

  it('respects cutoffTs in replay mode (snapshot at that moment)', () => {
    const positions = [
      mkPos(1, 1, '2026-01-01T00:00:00'),
      mkPos(2, 2, '2026-01-01T00:00:00'),
      mkPos(1, 2, '2026-01-01T00:00:05'),
      mkPos(2, 1, '2026-01-01T00:00:05'),
    ]
    const drivers = new Map([
      [1, mkDriver(1, 'Max', 'Red Bull', 'FF8000')],
      [2, mkDriver(2, 'Lando', 'McLaren', 'FF8000')],
    ])

    // Scrub to 00:00:00 (before the position swap).
    const rowsEarly = deriveTowerRows(positions, drivers, '2026-01-01T00:00:00')
    expect(rowsEarly[0].driver_number).toBe(1)
    expect(rowsEarly[0].position).toBe(1)

    // Scrub to 00:00:05 (after the swap).
    const rowsLate = deriveTowerRows(positions, drivers, '2026-01-01T00:00:05')
    expect(rowsLate[0].driver_number).toBe(2)
  })

  it('uses a stub when driver metadata is missing from the map', () => {
    const positions = [mkPos(81, 1, '2026-01-01T00:00:00')]
    const rows = deriveTowerRows(positions, new Map(), null)
    expect(rows).toHaveLength(1)
    expect(rows[0].driver.full_name).toBe('Driver 81')
    expect(rows[0].driver.name_acronym).toBe('81')
  })

  it('sorts by position ascending', () => {
    const positions = [
      mkPos(1, 5, '2026-01-01T00:00:00'),
      mkPos(2, 1, '2026-01-01T00:00:00'),
      mkPos(3, 3, '2026-01-01T00:00:00'),
    ]
    const rows = deriveTowerRows(positions, new Map(), null)
    expect(rows.map((r) => r.position)).toEqual([1, 3, 5])
  })
})
