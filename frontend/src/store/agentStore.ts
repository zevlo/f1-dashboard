import { create } from 'zustand'

// Race-engineer chat state. Holds the message log + the streaming state for
// the currently-being-generated assistant reply.
//
// The WebSocket hook appends tokens to the streaming buffer as
// `agent.token` events arrive, then promotes the buffer to a finished
// message when `agent.done` arrives. This keeps the per-render cost low
// (only one array push per token) and isolates the chat state from the rest
// of the dashboard (no driver click should ever re-render the chat).

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  ts: number
  // True for the assistant message currently receiving tokens. Cleared on
  // agent.done / agent.error.
  streaming?: boolean
}

interface AgentState {
  messages: ChatMessage[]
  // The id of the assistant message currently being streamed into. Set when
  // the first agent.token arrives; cleared on agent.done.
  streamingId: string | null
  // True between when the user sends a prompt and when the first token (or
  // error) arrives. Drives the "Engineer is thinking…" placeholder.
  thinking: boolean

  pushUserMessage: (text: string) => void
  beginAssistantStream: (messageId: string) => void
  appendToken: (messageId: string, token: string) => void
  finalizeStream: (messageId: string) => void
  markError: (messageId: string, error: string) => void
  clear: () => void
}

let seq = 0
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++seq}`

export const useAgentStore = create<AgentState>((set) => ({
  messages: [],
  streamingId: null,
  thinking: false,

  pushUserMessage: (text) =>
    set((s) => ({
      messages: [...s.messages, { id: nextId('u'), role: 'user', text, ts: Date.now() }],
      thinking: true,
    })),

  beginAssistantStream: (messageId) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: messageId, role: 'assistant', text: '', ts: Date.now(), streaming: true },
      ],
      streamingId: messageId,
      thinking: false,
    })),

  appendToken: (messageId, token) =>
    set((s) => {
      if (s.streamingId !== messageId) return s
      return {
        messages: s.messages.map((m) =>
          m.id === messageId ? { ...m, text: m.text + token } : m,
        ),
      }
    }),

  finalizeStream: (messageId) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, streaming: false } : m,
      ),
      streamingId: null,
      thinking: false,
    })),

  markError: (messageId, error) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? { ...m, text: m.text || `Error: ${error}`, streaming: false }
          : m,
      ),
      streamingId: null,
      thinking: false,
    })),

  clear: () => set({ messages: [], streamingId: null, thinking: false }),
}))
