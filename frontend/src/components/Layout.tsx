import { lazy, Suspense, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { ThemeToggle } from './ThemeToggle'
import { resetDemo } from '../lib/api'

// three.js + react-three-fiber + drei are the single biggest chunk in the
// bundle; lazy-load the purely-decorative background so it doesn't delay
// first paint of the actual chat/admin UI.
const AmbientBackground = lazy(() =>
  import('./AmbientBackground').then((m) => ({ default: m.AmbientBackground })),
)

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-full px-3 py-1.5 text-sm font-medium transition ${
    isActive
      ? 'bg-violet-600 text-white'
      : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
  }`

export function Layout({ children, onReset }: { children: ReactNode; onReset: () => void }) {
  const [resetting, setResetting] = useState(false)

  async function handleReset() {
    if (resetting) return
    setResetting(true)
    try {
      await resetDemo()
      onReset()
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="relative min-h-dvh">
      <Suspense fallback={null}>
        <AmbientBackground />
      </Suspense>

      <header className="sticky top-0 z-10 border-b border-zinc-200/70 bg-white/70 backdrop-blur-md dark:border-zinc-800/70 dark:bg-zinc-950/70">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-cyan-400 text-sm font-bold text-white">
              F
            </span>
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">FoundersMax Refunds</span>
          </div>

          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navLinkClass}>
              Chat
            </NavLink>
            <NavLink to="/admin" className={navLinkClass}>
              Admin
            </NavLink>
          </nav>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleReset()}
              disabled={resetting}
              title="Clear all sessions, logs, and mock CRM mutations"
              className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 transition hover:border-zinc-300 hover:text-zinc-900 disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-400 dark:hover:border-zinc-700 dark:hover:text-zinc-100"
            >
              {resetting ? 'Resetting…' : 'Reset demo'}
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main>{children}</main>
    </div>
  )
}
