import { useEffect, useRef, useState } from 'react'
import { sendChatMessage } from '../lib/api'
import { VoiceControl } from './VoiceControl'
import type { ChatMessage } from '../lib/types'

function newId(): string {
  return crypto.randomUUID()
}

export function ChatView({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: newId(),
      role: 'assistant',
      content: "Hi! I'm the FoundersMax support agent. Tell me your email and order, and I'll help with your refund.",
      channel: 'text',
    },
  ])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  function appendMessage(message: Omit<ChatMessage, 'id'>) {
    setMessages((prev) => [...prev, { ...message, id: newId() }])
  }

  async function handleSend() {
    const text = draft.trim()
    if (!text || sending) return
    setDraft('')
    appendMessage({ role: 'user', content: text, channel: 'text' })
    setSending(true)
    try {
      const res = await sendChatMessage(sessionId, text)
      appendMessage({ role: 'assistant', content: res.reply, channel: 'text' })
    } catch (err) {
      appendMessage({
        role: 'assistant',
        content: err instanceof Error ? `⚠️ ${err.message}` : '⚠️ Something went wrong. Please try again.',
        channel: 'text',
      })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-4rem)] w-full max-w-2xl flex-col px-4 py-6">
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-t-2xl border border-b-0 border-zinc-200 bg-white/70 p-4 backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-900/60"
      >
        {messages.map((message) => (
          <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                message.role === 'user'
                  ? 'bg-violet-600 text-white'
                  : 'bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-100'
              }`}
            >
              {message.channel === 'voice' && (
                <span className="mr-1 align-middle text-xs opacity-70" title="via voice">
                  🎙️
                </span>
              )}
              {message.content}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1 rounded-2xl bg-zinc-100 px-4 py-3 dark:bg-zinc-800">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400" />
            </div>
          </div>
        )}
      </div>

      <div className="rounded-b-2xl border border-zinc-200 bg-white/70 px-4 pb-3 backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-900/60">
        <VoiceControl
          sessionId={sessionId}
          onTranscript={(text) => appendMessage({ role: 'user', content: text, channel: 'voice' })}
          onReplyText={(text) => appendMessage({ role: 'assistant', content: text.trim(), channel: 'voice' })}
        />

        <form
          onSubmit={(e) => {
            e.preventDefault()
            void handleSend()
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Type your message…"
            className="flex-1 rounded-full border border-zinc-200 bg-white px-4 py-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 focus:border-violet-400 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-600"
          />
          <button
            type="submit"
            disabled={sending || !draft.trim()}
            className="rounded-full bg-violet-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
