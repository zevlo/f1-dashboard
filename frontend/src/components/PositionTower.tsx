import { Panel, type PanelStatus, SkeletonBlock } from './Panel'
import { useDriverStore } from '../store/driverStore'
import type { Driver } from '../types'
import type { TowerRow } from '../derive/towerRows'

interface PositionTowerProps {
  rows: TowerRow[]
  drivers: Map<number, Driver>
  loading: boolean
  hasSession: boolean
  selectedDriverNumber: number | null
  comparisonDrivers: number[]
  // Dim when the WS connection is stale so users see data is suspect.
  dimmed: boolean
}

const SKELETON_ROWS = (
  <>
    {Array.from({ length: 8 }, (_, i) => (
      <SkeletonBlock key={i} className="h-8 w-full" />
    ))}
  </>
)

export function PositionTower({
  rows,
  drivers: _drivers,
  loading,
  hasSession,
  selectedDriverNumber,
  comparisonDrivers,
  dimmed,
}: PositionTowerProps) {
  const select = useDriverStore((s) => s.select)
  const toggleComparison = useDriverStore((s) => s.toggleComparison)

  const status: PanelStatus = !hasSession ? 'idle' : loading && rows.length === 0 ? 'loading' : 'ready'

  return (
    <Panel
      title="Positions"
      status={status}
      idleMessage="Pick a session to load the field"
      skeleton={SKELETON_ROWS}
      className="w-[260px] shrink-0"
      headerExtra={
        <span className="tnum">
          {rows.length > 0 ? `${rows.length} drivers` : ''}
        </span>
      }
    >
      <ul
        className={`flex h-full flex-col divide-y divide-zinc-900 overflow-y-auto transition-opacity ${
          dimmed ? 'opacity-50' : ''
        }`}
      >
        {rows.map((row) => {
          const isSelected = row.driver_number === selectedDriverNumber
          const isComparison = comparisonDrivers.includes(row.driver_number)
          const teamColor = `#${row.driver.team_colour || '666666'}`
          return (
            <li key={row.driver_number}>
              <button
                type="button"
                onClick={(e) => {
                  if (e.shiftKey) {
                    toggleComparison(row.driver_number)
                  } else {
                    select(row.driver_number)
                  }
                }}
                className={`group flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors ${
                  isSelected
                    ? 'bg-zinc-100/10 ring-1 ring-inset ring-zinc-100/30'
                    : isComparison
                      ? 'bg-sky-500/10 ring-1 ring-inset ring-sky-500/30'
                      : 'hover:bg-zinc-800/50'
                }`}
                title="Click to focus · Shift-click to compare"
              >
                {/* Position number */}
                <span className="tnum w-6 text-right text-xs font-semibold text-zinc-400">
                  P{row.position}
                </span>
                {/* Team-color stripe */}
                <span
                  className="h-6 w-1 rounded-sm"
                  style={{ backgroundColor: teamColor }}
                  aria-hidden
                />
                {/* Driver number + name */}
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="tnum text-[10px] text-zinc-500">#{row.driver_number}</span>
                  <span className="truncate text-xs font-medium text-zinc-100">
                    {row.driver.name_acronym || row.driver.full_name}
                  </span>
                </span>
                {/* Team abbreviation */}
                <span className="truncate text-[10px] text-zinc-500">
                  {row.driver.team_name}
                </span>
                {/* Comparison badge */}
                {isComparison && (
                  <span className="rounded bg-sky-500/30 px-1 text-[9px] font-bold uppercase text-sky-200">
                    cmp
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
