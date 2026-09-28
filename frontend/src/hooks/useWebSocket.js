/**
 * useWebSocket.js
 * ───────────────
 * Connection to the backend translation socket.
 *
 * Reconnection: an operator Stop closes the socket deliberately and never
 * reconnects. Any other close (backend restart, laptop sleep, network blip)
 * reconnects forever with exponential back-off capped at 5 s. The backend
 * starts a fresh Google streaming session on every new connection, so
 * captions resume without the operator pressing Start again. Audio chunks
 * produced while disconnected are dropped (live captions have no use for
 * stale audio).
 *
 * connectionStatus: 'idle' | 'connecting' | 'connected' | 'reconnecting'
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws/translate'
const MAX_RECONNECT_DELAY_MS = 5000

export function useWebSocket(onMessage) {
  const wsRef = useRef(null)
  const [connectionStatus, setConnectionStatus] = useState('idle')

  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage
  const attemptRef = useRef(0)
  const timerRef = useRef(null)
  const shouldConnectRef = useRef(false)
  const languageRef = useRef('')

  const open = useCallback(() => {
    clearTimeout(timerRef.current)
    const url = languageRef.current
      ? `${WS_URL}?lang=${encodeURIComponent(languageRef.current)}`
      : WS_URL
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      attemptRef.current = 0
      setConnectionStatus('connected')
    }

    ws.onmessage = (event) => {
      try {
        onMessageRef.current?.(JSON.parse(event.data))
      } catch {
        console.warn('[WS] Ignoring non-JSON message')
      }
    }

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      if (!shouldConnectRef.current) return
      const attempt = ++attemptRef.current
      const delay = Math.min(500 * 2 ** (attempt - 1), MAX_RECONNECT_DELAY_MS)
      setConnectionStatus('reconnecting')
      timerRef.current = setTimeout(open, delay)
    }
  }, [])

  /** language: speaker's main language (e.g. 'si-LK'); kept across reconnects. */
  const connect = useCallback((language = '') => {
    shouldConnectRef.current = true
    languageRef.current = language
    const ws = wsRef.current
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    attemptRef.current = 0
    setConnectionStatus('connecting')
    open()
  }, [open])

  const disconnect = useCallback(() => {
    shouldConnectRef.current = false
    clearTimeout(timerRef.current)
    const ws = wsRef.current
    wsRef.current = null
    if (ws) {
      if (ws.readyState === WebSocket.OPEN) ws.send('STOP')
      ws.close(1000, 'operator-stop')
    }
    setConnectionStatus('idle')
  }, [])

  const sendAudio = useCallback((buffer) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buffer)
  }, [])

  useEffect(() => () => {
    shouldConnectRef.current = false
    clearTimeout(timerRef.current)
    wsRef.current?.close()
  }, [])

  return { connect, disconnect, sendAudio, connectionStatus }
}
