/**
 * App.jsx
 * ───────
 * Root component. Manages global session state and wires together:
 *   - useWebSocket  → backend connection
 *   - useAudioStream → mic capture
 *   - useDeviceEnumerator → device selection
 *
 * Layout (two sections, full viewport height):
 *   ┌────────────────────────────────────────┐
 *   │ StatusBar                              │
 *   ├────────────────────────────────────────┤
 *   │                                        │
 *   │  Section A: PowerPointViewer  (flex-1) │
 *   │  (enforces 16:9 internally)            │
 *   │                                        │
 *   ├────────────────────────────────────────┤
 *   │  Section B: Translation Controls +     │
 *   │             Subtitle Panel             │
 *   └────────────────────────────────────────┘
 *
 * Subtitle state management:
 *   Only isFinal messages update the displayed subtitles.
 *   Each update increments `animKey` so React treats every line as a new
 *   mount, triggering the slide-up animation — even for identical text.
 */

import React, { useState, useCallback, useRef } from 'react'

import StatusBar from './components/StatusBar'
import PowerPointViewer from './components/PowerPointViewer'
import SubtitlePanel from './components/SubtitlePanel'
import TranslationControls from './components/TranslationControls'
import DeviceSelector from './components/DeviceSelector'

import { useWebSocket } from './hooks/useWebSocket'
import { useAudioStream } from './hooks/useAudioStream'
import { useDeviceEnumerator } from './hooks/useDeviceEnumerator'

const EMPTY_SUBTITLES = { sinhala: '', tamil: '', original: '', animKey: 0 }

export default function App() {
  // ── Subtitle state ────────────────────────────────────────────────────
  const [subtitles, setSubtitles] = useState(EMPTY_SUBTITLES)
  const animKeyRef = useRef(0)

  // ── Error notification ────────────────────────────────────────────────
  const [errorMsg, setErrorMsg] = useState(null)

  // ── Message handler (called by useWebSocket on every backend message) ─
  const handleMessage = useCallback((msg) => {
    if (msg.type === 'translation' && msg.isFinal) {
      animKeyRef.current += 1
      setSubtitles({
        sinhala: msg.sinhala || '',
        tamil: msg.tamil || '',
        original: msg.original || '',
        animKey: animKeyRef.current,
      })
    } else if (msg.type === 'error') {
      setErrorMsg(msg.message)
      // Auto-dismiss after 6 s
      setTimeout(() => setErrorMsg(null), 6000)
    }
  }, [])

  // ── WebSocket ─────────────────────────────────────────────────────────
  const { connect, disconnect, sendAudio, sendCommand, isConnected, connectionStatus } =
    useWebSocket(handleMessage)

  // ── Audio stream ──────────────────────────────────────────────────────
  const { isStreaming, startStreaming, stopStreaming, error: audioError, audioLevel } =
    useAudioStream(sendAudio)

  // ── Device selection ──────────────────────────────────────────────────
  const {
    devices,
    selectedDeviceId,
    setSelectedDeviceId,
    permissionError,
    enumerating,
    refresh,
  } = useDeviceEnumerator()

  // ── Session control ───────────────────────────────────────────────────
  const handleStart = useCallback(async () => {
    setSubtitles(EMPTY_SUBTITLES)
    setErrorMsg(null)
    connect()
    await startStreaming(selectedDeviceId)
  }, [connect, startStreaming, selectedDeviceId])

  const handleStop = useCallback(() => {
    stopStreaming()
    sendCommand('STOP')
    disconnect()
  }, [stopStreaming, sendCommand, disconnect])

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-base">
      {/* ── Top status bar ───────────────────────────────────────────────── */}
      <StatusBar />

      {/* ── Error toast ──────────────────────────────────────────────────── */}
      {(errorMsg || audioError) && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-xl bg-red-900/90 border border-red-600/50 px-5 py-3 text-sm text-red-200 shadow-2xl backdrop-blur-md animate-fade-in">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="flex-shrink-0">
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{errorMsg || audioError}</span>
          <button onClick={() => setErrorMsg(null)} className="text-red-400 hover:text-white ml-2 font-bold">✕</button>
        </div>
      )}

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex flex-col flex-1 min-h-0 p-4 gap-4">

        {/* ── SECTION A: Slide Viewer ─────────────────────────────────────── */}
        <section
          className="flex-1 min-h-0 glass rounded-2xl p-3"
          aria-label="Presentation slide viewer"
        >
          <PowerPointViewer />
        </section>

        {/* ── SECTION B: Translation controls + subtitles ─────────────────── */}
        <section
          className="glass rounded-2xl px-5 py-4 flex-shrink-0"
          aria-label="Translation controls and live subtitles"
          style={{ minHeight: '220px', maxHeight: '320px' }}
        >
          <div className="flex gap-6 h-full">

            {/* Left column: device + controls */}
            <div className="flex flex-col gap-4 flex-shrink-0" style={{ width: '280px' }}>
              <DeviceSelector
                devices={devices}
                selectedDeviceId={selectedDeviceId}
                onSelect={setSelectedDeviceId}
                disabled={isStreaming}
                permissionError={permissionError}
                enumerating={enumerating}
                onRefresh={refresh}
              />
              <div className="h-px bg-border/60" />
              <TranslationControls
                isStreaming={isStreaming}
                connectionStatus={connectionStatus}
                audioLevel={audioLevel}
                onStart={handleStart}
                onStop={handleStop}
              />
            </div>

            {/* Vertical divider */}
            <div className="w-px bg-border/60 flex-shrink-0" />

            {/* Right column: subtitle lines */}
            <div className="flex-1 min-w-0 overflow-hidden">
              <SubtitlePanel
                subtitles={subtitles}
                isConnected={isConnected}
                isStreaming={isStreaming}
              />
            </div>

          </div>
        </section>

      </main>
    </div>
  )
}
