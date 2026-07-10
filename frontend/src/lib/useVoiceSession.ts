import { useCallback, useEffect, useRef, useState } from 'react'
import { WS_BASE_URL } from './config'
import { TARGET_SAMPLE_RATE, concatInt16, encodeMicChunk, float32FromInt16, int16FromBase64, rms } from './audio'
import type { VoiceStatus } from './types'

export interface AudioLevels {
  /** ~0-1 mic input amplitude, updated continuously while listening. */
  input: number
  /** ~0-1 playback amplitude, updated continuously while speaking. */
  output: number
}

interface UseVoiceSessionArgs {
  sessionId: string
  onTranscript?: (text: string) => void
  onReplyText?: (text: string) => void
  onErrorMessage?: (message: string) => void
}

export interface VoiceSession {
  status: VoiceStatus
  /** Mutated in place every frame — read from a r3f useFrame loop, don't
   * put this in React state or the orb will cause a re-render per sample. */
  levelsRef: React.RefObject<AudioLevels>
  startHold: () => Promise<void>
  stopHold: () => void
  supported: boolean
}

const PROCESSOR_BUFFER_SIZE = 4096

export function useVoiceSession({
  sessionId,
  onTranscript,
  onReplyText,
  onErrorMessage,
}: UseVoiceSessionArgs): VoiceSession {
  const [status, setStatus] = useState<VoiceStatus>('idle')
  const levelsRef = useRef<AudioLevels>({ input: 0, output: 0 })

  const socketRef = useRef<WebSocket | null>(null)
  const micContextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const holdingRef = useRef(false)
  const initializingMicRef = useRef<Promise<void> | null>(null)

  const playbackChunksRef = useRef<Int16Array[]>([])
  const playbackContextRef = useRef<AudioContext | null>(null)
  const playbackRafRef = useRef<number | null>(null)

  const callbacksRef = useRef({ onTranscript, onReplyText, onErrorMessage })
  callbacksRef.current = { onTranscript, onReplyText, onErrorMessage }

  const supported =
    typeof window !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.AudioContext !== 'undefined'

  const stopLevelLoop = useCallback(() => {
    if (playbackRafRef.current !== null) {
      cancelAnimationFrame(playbackRafRef.current)
      playbackRafRef.current = null
    }
    levelsRef.current.output = 0
  }, [])

  const playQueuedAudio = useCallback(async () => {
    const chunks = playbackChunksRef.current
    playbackChunksRef.current = []
    if (chunks.length === 0) {
      setStatus('ready')
      return
    }

    const pcm = concatInt16(chunks)
    const floatData = float32FromInt16(pcm)

    if (!playbackContextRef.current) {
      playbackContextRef.current = new AudioContext()
    }
    const ctx = playbackContextRef.current
    if (ctx.state === 'suspended') await ctx.resume()

    const buffer = ctx.createBuffer(1, floatData.length, TARGET_SAMPLE_RATE)
    // floatData is always ArrayBuffer-backed (freshly constructed in
    // float32FromInt16); TS 6's stricter TypedArray generics just can't
    // prove that from the inferred ArrayBufferLike return type.
    buffer.copyToChannel(floatData as Float32Array<ArrayBuffer>, 0)

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    const timeDomain = new Float32Array(analyser.fftSize)

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(analyser)
    analyser.connect(ctx.destination)

    setStatus('speaking')

    const tick = () => {
      analyser.getFloatTimeDomainData(timeDomain)
      levelsRef.current.output = rms(timeDomain)
      playbackRafRef.current = requestAnimationFrame(tick)
    }
    tick()

    source.onended = () => {
      stopLevelLoop()
      setStatus((current) => (current === 'speaking' ? 'ready' : current))
    }
    source.start()
  }, [stopLevelLoop])

  const handleServerMessage = useCallback(
    (raw: string) => {
      let msg: { type: string; text?: string; audio?: string; message?: string }
      try {
        msg = JSON.parse(raw)
      } catch {
        return
      }

      switch (msg.type) {
        case 'ready':
          setStatus('ready')
          break
        case 'transcript':
          if (msg.text) callbacksRef.current.onTranscript?.(msg.text)
          setStatus('thinking')
          break
        case 'reply_text':
          if (msg.text) callbacksRef.current.onReplyText?.(msg.text)
          break
        case 'audio':
          if (msg.audio) playbackChunksRef.current.push(int16FromBase64(msg.audio))
          break
        case 'audio_done':
          void playQueuedAudio()
          break
        case 'error':
          callbacksRef.current.onErrorMessage?.(msg.message ?? 'Voice session error.')
          setStatus('error')
          break
        default:
          break
      }
    },
    [playQueuedAudio],
  )

  const ensureSocket = useCallback((): Promise<WebSocket> => {
    const existing = socketRef.current
    if (existing && existing.readyState === WebSocket.OPEN) return Promise.resolve(existing)

    setStatus('connecting')
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(`${WS_BASE_URL}/ws/voice?session_id=${encodeURIComponent(sessionId)}`)
      socketRef.current = socket

      socket.onopen = () => resolve(socket)
      socket.onmessage = (event) => handleServerMessage(event.data)
      socket.onerror = () => reject(new Error('Could not connect to the voice service.'))
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null
      }
    })
  }, [sessionId, handleServerMessage])

  const ensureMic = useCallback((): Promise<void> => {
    if (processorRef.current) return Promise.resolve()
    if (initializingMicRef.current) return initializingMicRef.current

    const setup = (async () => {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const ctx = new AudioContext()
      micContextRef.current = ctx
      if (ctx.state === 'suspended') await ctx.resume()

      const source = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(PROCESSOR_BUFFER_SIZE, 1, 1)

      processor.onaudioprocess = (event) => {
        if (!holdingRef.current) return
        const input = event.inputBuffer.getChannelData(0)
        levelsRef.current.input = rms(input)

        const socket = socketRef.current
        if (socket && socket.readyState === WebSocket.OPEN) {
          const audio = encodeMicChunk(input, ctx.sampleRate)
          socket.send(JSON.stringify({ type: 'audio', audio }))
        }
      }

      // Chrome requires the graph to reach a destination for
      // onaudioprocess to fire; route through a silent gain node so we
      // don't feed the mic back into the speakers.
      const silentGain = ctx.createGain()
      silentGain.gain.value = 0
      source.connect(processor)
      processor.connect(silentGain)
      silentGain.connect(ctx.destination)

      processorRef.current = processor
    })()

    initializingMicRef.current = setup
    return setup
  }, [])

  // Tracks "the user still wants to be holding" independent of whether the
  // mic/socket setup has finished — startHold's setup await can easily take
  // longer than a quick tap-and-release, and without this a release that
  // lands mid-setup gets silently dropped (holdingRef is still false, so
  // stopHold's guard no-ops) leaving the UI stuck in "Listening…" forever
  // once setup finally completes and flips it on.
  const desiredHoldRef = useRef(false)

  const startHold = useCallback(async () => {
    desiredHoldRef.current = true
    try {
      await Promise.all([ensureSocket(), ensureMic()])
      if (!desiredHoldRef.current) {
        // Released before setup finished — nothing was recorded, so just
        // settle back to ready instead of entering the listening state.
        setStatus('ready')
        return
      }
      holdingRef.current = true
      levelsRef.current.input = 0
      setStatus('listening')
    } catch (err) {
      desiredHoldRef.current = false
      callbacksRef.current.onErrorMessage?.(err instanceof Error ? err.message : 'Microphone access failed.')
      setStatus('error')
    }
  }, [ensureSocket, ensureMic])

  const stopHold = useCallback(() => {
    desiredHoldRef.current = false
    if (!holdingRef.current) return
    holdingRef.current = false
    levelsRef.current.input = 0
    const socket = socketRef.current
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'commit' }))
    }
    setStatus('thinking')
  }, [])

  useEffect(() => {
    return () => {
      holdingRef.current = false
      stopLevelLoop()
      processorRef.current?.disconnect()
      streamRef.current?.getTracks().forEach((track) => track.stop())
      micContextRef.current?.close().catch(() => {})
      playbackContextRef.current?.close().catch(() => {})
      socketRef.current?.close()
    }
  }, [stopLevelLoop])

  return { status, levelsRef, startHold, stopHold, supported }
}
