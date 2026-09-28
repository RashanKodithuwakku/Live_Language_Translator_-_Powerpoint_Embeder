import { useEffect, useState } from 'react'

export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

/** 'checking' | 'ok' | 'nokey' (running, but Google key file missing) | 'offline' */
export function useBackendHealth(intervalMs = 10_000) {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    let cancelled = false
    const check = async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) })
        const body = res.ok ? await res.json() : null
        if (!cancelled) setStatus(!body ? 'offline' : body.credentials_found ? 'ok' : 'nokey')
      } catch {
        if (!cancelled) setStatus('offline')
      }
    }
    check()
    const id = setInterval(check, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [intervalMs])

  return status
}
