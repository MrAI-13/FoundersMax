import { API_BASE_URL } from './config'

export interface ChatResponse {
  session_id: string
  reply: string
}

export async function sendChatMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `Chat request failed (${res.status})`)
  }
  return res.json()
}

export async function resetDemo(): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/reset`, { method: 'POST' })
  if (!res.ok) {
    throw new Error(`Reset failed (${res.status})`)
  }
}
