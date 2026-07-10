import { lazy, Suspense, useCallback, useState } from 'react'
import { useVoiceSession } from '../lib/useVoiceSession'
import type { VoiceStatus } from '../lib/types'

// Deferred so the three.js/r3f/drei chunk loads alongside (not before) the
// rest of the chat UI — see Layout.tsx for the same treatment of the
// ambient background.
const VoiceOrb = lazy(() => import('./VoiceOrb').then((m) => ({ default: m.VoiceOrb })))

interface VoiceControlProps {
  sessionId: string
  onTranscript: (text: string) => void
  onReplyText: (text: string) => void
}

const STATUS_LABEL: Record<VoiceStatus, string> = {
  idle: 'Hold to talk',
  connecting: 'Connecting…',
  ready: 'Hold to talk',
  listening: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking…',
  error: 'Something went wrong — try again',
}

export function VoiceControl({ sessionId, onTranscript, onReplyText }: VoiceControlProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const onErrorMessage = useCallback((message: string) => setErrorMessage(message), [])

  const { status, levelsRef, startHold, stopHold, supported } = useVoiceSession({
    sessionId,
    onTranscript: (text) => {
      setErrorMessage(null)
      onTranscript(text)
    },
    onReplyText,
    onErrorMessage,
  })

  if (!supported) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
        Voice isn't supported in this browser — microphone access requires a secure context (https or localhost).
      </div>
    )
  }

  const busy = status === 'listening' || status === 'thinking' || status === 'speaking'

  return (
    <div className="flex flex-col items-center gap-3 py-2">
      <Suspense
        fallback={
          <div className="h-[168px] w-[168px] animate-pulse rounded-full bg-violet-500/20" />
        }
      >
        <VoiceOrb levelsRef={levelsRef} status={status} size={168} />
      </Suspense>

      <button
        type="button"
        onPointerDown={(e) => {
          e.preventDefault()
          void startHold()
        }}
        onPointerUp={stopHold}
        onPointerLeave={() => busy && status === 'listening' && stopHold()}
        disabled={status === 'thinking' || status === 'speaking' || status === 'connecting'}
        className={`select-none rounded-full px-6 py-2.5 text-sm font-medium text-white shadow-lg transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-60 ${
          status === 'listening'
            ? 'bg-amber-500 shadow-amber-500/30'
            : status === 'speaking'
              ? 'bg-cyan-500 shadow-cyan-500/30'
              : 'bg-violet-600 shadow-violet-600/30 hover:bg-violet-500'
        }`}
      >
        {STATUS_LABEL[status]}
      </button>

      {errorMessage && (
        <p className="max-w-xs text-center text-xs text-red-600 dark:text-red-400">{errorMessage}</p>
      )}
    </div>
  )
}
