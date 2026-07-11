import { useCallback, useEffect, useRef, useState } from 'react'
import { useVoiceSession } from '../lib/useVoiceSession'
import type { VoiceStatus } from '../lib/types'

interface VoiceControlProps {
  sessionId: string
  onTranscript: (text: string) => void
  onReplyText: (text: string) => void
}

const STATUS_LABEL: Record<VoiceStatus, string> = {
  idle: 'Tap to talk',
  connecting: 'Connecting…',
  ready: 'Tap to talk',
  listening: 'Listening… tap to send',
  thinking: 'Thinking…',
  speaking: 'Speaking…',
  error: 'Tap to try again',
}

const BUTTON_COLOR: Record<VoiceStatus, string> = {
  idle: 'bg-violet-600 hover:bg-violet-500',
  connecting: 'bg-violet-600',
  ready: 'bg-violet-600 hover:bg-violet-500',
  listening: 'bg-amber-500 hover:bg-amber-400',
  thinking: 'bg-violet-600',
  speaking: 'bg-cyan-500',
  error: 'bg-red-500 hover:bg-red-400',
}

const LABEL_COLOR: Record<VoiceStatus, string> = {
  idle: 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900',
  connecting: 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900',
  ready: 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900',
  listening: 'bg-amber-600 text-white',
  thinking: 'bg-violet-600 text-white',
  speaking: 'bg-cyan-600 text-white',
  error: 'bg-red-600 text-white',
}

function MicIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 0 1-14 0M12 18v3" />
    </svg>
  )
}

function StopIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  )
}

export function VoiceControl({ sessionId, onTranscript, onReplyText }: VoiceControlProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const ringRef = useRef<HTMLSpanElement>(null)
  const rafRef = useRef<number | null>(null)

  const onErrorMessage = useCallback((message: string) => setErrorMessage(message), [])

  const { status, levelsRef, startRecording, stopRecording, supported } = useVoiceSession({
    sessionId,
    onTranscript: (text) => {
      setErrorMessage(null)
      onTranscript(text)
    },
    onReplyText,
    onErrorMessage,
  })

  // Drive the glow ring straight off the audio-level ref every frame, the
  // same "ref, not state" contract the rest of the voice pipeline uses, so
  // the mic button pulses with real mic/playback level without a re-render
  // per sample — no separate floating orb, just this button reacting.
  useEffect(() => {
    const active = status === 'listening' || status === 'speaking'
    if (!active) {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      if (ringRef.current) {
        ringRef.current.style.transform = 'scale(1)'
        ringRef.current.style.opacity = '0'
      }
      return
    }
    const tick = () => {
      const level = status === 'listening' ? levelsRef.current.input : levelsRef.current.output
      const boosted = Math.min(1, level * 6)
      if (ringRef.current) {
        ringRef.current.style.transform = `scale(${1 + boosted * 0.7})`
        ringRef.current.style.opacity = `${0.2 + boosted * 0.5}`
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    tick()
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [status, levelsRef])

  if (!supported) {
    return (
      <span
        className="text-xs text-amber-600 dark:text-amber-400"
        title="Voice requires microphone access over https or localhost."
      >
        🎤 unavailable
      </span>
    )
  }

  const disabled = status === 'thinking' || status === 'speaking' || status === 'connecting'
  const label = errorMessage ?? STATUS_LABEL[status]

  function handleClick() {
    if (status === 'listening') {
      stopRecording()
    } else {
      void startRecording()
    }
  }

  return (
    <div className="relative shrink-0">
      <div
        key={label}
        className={`pointer-events-none absolute -top-9 right-0 animate-[fade-in_0.15s_ease-out] whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium shadow-md ${LABEL_COLOR[status]}`}
      >
        {label}
      </div>

      <button
        type="button"
        aria-label={status === 'listening' ? 'Tap to stop and send' : 'Tap to talk'}
        aria-pressed={status === 'listening'}
        onClick={handleClick}
        disabled={disabled}
        className={`relative flex h-10 w-10 select-none items-center justify-center rounded-full text-white shadow-lg transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-60 ${BUTTON_COLOR[status]}`}
      >
        <span
          ref={ringRef}
          className="pointer-events-none absolute inset-0 rounded-full bg-white/40 opacity-0"
          style={{ transform: 'scale(1)' }}
        />
        {status === 'listening' ? (
          <StopIcon className="relative h-3.5 w-3.5" />
        ) : (
          <MicIcon className="relative h-4 w-4" />
        )}
      </button>
    </div>
  )
}
