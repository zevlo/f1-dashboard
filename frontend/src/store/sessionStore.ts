import { create } from 'zustand'
import type { SessionMode } from '../types'

// Selected session + derived mode (live vs historical). The mode is computed
// from the Session record in useSession() and pushed here when it resolves,
// so the rest of the UI can read it synchronously without re-deriving.
//
// The only state mutations that cause network traffic are sessionKey changes
// — everything else (driver click, scrub, etc.) lives in other stores and is
// pure-UI.

interface SessionState {
  sessionKey: string | null
  mode: SessionMode | null
  setSession: (sessionKey: string | null, mode: SessionMode | null) => void
  setMode: (mode: SessionMode) => void
  clear: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionKey: null,
  mode: null,
  setSession: (sessionKey, mode) => set({ sessionKey, mode }),
  setMode: (mode) => set({ mode }),
  clear: () => set({ sessionKey: null, mode: null }),
}))
