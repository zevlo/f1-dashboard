import { useEffect, useRef } from 'react'
import { useReplayStore } from '../store/replayStore'

// Replay transport controls — play/pause, speed cycle, scrubber bar. Only
// visible in historical mode. Drives the replay clock via requestAnimationFrame.
//
// The clock advances scrubTs at wall-clock * speed. When scrubTs crosses
// bounds[1] (session end), it pauses (no loop — keeps the UX predictable).

interface ReplayControlsProps {
  // Total lap count + flag markers on the scrubber, used to render ticks.
  latestLap: number | null
}

export function ReplayControls({ latestLap }: ReplayControlsProps) {
  const isPlaying = useReplayStore((s) => s.isPlaying)
  const speed = useReplayStore((s) => s.speed)
  const scrubTs = useReplayStore((s) => s.scrubTs)
  const bounds = useReplayStore((s) => s.bounds)
  const mode = useReplayStore((s) => s.mode)
  const toggle = useReplayStore((s) => s.toggle)
  const cycleSpeed = useReplayStore((s) => s.cycleSpeed)
  const seek = useReplayStore((s) => s.seek)

  const rafRef = useRef<number | null>(null)
  const lastTickRef = useRef<number | null>(null)

  // RAF-driven clock. Re-subscribes only when isPlaying/mode/bounds change —
  // NOT on every scrub advance (avoids cancelling + restarting RAF 60×/sec).
  // scrubTs + speed are read via getState() inside the tick closure.
  useEffect(() => {
    if (!isPlaying || mode !== 'historical' || !bounds) return
    lastTickRef.current = null

    const tick = (now: number) => {
      if (lastTickRef.current == null) {
        lastTickRef.current = now
      }
      const elapsedMs = now - lastTickRef.current
      lastTickRef.current = now

      const state = useReplayStore.getState()
      const current = state.scrubTs
      const [start, end] = state.bounds!
      const startMs = Date.parse(start)
      const endMs = Date.parse(end)
      const currentMs = current ? Date.parse(current) : startMs

      const advancedMs = currentMs + elapsedMs * state.speed
      if (advancedMs >= endMs) {
        state.setScrub(end)
        state.pause()
        return
      }
      state.setScrub(new Date(advancedMs).toISOString())
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [isPlaying, mode, bounds])

  if (mode !== 'historical' || !bounds) return null

  const startMs = Date.parse(bounds[0])
  const endMs = Date.parse(bounds[1])
  const totalMs = endMs - startMs
  const currentMs = scrubTs ? Date.parse(scrubTs) : startMs
  const progress = totalMs > 0 ? Math.max(0, Math.min(1, (currentMs - startMs) / totalMs)) : 0

  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-t border-zinc-800 bg-zinc-900/60 px-3">
      <button
        type="button"
        onClick={toggle}
        className="flex h-7 w-7 items-center justify-center rounded-full border border-zinc-600 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
        title={isPlaying ? 'Pause' : 'Play'}
      >
        {isPlaying ? (
          <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor">
            <rect x="3" y="2" width="3.5" height="12" rx="1" />
            <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" className="h-3 w-3 translate-x-[1px]" fill="currentColor">
            <path d="M3 2v12l11-6L3 2z" />
          </svg>
        )}
      </button>

      <button
        type="button"
        onClick={cycleSpeed}
        className="tnum min-w-[36px] rounded border border-zinc-700 bg-zinc-950 px-2 py-0.5 text-xs font-semibold text-zinc-200 hover:bg-zinc-800"
        title="Cycle speed"
      >
        {speed}×
      </button>

      <input
        type="range"
        min={0}
        max={1000}
        value={Math.round(progress * 1000)}
        onChange={(e) => {
          const ratio = Number(e.target.value) / 1000
          const ms = startMs + ratio * totalMs
          seek(new Date(ms).toISOString())
        }}
        className="flex-1 accent-amber-400"
        aria-label="Scrub session"
      />

      <span className="tnum text-[11px] text-zinc-500" style={{ minWidth: 90 }}>
        {scrubTs ? new Date(scrubTs).toLocaleTimeString([], { hour12: false }) : '—'}
      </span>

      {latestLap != null && (
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          Lap {latestLap}
        </span>
      )}
    </div>
  )
}
