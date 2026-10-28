/**
 * App shell: 16:9 slides (memoized) + operator column + 3-line subtitles.
 * Finals replace all three lines (Sinhala, Tamil, English) after the backend cleans them.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'

import PowerPointViewer from './components/PowerPointViewer'
import SubtitlePanel from './components/SubtitlePanel'
import TranslationControls from './components/TranslationControls'
import DeviceSelector from './components/DeviceSelector'

import { useWebSocket } from './hooks/useWebSocket'
import { useAudioStream } from './hooks/useAudioStream'
import { useDeviceEnumerator } from './hooks/useDeviceEnumerator'
import { useBackendHealth } from './hooks/useBackendHealth'

const EMPTY_SUBTITLES = { sinhala: '', tamil: '', original: '', seq: 0, interim: false }
const NOTICE_MS = 8000
// Silence/idle hints are normal between speakers; don't pop them up.
const QUIET_HINT = /no sound|no speech|silent|idle|resumed|noise floor/i
const VIEWS = [
  { id: 'both', label: 'Both', title: 'Show slides and translation' },
  { id: 'slides', label: 'Slides', title: 'Slides only (full screen)' },
  { id: 'captions', label: 'Translation', title: 'Translation only (full screen)' },
]
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

function useStoredState(key, initial) {
  const [value, setValue] = useState(() => {
    const stored = localStorage.getItem(key)
    return stored === null ? initial : JSON.parse(stored)
  })
  useEffect(() => localStorage.setItem(key, JSON.stringify(value)), [key, value])
  return [value, setValue]
}

export default function App() {
  const [subtitles, setSubtitles] = useState(EMPTY_SUBTITLES)
  const [notice, setNotice] = useState(null)
  const [active, setActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [mediaAudible, setMediaAudible] = useState(false)
  const [usage, setUsage] = useState(null)
  const [latency, setLatency] = useState(null)
  const [showLatency, setShowLatency] = useStoredState('liveTranslator.showLatency', false)
  const [pauseDuringMedia, setPauseDuringMedia] = useStoredState('liveTranslator.pauseDuringMedia', true)
  const [mediaSinkId, setMediaSinkId] = useStoredState('liveTranslator.mediaSinkId', '')
  const [speakerLanguage, setSpeakerLanguage] = useStoredState('liveTranslator.speakerLanguage', 'si-LK')
  const [profile, setProfile] = useStoredState('liveTranslator.profile', 'eco')
  const [view, setView] = useState('both')
  const [settingsOpen, setSettingsOpen] = useStoredState('liveTranslator.settingsOpen', true)
  const seqRef = useRef(0)
  const noticeTimer = useRef(null)
  const paintRef = useRef(0)
  const pendingSubs = useRef(EMPTY_SUBTITLES)

  const showNotice = useCallback((message) => {
    clearTimeout(noticeTimer.current)
    setNotice(message)
    noticeTimer.current = setTimeout(() => setNotice(null), NOTICE_MS)
  }, [])

  const paintSubtitles = useCallback((updater) => {
    const base = pendingSubs.current
    const next = typeof updater === 'function' ? updater(base) : updater
    pendingSubs.current = next
    if (paintRef.current) return
    paintRef.current = requestAnimationFrame(() => {
      paintRef.current = 0
      setSubtitles(pendingSubs.current)
    })
  }, [])

  const handleMessage = useCallback((msg) => {
    if (msg.type === 'translation') {
      if (msg.latency) setLatency(msg.latency)
      const english = msg.english || ''
      if (msg.isFinal) {
        seqRef.current += 1
        paintSubtitles({
          sinhala: msg.sinhala || '',
          tamil: msg.tamil || '',
          original: english || msg.original || '',
          seq: seqRef.current,
          interim: false,
        })
      } else {
        paintSubtitles((base) => {
          const next = msg.original || ''
          // Within one sentence, don't let a revised interim shrink the line.
          const shrinking = base.interim && next.length < base.original.length && base.original.startsWith(next)
          const original = shrinking ? base.original : next || base.original
          return {
            sinhala: msg.sinhala ? msg.sinhala : base.sinhala,
            tamil: msg.tamil ? msg.tamil : base.tamil,
            original: english || original,
            seq: base.seq,
            interim: true,
          }
        })
      }
      return
    }
    if (msg.type === 'usage') setUsage(msg.usage)
    else if (msg.type === 'error' && !QUIET_HINT.test(msg.message || '')) showNotice(msg.message)
    else if (msg.type === 'status' && /budget|cache|override/i.test(msg.message || '')) {
      showNotice(msg.message)
    }
  }, [paintSubtitles, showNotice])

  const { connect, disconnect, sendAudio, sendText, setLanguage, connectionStatus } = useWebSocket(handleMessage)

  const handleClear = useCallback(() => {
    pendingSubs.current = EMPTY_SUBTITLES
    setSubtitles(EMPTY_SUBTITLES)
    // The backend re-sends its last translations with each live preview.
    sendText('CLEAR')
  }, [sendText])

  const handleSpeakerLanguageChange = useCallback((code) => {
    setSpeakerLanguage(code)
    setLanguage(code)
  }, [setSpeakerLanguage, setLanguage])
  const audio = useAudioStream(sendAudio)
  const devices = useDeviceEnumerator()
  const backend = useBackendHealth()

  const gated = pauseDuringMedia && mediaAudible
  const { setGated } = audio
  useEffect(() => setGated(gated), [gated, setGated])

  useEffect(() => {
    fetch(`${API}/api/usage`)
      .then((r) => r.json())
      .then(setUsage)
      .catch(() => {})
  }, [])

  const handleStart = useCallback(async () => {
    setBusy(true)
    setNotice(null)
    setSubtitles(EMPTY_SUBTITLES)
    pendingSubs.current = EMPTY_SUBTITLES
    connect(speakerLanguage, profile)
    const device = devices.inputs.find((d) => d.deviceId === devices.selectedDeviceId)
    const ok = await audio.startStreaming(devices.selectedDeviceId, {
      mode: device?.kind === 'mixer' ? 'mixer' : 'mic',
      channel: 'auto',
    })
    if (ok) setActive(true)
    else disconnect()
    setBusy(false)
  }, [connect, disconnect, audio, devices.inputs, devices.selectedDeviceId, speakerLanguage, profile])

  const handleStop = useCallback(() => {
    setActive(false)
    audio.stopStreaming()
    disconnect()
  }, [audio, disconnect])

  let status = 'idle'
  if (busy) status = 'starting'
  else if (active && !audio.isStreaming) status = 'inputLost'
  else if (active && connectionStatus === 'reconnecting') status = 'reconnecting'
  else if (active && connectionStatus === 'connecting') status = 'connecting'
  else if (active && gated) status = 'paused'
  else if (active) status = 'live'

  const operatorMessage = audio.error || notice
  const cacheMode = usage?.mode === 'cache'

  return (
    <div className="relative flex h-full flex-col gap-3 bg-base p-2 sm:p-3">
      <div
        className="group absolute left-1/2 top-1 z-30 flex -translate-x-1/2 gap-0.5 rounded-full bg-surface-2/80 p-0.5 opacity-40 shadow-lg ring-1 ring-border transition-opacity hover:opacity-100 focus-within:opacity-100"
        role="group"
        aria-label="Layout"
      >
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => setView(v.id)}
            title={v.title}
            aria-pressed={view === v.id}
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold transition ${
              view === v.id ? 'bg-primary text-slate-950' : 'text-slate-300 hover:bg-surface-3'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Both panels stay mounted so the deck and the live session survive view changes. */}
      <section
        className={`panel min-h-0 flex-1 p-2 sm:p-3 ${view === 'captions' ? 'hidden' : ''}`}
        aria-label="Presentation"
      >
        <PowerPointViewer mediaSinkId={mediaSinkId} onAudibleMediaChange={setMediaAudible} />
      </section>

      <section
        className={`panel relative flex flex-col md:flex-row ${
          view === 'slides'
            ? 'hidden'
            : view === 'captions'
              ? 'min-h-0 flex-1'
              : 'shrink-0 md:h-[clamp(220px,30vh,340px)]'
        }`}
        aria-label="Live translation"
      >
        <aside className={`flex shrink-0 flex-row gap-4 overflow-y-auto border-b border-white/10 p-3 transition-[width] duration-300 ease-out md:flex-col md:gap-3 md:border-b-0 md:border-r ${settingsOpen ? 'md:w-56' : 'md:w-40'}`}>
          <div className="min-w-0 flex-1 md:flex-none">
            <TranslationControls
              status={status}
              backend={backend}
              level={audio.level}
              active={active}
              busy={busy}
              onStart={handleStart}
              onStop={handleStop}
              profile={profile}
              cacheMode={cacheMode}
            />
            <button
              type="button"
              className="mt-1 text-[9px] text-slate-600 hover:text-slate-400"
              onClick={() => setShowLatency((v) => !v)}
            >
              {showLatency ? 'Hide latency' : 'Latency'}
            </button>
            {showLatency && latency && (
              <pre className="mt-1 max-h-20 overflow-auto text-[8px] leading-tight text-slate-500">
                {JSON.stringify(latency.last || latency, null, 0)}
              </pre>
            )}
          </div>
          <div className="min-w-0 flex-1 md:flex-none">
            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              aria-expanded={settingsOpen}
              className="flex w-full items-center justify-between rounded-lg px-1 py-1 text-[11px] font-medium text-zinc-400 transition hover:bg-surface-3 hover:text-zinc-100"
            >
              <span>{settingsOpen ? 'Hide settings' : 'Show settings'}</span>
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                className={`transition-transform duration-300 ${settingsOpen ? 'rotate-180' : ''}`}
                aria-hidden="true"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            <div
              className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
                settingsOpen ? 'grid-rows-[1fr] opacity-100' : 'pointer-events-none grid-rows-[0fr] opacity-0'
              }`}
            >
              <div className="min-h-0 overflow-hidden">
                <div className="pt-2">
                  <DeviceSelector
                    inputs={devices.inputs}
                    outputs={devices.outputs}
                    selectedDeviceId={devices.selectedDeviceId}
                    onSelect={devices.setSelectedDeviceId}
                    locked={active || busy}
                    permissionError={devices.permissionError}
                    enumerating={devices.enumerating}
                    onRefresh={devices.refresh}
                    speakerLanguage={speakerLanguage}
                    onSpeakerLanguageChange={handleSpeakerLanguageChange}
                    profile={profile}
                    onProfileChange={setProfile}
                    mediaSinkId={mediaSinkId}
                    onMediaSinkChange={setMediaSinkId}
                    pauseDuringMedia={pauseDuringMedia}
                    onPauseDuringMediaChange={setPauseDuringMedia}
                  />
                </div>
              </div>
            </div>
          </div>
        </aside>

        <div className={`relative h-52 min-w-0 flex-1 px-4 py-2 sm:h-60 md:h-auto md:px-6 md:py-3 ${subtitles.interim ? 'opacity-90' : ''}`}>
          <SubtitlePanel subtitles={subtitles} large={view === 'captions'} />
          <button
            type="button"
            onClick={handleClear}
            className="absolute bottom-2 right-3 z-10 flex items-center gap-1 rounded-md bg-surface-2/90 px-2.5 py-1 text-xs font-semibold text-slate-300 ring-1 ring-border hover:bg-red-900/80 hover:text-white hover:ring-red-700 active:scale-95"
            title="Clear all subtitle lines now"
            aria-label="Clear subtitles"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            Clear
          </button>
        </div>

        {operatorMessage && (
          <div
            role="alert"
            className="absolute right-3 top-2 z-10 flex max-w-md items-start gap-2 rounded-md bg-red-950/90 px-3 py-1.5 text-xs text-red-200 ring-1 ring-red-800/60"
          >
            <span className="leading-snug">{operatorMessage}</span>
            {notice && !audio.error && (
              <button type="button" onClick={() => setNotice(null)} className="text-red-400 hover:text-white" aria-label="Dismiss">
                ✕
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
