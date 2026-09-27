/**
 * useWebSocket.js
 * ───────────────
 * Manages the persistent WebSocket connection to the backend translation
 * service. Exposes:
 *   - sendAudio(pcmBytes)   → sends a binary audio frame
 *   - sendCommand(text)     → sends a text control command ("STOP"/"START")
 *   - isConnected           → boolean connection state
 *   - lastMessage           → most recent parsed JSON message from backend
 *   - connectionStatus      → "idle" | "connecting" | "connected" | "error" | "disconnected"
 *
 * Reconnection strategy:
 *   The hook does NOT auto-reconnect after a deliberate operator Stop
 *   (i.e. after we close the socket ourselves). It DOES attempt to
 *   reconnect if the connection is dropped unexpectedly (network blip,
 *   backend restart), with an exponential back-off capped at 5 s.
 *
 * The WebSocket URL is configurable via import.meta.env.VITE_WS_URL
 * (default: ws://127.0.0.1:8000/ws/translate).
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws/translate'
const MAX_RECONNECT_DELAY_MS = 5000

export function useWebSocket(onMessage) {
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState('idle') // idle | connecting | connected | error | disconnected
  const [lastMessage, setLastMessage] = useState(null)

  // Reconnection state
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef(null)
  const intentionalCloseRef = useRef(false) // set true when WE close the socket

  // ── Internal helpers ────────────────────────────────────────────────────
  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    // Don't open a second connection if already open
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return

    intentionalCloseRef.current = false
    setConnectionStatus('connecting')

    const ws = new WebSocket(WS_URL)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected to backend')
      setIsConnected(true)
      setConnectionStatus('connected')
      reconnectAttemptRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        setLastMessage(parsed)
        if (onMessage) onMessage(parsed)
      } catch (err) {
        console.warn('[WS] Could not parse message:', event.data)
      }
    }

    ws.onerror = (err) => {
      console.error('[WS] Error:', err)
      setConnectionStatus('error')
    }

    ws.onclose = (event) => {
      console.log(`[WS] Closed (code=${event.code}, intentional=${intentionalCloseRef.current})`)
      setIsConnected(false)
      wsRef.current = null

      if (intentionalCloseRef.current) {
        setConnectionStatus('disconnected')
        return
      }

      // Unexpected close — attempt reconnect with exponential back-off
      setConnectionStatus('disconnected')
      const attempt = ++reconnectAttemptRef.current
      const delay = Math.min(500 * Math.pow(2, attempt - 1), MAX_RECONNECT_DELAY_MS)
      console.log(`[WS] Reconnecting in ${delay}ms (attempt ${attempt})`)

      reconnectTimerRef.current = setTimeout(() => {
        connect()
      }, delay)
    }
  }, [onMessage]) // eslint-disable-line react-hooks/exhaustive-deps

  const disconnect = useCallback(() => {
    clearReconnectTimer()
    intentionalCloseRef.current = true
    if (wsRef.current) {
      wsRef.current.close(1000, 'operator-stop')
      wsRef.current = null
    }
    setIsConnected(false)
    setConnectionStatus('idle')
  }, [clearReconnectTimer])

  // ── Public API ──────────────────────────────────────────────────────────
  const sendAudio = useCallback((pcmBytes) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(pcmBytes)
    }
  }, [])

  const sendCommand = useCallback((text) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(text)
    }
  }, [])

  // Clean up on unmount
  useEffect(() => {
    return () => {
      clearReconnectTimer()
      intentionalCloseRef.current = true
      wsRef.current?.close()
    }
  }, [clearReconnectTimer])

  return {
    connect,
    disconnect,
    sendAudio,
    sendCommand,
    isConnected,
    connectionStatus,
    lastMessage,
  }
}
