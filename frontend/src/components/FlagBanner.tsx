import { useEffect, useState } from 'react'

// Slim flag banner — replaces the v1 race-control panel. Listens for
// `f1:flag` window events dispatched by the WebSocket hook (live mode) and
// derives a banner colour + label. Hidden when no flag is active.
//
// In replay mode, the App passes the current race-control flag via the
// `flag` prop instead.

const FLAG_STYLE: Record<string, { bg: string; label: string }> = {
  RED: { bg: 'bg-rose-600', label: 'Red flag' },
  YELLOW: { bg: 'bg-amber-400 text-zinc-950', label: 'Yellow flag' },
  'DOUBLE YELLOW': { bg: 'bg-amber-400 text-zinc-950', label: 'Double yellow' },
  GREEN: { bg: 'bg-emerald-600', label: 'Green flag' },
  BLUE: { bg: 'bg-sky-600', label: 'Blue flag' },
  CHEQUERED: { bg: 'bg-zinc-100 text-zinc-950', label: 'Chequered' },
  BLACK: { bg: 'bg-zinc-950 ring-1 ring-zinc-700', label: 'Black flag' },
  WHITE: { bg: 'bg-zinc-100 text-zinc-950', label: 'White flag' },
}

interface FlagBannerProps {
  // Set in replay mode (latest flag at scrubTs). Null in live mode — banner
  // listens to window events instead.
  flag: string | null
  // Latest race-control message at the current moment (optional sub-text).
  message?: string | null
}

export function FlagBanner({ flag, message }: FlagBannerProps) {
  // In live mode, listen for `f1:flag` window events.
  const [liveFlag, setLiveFlag] = useState<string | null>(null)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<string | null>).detail
      setLiveFlag(detail)
    }
    window.addEventListener('f1:flag', handler)
    return () => window.removeEventListener('f1:flag', handler)
  }, [])

  const activeFlag = liveFlag ?? flag
  if (!activeFlag) return null

  const style = FLAG_STYLE[activeFlag] ?? {
    bg: 'bg-zinc-800 text-zinc-200',
    label: activeFlag,
  }

  return (
    <div className={`flex h-8 shrink-0 items-center justify-between gap-3 px-4 text-xs font-semibold ${style.bg}`}>
      <span className="uppercase tracking-[0.2em]">{style.label}</span>
      {message && <span className="truncate text-[11px] opacity-80">{message}</span>}
    </div>
  )
}
