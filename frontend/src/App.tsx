import { useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ChatView } from './components/ChatView'
import { AdminDashboard } from './components/AdminDashboard'

function newSessionId(): string {
  return crypto.randomUUID()
}

function App() {
  const [sessionId, setSessionId] = useState(newSessionId)

  return (
    <Layout onReset={() => setSessionId(newSessionId())}>
      <Routes>
        <Route path="/" element={<ChatView key={sessionId} sessionId={sessionId} />} />
        <Route path="/admin" element={<AdminDashboard />} />
      </Routes>
    </Layout>
  )
}

export default App
