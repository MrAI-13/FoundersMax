import { useState } from 'react'
import type { LogEvent, LogEventType } from '../lib/types'

const TYPE_STYLES: Record<LogEventType, { label: string; dot: string; badge: string }> = {
  thinking: {
    label: 'Thinking',
    dot: 'bg-zinc-400',
    badge: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  },
  tool_call: {
    label: 'Tool call',
    dot: 'bg-blue-500',
    badge: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
  },
  tool_result: {
    label: 'Tool result',
    dot: 'bg-emerald-500',
    badge: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  },
  retry: {
    label: 'Retry',
    dot: 'bg-amber-500',
    badge: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  },
  error: {
    label: 'Error',
    dot: 'bg-red-500',
    badge: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300',
  },
  decision: {
    label: 'Decision',
    dot: 'bg-violet-500',
    badge: 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300',
  },
  message: {
    label: 'Message',
    dot: 'bg-cyan-500',
    badge: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-300',
  },
}

function summarizePayload(event: LogEvent): string {
  const p = event.payload
  if (event.type === 'tool_call' && typeof p.name === 'string') {
    return `${p.name}(${JSON.stringify(p.args ?? {})})`
  }
  if (event.type === 'tool_result' && typeof p.name === 'string') {
    const isError = p.is_error ? ' — error' : ''
    return `${p.name}${isError}`
  }
  if (event.type === 'decision' && typeof p.name === 'string') {
    return `${p.name}`
  }
  if (event.type === 'message' && typeof p.role === 'string') {
    const content = typeof p.content === 'string' ? p.content : ''
    return `${p.role}: ${content.slice(0, 80)}`
  }
  if (event.type === 'thinking' && typeof p.note === 'string') {
    return p.note
  }
  if ((event.type === 'error' || event.type === 'retry') && typeof p.detail === 'string') {
    return p.detail
  }
  return ''
}

export function LogEventRow({ event }: { event: LogEvent }) {
  const [expanded, setExpanded] = useState(false)
  const style = TYPE_STYLES[event.type]
  const time = new Date(event.ts).toLocaleTimeString(undefined, { hour12: false })
  const summary = summarizePayload(event)
  const channel = event.payload.channel === 'voice' ? '🎙️' : null

  return (
    <div className="border-b border-zinc-100 px-3 py-2 font-mono text-xs last:border-b-0 dark:border-zinc-800/70">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-start gap-2 text-left"
      >
        <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />
        <span className="shrink-0 text-zinc-400 dark:text-zinc-500">{time}</span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 font-sans font-medium ${style.badge}`}>{style.label}</span>
        {channel && <span className="shrink-0">{channel}</span>}
        <span className="min-w-0 flex-1 truncate text-zinc-600 dark:text-zinc-400">{summary}</span>
        <span className="shrink-0 text-zinc-300 dark:text-zinc-600">{event.session_id.slice(0, 8)}</span>
      </button>
      {expanded && (
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-zinc-50 p-2 text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </div>
  )
}
