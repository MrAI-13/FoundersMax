import { useEffect, useRef, useState } from 'react'
import { WS_BASE_URL } from './config'
import type { LogEvent } from './types'

const MAX_EVENTS = 500
const RECONNECT_DELAY_MS = 1500

export interface LogsSocketState {
  events: LogEvent[]
  connected: boolean
  clear: () => void
}

export function useLogsSocket(): LogsSocketState {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [connected, setConnected] = useState(false)
  const closedByUsRef = useRef(false)

  useEffect(() => {
    closedByUsRef.current = false
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      socket = new WebSocket(`${WS_BASE_URL}/ws/logs`)

      socket.onopen = () => setConnected(true)

      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as LogEvent
          setEvents((prev) => {
            // The server replays full history on every connect (including
            // reconnects after a dropped socket — e.g. a backend --reload
            // restart, or React StrictMode's double effect-invoke in dev).
            // Without this guard, each reconnect re-appends everything it
            // already sent, duplicating rows in the admin log.
            if (prev.some((e) => e.seq === parsed.seq)) return prev
            const next = [...prev, parsed]
            return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next
          })
        } catch {
          // ignore malformed frames
        }
      }

      socket.onclose = () => {
        setConnected(false)
        if (!closedByUsRef.current) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }

      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()

    return () => {
      closedByUsRef.current = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [])

  return { events, connected, clear: () => setEvents([]) }
}
