export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  channel: 'text' | 'voice'
}

export type LogEventType =
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'retry'
  | 'error'
  | 'decision'
  | 'message'

export interface LogEvent {
  ts: string
  session_id: string
  type: LogEventType
  payload: Record<string, unknown>
  seq: number
}

export type VoiceStatus = 'idle' | 'connecting' | 'ready' | 'listening' | 'thinking' | 'speaking' | 'error'
