import { useEffect, useRef, useState } from 'react'
import { Panel, type PanelStatus } from './Panel'
import { useAgentStore } from '../store/agentStore'
import { useSessionStore } from '../store/sessionStore'
import { useDriverStore } from '../store/driverStore'

interface AgentChatPanelProps {
  // WS send function (from useWebSocket).
  send: (payload: unknown) => boolean
  // Whether the WS connection is open.
  wsReady: boolean
}

const SUGGESTED_PROMPTS = [
  'Who is leading right now?',
  'Compare VER and NOR on sector 2',
  'What happened on lap 12?',
  'Which driver has the fastest lap?',
]

export function AgentChatPanel({ send, wsReady }: AgentChatPanelProps) {
  const sessionKey = useSessionStore((s) => s.sessionKey)
  const mode = useSessionStore((s) => s.mode)
  const selectedDriverNumber = useDriverStore((s) => s.selectedDriverNumber)
  const messages = useAgentStore((s) => s.messages)
  const thinking = useAgentStore((s) => s.thinking)
  const pushUserMessage = useAgentStore((s) => s.pushUserMessage)
  const clear = useAgentStore((s) => s.clear)

  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLUListElement>(null)

  // Auto-scroll to the latest message as tokens stream in.
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  // Reset chat when the session changes.
  useEffect(() => {
    clear()
    setDraft('')
  }, [sessionKey, clear])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!sessionKey || !wsReady) return
    const text = draft.trim()
    if (!text) return

    pushUserMessage(text)
    setDraft('')
    send({
      action: 'agent.ask',
      text,
      sessionKey,
      driverNumber: selectedDriverNumber,
    })
  }

  function handleSuggestedPrompt(prompt: string) {
    if (!sessionKey || !wsReady) return
    pushUserMessage(prompt)
    send({
      action: 'agent.ask',
      text: prompt,
      sessionKey,
      driverNumber: selectedDriverNumber,
    })
  }

  const status: PanelStatus = !sessionKey
    ? 'idle'
    : !wsReady
      ? 'stale'
      : 'ready'

  return (
    <Panel
      title="Race Engineer"
      status={status}
      idleMessage="Pick a session to ask the race engineer"
      className="w-[360px] shrink-0"
      headerExtra={
        sessionKey ? (
          <span className="font-mono">
            {sessionKey}
            {selectedDriverNumber != null ? ` · #${selectedDriverNumber}` : ''}
          </span>
        ) : null
      }
    >
      <div className="flex h-full flex-col">
        {/* Messages */}
        <ul ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
          {messages.length === 0 && sessionKey && (
            <>
              <li className="px-1 text-xs text-zinc-500">
                Ask about lap deltas, sectors, or driver comparisons. Replies
                {mode === 'live' ? ' stream live' : ' use the session replay'}.
              </li>
              <li className="space-y-1.5 pt-2">
                {SUGGESTED_PROMPTS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    disabled={!wsReady}
                    onClick={() => handleSuggestedPrompt(p)}
                    className="block w-full rounded border border-zinc-800 bg-zinc-950/40 px-2.5 py-1.5 text-left text-xs text-zinc-300 transition-colors hover:border-zinc-700 hover:bg-zinc-800/50 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {p}
                  </button>
                ))}
              </li>
            </>
          )}

          {messages.map((m) => (
            <li
              key={m.id}
              className={`rounded-md px-2.5 py-1.5 text-xs ${
                m.role === 'user'
                  ? 'ml-6 bg-zinc-100/10 text-zinc-100'
                  : 'mr-6 bg-zinc-950/60 text-zinc-300'
              }`}
            >
              <div className="mb-0.5 text-[9px] font-semibold uppercase tracking-wider text-zinc-500">
                {m.role === 'user' ? 'You' : 'Engineer'}
              </div>
              <p className="whitespace-pre-wrap">{m.text || (m.streaming ? '…' : '')}</p>
            </li>
          ))}

          {thinking && (
            <li className="mr-6 text-[11px] text-zinc-500">Engineer is thinking…</li>
          )}
        </ul>

        {/* Composer */}
        <form
          onSubmit={handleSubmit}
          className="flex shrink-0 gap-2 border-t border-zinc-800 p-2"
        >
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={sessionKey ? 'Ask the race engineer…' : 'Pick a session first'}
            disabled={!sessionKey || !wsReady}
            className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!sessionKey || !wsReady || !draft.trim()}
            className="shrink-0 rounded-md border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-xs font-semibold text-zinc-100 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </Panel>
  )
}
