import { useMemo } from 'react'
import { useSessions } from '../api/hooks'
import type { Session, WsConnectionStatus } from '../types'

interface TopBarProps {
  selectedSessionKey: string | null
  session: Session | null
  sessionLoading: boolean
  mode: 'live' | 'historical' | null
  connectionStatus: WsConnectionStatus
  currentLap: number | null
  onSessionChange: (sessionKey: string | null) => void
  onRetryConnection: () => void
}

export function TopBar({
  selectedSessionKey,
  session,
  sessionLoading,
  mode,
  connectionStatus,
  currentLap,
  onSessionChange,
  onRetryConnection,
}: TopBarProps) {
  const sessionsQuery = useSessions()
  const sessions = sessionsQuery.data?.items ?? []

  const connectionLabel = useMemo(() => {
    switch (connectionStatus) {
      case 'connected':
        return null // don't show banner when everything's fine
      case 'connecting':
        return { text: 'Connecting…', tone: 'text-amber-400' }
      case 'reconnecting':
        return { text: 'Reconnecting…', tone: 'text-amber-400' }
      case 'disconnected':
        return { text: 'Disconnected — retry', tone: 'text-rose-400 underline cursor-pointer' }
      default:
        return null
    }
  }, [connectionStatus])

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-zinc-800 px-4">
      {/* Brand + circuit */}
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="text-sm font-bold uppercase tracking-[0.3em] text-zinc-200">F1</h1>
        {session ? (
          <div className="flex items-baseline gap-2 truncate">
            <span className="truncate text-sm font-semibold text-zinc-100">
              {session.session_name ?? 'Session'}{' '}
              <span className="text-zinc-500">·</span>{' '}
              <span className="text-zinc-300">{session.circuit_short_name}</span>
            </span>
            <span className="text-[11px] text-zinc-500">{session.country_name}</span>
          </div>
        ) : (
          <span className="text-sm text-zinc-500">{sessionLoading ? 'Loading…' : 'Pick a session'}</span>
        )}
      </div>

      {/* Session picker */}
      <select
        value={selectedSessionKey ?? ''}
        onChange={(e) => onSessionChange(e.target.value || null)}
        className="ml-auto rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 focus:border-zinc-500 focus:outline-none"
      >
        <option value="">— session —</option>
        {sessions.map((s) => (
          <option key={s.session_key} value={s.session_key}>
            {s.year} {s.session_name} · {s.circuit_short_name}
          </option>
        ))}
      </select>

      {/* Mode pill */}
      {mode && (
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
            mode === 'live'
              ? 'bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/40'
              : 'bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40'
          }`}
        >
          {mode === 'live' ? 'Live' : 'Replay'}
        </span>
      )}

      {/* Lap counter */}
      {currentLap !== null && (
        <div className="flex flex-col items-end leading-none">
          <span className="text-[9px] uppercase tracking-wider text-zinc-500">Lap</span>
          <span className="tnum text-base font-semibold text-zinc-100">{currentLap}</span>
        </div>
      )}

      {/* Connection status */}
      {connectionLabel && (
        <button
          type="button"
          onClick={connectionStatus === 'disconnected' ? onRetryConnection : undefined}
          className={`text-[11px] font-medium ${connectionLabel.tone}`}
        >
          {connectionLabel.text}
        </button>
      )}
    </header>
  )
}
