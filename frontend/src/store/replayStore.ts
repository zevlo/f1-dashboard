import { create } from 'zustand'

// Replay clock — single source of truth for "what moment is the dashboard
// currently showing" in historical mode. Live mode ignores this store (the
// WebSocket drives live ticks into the TanStack Query cache directly).
//
// `scrubTs` is the ISO timestamp the dashboard should render at. The clock
// advances it via requestAnimationFrame in src/ws/useReplayClock.ts based on
// real elapsed wall-clock * speed. Components subscribe to scrubTs and derive
// their visible data via derive/telemetryAt.

import type { SessionMode } from '../types'

interface ReplayState {
  // Whether the clock is advancing (play button). False at session load.
  isPlaying: boolean
  // Multiplier on real-time. 1 = real playback, 4 = 4x, 10 = 10x skip.
  speed: 1 | 4 | 10
  // Current moment the dashboard is showing. Null = "show the latest data".
  scrubTs: string | null
  // Session time bounds ([start, end]). Set when a session loads so the
  // clock knows when to stop / loop.
  bounds: [string, string] | null
  // Active only in historical mode; live mode ignores the clock.
  mode: SessionMode | null

  play: () => void
  pause: () => void
  toggle: () => void
  cycleSpeed: () => void
  seek: (ts: string | null) => void
  setBounds: (bounds: [string, string] | null) => void
  setMode: (mode: SessionMode | null) => void
  setScrub: (ts: string | null) => void
  reset: () => void
}

export const useReplayStore = create<ReplayState>((set) => ({
  isPlaying: false,
  speed: 1,
  scrubTs: null,
  bounds: null,
  mode: null,

  play: () => set({ isPlaying: true }),
  pause: () => set({ isPlaying: false }),
  toggle: () => set((s) => ({ isPlaying: !s.isPlaying })),
  cycleSpeed: () =>
    set((s) => ({
      speed: s.speed === 1 ? 4 : s.speed === 4 ? 10 : 1,
    })),
  seek: (ts) => set({ scrubTs: ts }),
  setBounds: (bounds) => set({ bounds }),
  setMode: (mode) => set({ mode }),
  setScrub: (ts) => set({ scrubTs: ts }),
  reset: () =>
    set({
      isPlaying: false,
      speed: 1,
      scrubTs: null,
      bounds: null,
    }),
}))
