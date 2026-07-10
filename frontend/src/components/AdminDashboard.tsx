import { useEffect, useMemo, useRef, useState } from 'react'
import { useLogsSocket } from '../lib/useLogsSocket'
import { LogEventRow } from './LogEventRow'
import type { LogEventType } from '../lib/types'

const ALL_TYPES: LogEventType[] = ['thinking', 'tool_call', 'tool_result', 'retry', 'error', 'decision', 'message']

export function AdminDashboard() {
  const { events, connected } = useLogsSocket()
  const [activeTypes, setActiveTypes] = useState<Set<LogEventType>>(new Set(ALL_TYPES))
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const sessionIds = useMemo(() => {
    const ids = new Set(events.map((e) => e.session_id))
    return Array.from(ids)
  }, [events])
  const [sessionFilter, setSessionFilter] = useState<string>('all')

  const filtered = useMemo(
    () =>
      events.filter(
        (e) => activeTypes.has(e.type) && (sessionFilter === 'all' || e.session_id === sessionFilter),
      ),
    [events, activeTypes, sessionFilter],
  )

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [filtered, autoScroll])

  function toggleType(type: LogEventType) {
    setActiveTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const counts = useMemo(() => {
    const c: Partial<Record<LogEventType, number>> = {}
    for (const e of events) c[e.type] = (c[e.type] ?? 0) + 1
    return c
  }, [events])

  return (
    <div className="mx-auto flex h-[calc(100dvh-4rem)] w-full max-w-5xl flex-col px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Agent Reasoning Log</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Live event stream from every chat and voice session — thinking, tool calls, retries, and final decisions.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span className="text-zinc-500 dark:text-zinc-400">{connected ? 'Connected' : 'Reconnecting…'}</span>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {ALL_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => toggleType(type)}
            className={`rounded-full border px-2.5 py-1 text-xs font-medium transition ${
              activeTypes.has(type)
                ? 'border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-500/40 dark:bg-violet-500/10 dark:text-violet-300'
                : 'border-zinc-200 bg-white text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-600'
            }`}
          >
            {type} <span className="opacity-60">{counts[type] ?? 0}</span>
          </button>
        ))}

        <select
          value={sessionFilter}
          onChange={(e) => setSessionFilter(e.target.value)}
          className="ml-auto rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
        >
          <option value="all">All sessions</option>
          {sessionIds.map((id) => (
            <option key={id} value={id}>
              {id.slice(0, 8)}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="accent-violet-600"
          />
          Auto-scroll
        </label>
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-zinc-200 bg-white/70 backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-900/60"
      >
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center p-8 text-center text-sm text-zinc-400 dark:text-zinc-600">
            No events yet — start a chat or voice session to see the agent's reasoning here in real time.
          </div>
        ) : (
          filtered.map((event) => <LogEventRow key={event.seq} event={event} />)
        )}
      </div>
    </div>
  )
}
