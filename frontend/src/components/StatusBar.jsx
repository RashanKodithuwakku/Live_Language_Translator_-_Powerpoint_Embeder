/**
 * StatusBar.jsx
 * ─────────────
 * Top application status bar: backend health indicator, app branding,
 * and current event time.
 */

import React, { useEffect, useState } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

function useBackendHealth() {
  const [status, setStatus] = useState('checking') // checking | ok | error

  useEffect(() => {
    let cancelled = false

    async function check() {
      try {
        const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) })
        if (!cancelled) setStatus(res.ok ? 'ok' : 'error')
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    check()
    const interval = setInterval(check, 15_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return status
}

function Clock() {
  const [time, setTime] = useState('')

  useEffect(() => {
    const update = () => {
      setTime(new Date().toLocaleTimeString('en-GB', { hour12: false }))
    }
    update()
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [])

  return <span className="font-mono text-slate-400 text-sm">{time}</span>
}

export default function StatusBar() {
  const health = useBackendHealth()

  const healthConfig = {
    checking: { dot: 'bg-slate-500 animate-pulse', label: 'Checking backend…', color: 'text-slate-500' },
    ok:       { dot: 'bg-success',                 label: 'Backend online',    color: 'text-emerald-400' },
    error:    { dot: 'bg-red-500 animate-pulse',   label: 'Backend offline',   color: 'text-red-400' },
  }

  const cfg = healthConfig[health]

  return (
    <header className="flex items-center justify-between px-5 py-3 border-b border-border/50 bg-surface/60 backdrop-blur-sm flex-shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          {/* Waveform icon */}
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="text-primary">
            <path d="M2 12h2M4 12a8 8 0 0016 0M20 12h2M12 4v2M12 18v2" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            <path d="M6 12c0-3.314 2.686-6 6-6s6 2.686 6 6-2.686 6-6 6S6 15.314 6 12z" stroke="currentColor" strokeWidth="1.5"/>
            <circle cx="12" cy="12" r="2" fill="currentColor"/>
          </svg>
          <h1 className="text-base font-bold gradient-text">
            Live Translator
          </h1>
        </div>
        <div className="h-4 w-px bg-border" />
        <span className="text-xs text-slate-500 font-medium">
          Sinhala · Tamil · English
        </span>
      </div>

      {/* Right: health + clock */}
      <div className="flex items-center gap-4">
        <div className={`flex items-center gap-1.5 text-xs font-medium ${cfg.color}`}>
          <div className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
          {cfg.label}
        </div>
        <Clock />
      </div>
    </header>
  )
}
