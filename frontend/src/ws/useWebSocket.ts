import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { config } from '../config'
import { useAgentStore } from '../store/agentStore'
import { useSessionStore } from '../store/sessionStore'
import type {
  CarTelemetry,
  Lap,
  PositionSample,
  RaceControlEvent,
  WsConnectionStatus,
  WsMessage,
} from '../types'
interface UseWebSocketOptions {
  // Full WS URL or null to disable. Caller composes this from config.wsUrl
  // + the selected sessionKey.
  url: string | null
  onReconnect?: () => void
}

// Single WebSocket connection per session. Reconnects with bounded backoff
// and re-emits "ready" via the status field. Dispatches every server message
// either into the TanStack Query cache (telemetry) or into the agentStore
// (chat stream).
//
// Reconnect strategy: 1s, 2s, 4s, 8s, then steady-state 15s. Exponential up
// to 8s caps the early "did the user's wifi just blip" window; 15s steady
// avoids hammering the API when the backend is genuinely down.
const BACKOFF_STEPS = [1_000, 2_000, 4_000, 8_000, 15_000]

export function useWebSocket({ url, onReconnect }: UseWebSocketOptions) {
  const [status, setStatus] = useState<WsConnectionStatus>('idle')
  const queryClient = useQueryClient()
  const sessionKey = useSessionStore((s) => s.sessionKey)

  // Stable refs to avoid re-running the effect on every render.
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttempt = useRef(0)
  // Track the URL we're currently connected to so a session switch cleanly
  // tears down the old socket before opening a new one.
  const connectedUrl = useRef<string | null>(null)
  // Snapshot of the latest onReconnect callback so we can call it without
  // re-running the effect.
  const onReconnectRef = useRef(onReconnect)
  onReconnectRef.current = onReconnect

  // Agent store access via getState() to avoid re-running the connect effect
  // when chat messages stream in.
  const clearReconnect = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
  }, [])

  const handleMessage = useCallback(
    (raw: MessageEvent) => {
      let msg: WsMessage
      try {
        msg = JSON.parse(raw.data) as WsMessage
      } catch {
        return
      }
      if (!sessionKey) return

      switch (msg.type) {
        case 'position.update': {
          const { driver_number, position, ts } = msg.data
          const sample: PositionSample = {
            session_key: sessionKey,
            ts_driver: `${ts}#${driver_number}`,
            driver_number,
            position,
            date: ts,
          }
          // Append into both the positions list and the replay payload's positions
          // list (whichever exists in the cache).
          queryClient.setQueryData<PositionSample[]>(['positions', sessionKey], (prev) =>
            prev ? [...prev, sample] : [sample],
          )
          queryClient.setQueryData<{ positions: PositionSample[] } | undefined>(
            ['replay', sessionKey],
            (prev) =>
              prev ? { ...prev, positions: [...prev.positions, sample] } : prev,
          )
          break
        }
        case 'car_data.update': {
          // Live car telemetry isn't stored in the cache (it's per-sample, not
          // a queryable list) — emit via a custom event so the telemetry panel
          // can pick it up via useSyncExternalStore-like subscription.
          window.dispatchEvent(new CustomEvent<CarTelemetry>('f1:car_data', { detail: msg.data }))
          break
        }
        case 'race_control.event': {
          const { ts, ...rest } = msg.data
          const event: RaceControlEvent = {
            session_key: sessionKey,
            timestamp: ts,
            ...rest,
          }
          queryClient.setQueryData<RaceControlEvent[]>(['race-control', sessionKey], (prev) =>
            prev ? [...prev, event] : [event],
          )
          queryClient.setQueryData<{ race_control: RaceControlEvent[] } | undefined>(
            ['replay', sessionKey],
            (prev) =>
              prev ? { ...prev, race_control: [...prev.race_control, event] } : prev,
          )
          break
        }
        case 'flag.change': {
          // Surface as a custom event the FlagBanner can subscribe to.
          window.dispatchEvent(new CustomEvent('f1:flag', { detail: msg.data.flag }))
          break
        }
        case 'lap.complete': {
          const { driver_number, ...rest } = msg.data
          const lap: Lap = {
            session_driver: `${sessionKey}#${driver_number}`,
            ...rest,
          }
          // Push into every laps query whose driver list includes this driver.
          // We don't know the exact query keys ahead of time, so iterate.
          queryClient.setQueriesData<{ laps: Lap[] } | Lap[]>({ queryKey: ['laps', sessionKey] }, (prev) => {
            if (!prev) return prev
            if (Array.isArray(prev)) {
              if (prev.some((l) => l.session_driver === lap.session_driver && l.lap_number === lap.lap_number)) {
                return prev
              }
              return [...prev, lap]
            }
            return prev
          })
          queryClient.setQueryData<{ laps: Lap[] } | undefined>(['replay', sessionKey], (prev) =>
            prev
              ? {
                  ...prev,
                  laps: prev.laps.some(
                    (l) => l.session_driver === lap.session_driver && l.lap_number === lap.lap_number,
                  )
                    ? prev.laps
                    : [...prev.laps, lap],
                }
              : prev,
          )
          break
        }
        case 'agent.token': {
          const { streamingId } = useAgentStore.getState()
          if (!streamingId) {
            useAgentStore.getState().beginAssistantStream(msg.messageId)
          }
          useAgentStore.getState().appendToken(msg.messageId, msg.token)
          break
        }
        case 'agent.done': {
          const { streamingId } = useAgentStore.getState()
          if (streamingId === msg.messageId || streamingId === null) {
            useAgentStore.getState().finalizeStream(msg.messageId)
          }
          break
        }
        case 'agent.error': {
          const { streamingId } = useAgentStore.getState()
          useAgentStore.getState().markError(streamingId ?? msg.messageId ?? 'error', msg.error)
          break
        }
      }
    },
    [queryClient, sessionKey],
  )

  const connect = useCallback(() => {
    if (!url) return
    if (socketRef.current && connectedUrl.current === url) return

    // Clean up any previous socket
    if (socketRef.current) {
      try {
        socketRef.current.close()
      } catch {
        // ignore
      }
      socketRef.current = null
    }

    setStatus('connecting')
    const socket = new WebSocket(url)
    socketRef.current = socket
    connectedUrl.current = url

    socket.onopen = () => {
      reconnectAttempt.current = 0
      setStatus('connected')
    }
    socket.onmessage = handleMessage
    socket.onclose = () => {
      socketRef.current = null
      connectedUrl.current = null
      if (url) {
        setStatus('reconnecting')
        const delay = BACKOFF_STEPS[Math.min(reconnectAttempt.current, BACKOFF_STEPS.length - 1)]
        reconnectAttempt.current += 1
        clearReconnect()
        reconnectTimer.current = setTimeout(() => {
          // Re-fire connect with the same URL.
          if (connectedUrl.current === null) {
            onReconnectRef.current?.()
            connect()
          }
        }, delay)
      } else {
        setStatus('idle')
      }
    }
    socket.onerror = () => {
      // Let onclose handle the reconnect bookkeeping.
      setStatus('reconnecting')
    }
  }, [url, handleMessage, clearReconnect])

  useEffect(() => {
    if (!url) {
      // disconnect cleanly
      if (socketRef.current) {
        try {
          socketRef.current.close()
        } catch {
          // ignore
        }
        socketRef.current = null
        connectedUrl.current = null
      }
      setStatus('idle')
      return
    }
    connect()
    return () => {
      clearReconnect()
      if (socketRef.current) {
        try {
          socketRef.current.close()
        } catch {
          // ignore
        }
        socketRef.current = null
        connectedUrl.current = null
      }
    }
  }, [url, connect, clearReconnect])

  const send = useCallback((payload: unknown) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const retry = useCallback(() => {
    reconnectAttempt.current = 0
    connect()
  }, [connect])

  // Expose config.wsUrl + url-builder helper for callers.
  return { status, send, retry, wsUrl: config.wsUrl }
}
