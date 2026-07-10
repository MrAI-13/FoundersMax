const rawBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const API_BASE_URL = rawBase.replace(/\/$/, '')
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws')

export const SESSION_STORAGE_KEY = 'foundersmax-session-id'
export const THEME_STORAGE_KEY = 'foundersmax-theme'
