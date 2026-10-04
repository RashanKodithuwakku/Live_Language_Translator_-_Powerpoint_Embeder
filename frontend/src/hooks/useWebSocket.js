/**
 * WebSocket to /ws/translate?lang=&profile=
 * Auto-reconnects forever unless operator Stop.
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws/translate'
const MAX_RECONNECT_DELAY_MS = 5000
const STOP_GRACE_MS = 6000

export function useWebSocket(onMessage) {
  const wsRef = useRef(null)
  const [connectionStatus, setConnectionStatus] = useState('idle')

  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage
  const attemptRef = useRef(0)
  const timerRef = useRef(null)
  const shouldConnectRef = useRef(false)
  const languageRef = useRef('')
  const profileRef = useRef('eco')

  const open = useCallback(() => {
    clearTimeout(timerRef.current)
    const params = new URLSearchParams()
    if (languageRef.current) params.set('lang', languageRef.current)
    if (profileRef.current) params.set('profile', profileRef.current)
    const qs = params.toString()
    const ws = new WebSocket(qs ? `${WS_URL}?${qs}` : WS_URL)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      attemptRef.current = 0
      setConnectionStatus('connected')
    }

    ws.onmessage = (event) => {
      let msg
      try {
        msg = JSON.parse(event.data)
      } catch {
        console.warn('[WS] Ignoring non-JSON message')
        return
      }
      if (ws.stopping && wsRef.current && wsRef.current !== ws) {
        ws.close(1000, 'superseded')
        return
      }
      onMessageRef.current?.(msg)
      if (ws.stopping && msg.type === 'status' && msg.message?.startsWith('Stopped')) {
        ws.close(1000, 'operator-stop')
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

  const connect = useCallback((language = '', profile = 'eco') => {
    shouldConnectRef.current = true
    languageRef.current = language
    profileRef.current = profile
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
      if (ws.readyState === WebSocket.OPEN) {
        // Keep the socket open until the backend has delivered the
        // sentence that was in progress when Stop was pressed.
        ws.stopping = true
        ws.send('STOP')
        setTimeout(() => ws.close(1000, 'operator-stop'), STOP_GRACE_MS)
      } else {
        ws.close(1000, 'operator-stop')
      }
    }
    setConnectionStatus('idle')
  }, [])

  const sendAudio = useCallback((buffer) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buffer)
  }, [])

  const sendText = useCallback((text) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(text)
  }, [])

  // Live speaker switch; also used by any later auto-reconnect.
  const setLanguage = useCallback((language) => {
    languageRef.current = language
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(`LANG|${language}`)
  }, [])

  useEffect(() => () => {
    shouldConnectRef.current = false
    clearTimeout(timerRef.current)
    wsRef.current?.close()
  }, [])

  return { connect, disconnect, sendAudio, sendText, setLanguage, connectionStatus }
}
