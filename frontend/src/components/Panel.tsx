import type { ComponentProps, ReactNode } from 'react'

// Shared panel shell — title bar + status + body. Used by every panel so
// the dashboard reads as one cohesive timing-screen rather than a bunch of
// cards.

export type PanelStatus = 'idle' | 'loading' | 'ready' | 'stale' | 'error'

interface PanelProps extends ComponentProps<'section'> {
  title: string
  status?: PanelStatus
  // Right-aligned extra in the header (e.g. mono session key).
  headerExtra?: ReactNode
  // Shown when status === 'idle' (no session selected yet).
  idleMessage?: string
  // Shown when status === 'loading' and there's no data yet.
  skeleton?: ReactNode
  // Optional fixed width (Tailwind class string) — left/right panels set
  // this, the middle column flexes.
  className?: string
  bodyClassName?: string
  children: ReactNode
}

const STATUS_DOT: Record<PanelStatus, string> = {
  idle: 'bg-zinc-600',
  loading: 'bg-amber-400 animate-pulse',
  ready: 'bg-emerald-400',
  stale: 'bg-amber-400',
  error: 'bg-rose-500',
}

export function Panel({
  title,
  status = 'ready',
  headerExtra,
  idleMessage,
  skeleton,
  className = '',
  bodyClassName = '',
  children,
  ...rest
}: PanelProps) {
  return (
    <section
      {...rest}
      className={`flex min-h-0 flex-col overflow-hidden rounded-md border border-zinc-800 bg-zinc-900/60 ${className}`}
    >
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-zinc-800 px-3 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} aria-hidden />
          <h2 className="truncate text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-400">
            {title}
          </h2>
        </div>
        {headerExtra && <div className="truncate text-[10px] text-zinc-500">{headerExtra}</div>}
      </header>

      <div className={`min-h-0 flex-1 ${bodyClassName}`}>
        {status === 'idle' && idleMessage ? (
          <div className="flex h-full items-center justify-center px-4 py-6 text-center text-xs text-zinc-500">
            {idleMessage}
          </div>
        ) : status === 'loading' && skeleton ? (
          <div className="space-y-2 p-3">{skeleton}</div>
        ) : (
          children
        )}
      </div>
    </section>
  )
}

export function SkeletonBlock({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-zinc-800/80 ${className}`} />
}
