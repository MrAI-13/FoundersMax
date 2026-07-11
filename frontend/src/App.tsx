import { useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ChatView } from './components/ChatView'
import { AdminDashboard } from './components/AdminDashboard'
import type { ChatMessage } from './lib/types'

function newSessionId(): string {
  return crypto.randomUUID()
}

function newId(): string {
  return crypto.randomUUID()
}

function initialMessages(): ChatMessage[] {
  return [
    {
      id: newId(),
      role: 'assistant',
      content: "Hi! I'm the FoundersMax support agent. How can I help you today?",
      channel: 'text',
    },
  ]
}

function App() {
  const [sessionId, setSessionId] = useState(newSessionId)
  // Lifted out of ChatView so switching to /admin and back doesn't unmount
  // the chat and lose history (or the in-flight "sending" indicator) — only
  // the Route's element unmounts, App and this state stay mounted the whole
  // time.
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages)
  const [sending, setSending] = useState(false)

  function handleReset() {
    setSessionId(newSessionId())
    setMessages(initialMessages())
    setSending(false)
  }

  return (
    <Layout onReset={handleReset}>
      <Routes>
        <Route
          path="/"
          element={
            <ChatView
              sessionId={sessionId}
              messages={messages}
              onMessagesChange={setMessages}
              sending={sending}
              onSendingChange={setSending}
            />
          }
        />
        <Route path="/admin" element={<AdminDashboard />} />
      </Routes>
    </Layout>
  )
}

export default App
