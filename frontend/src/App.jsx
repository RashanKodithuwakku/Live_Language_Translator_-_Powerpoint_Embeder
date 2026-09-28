/**
 * App shell: 16:9 slides (memoized) + operator column + 3-line subtitles.
 * Interim captions update the original line immediately; finals replace all three.
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
      if (msg.isFinal) {
        seqRef.current += 1
        paintSubtitles({
          sinhala: msg.sinhala || '',
          tamil: msg.tamil || '',
          original: msg.original || '',
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
            original,
            seq: base.seq,
            interim: true,
          }
        })
      }
      return
    }
    if (msg.type === 'usage') setUsage(msg.usage)
    else if (msg.type === 'error') showNotice(msg.message)
    else if (msg.type === 'status' && /budget|idle|noise|cache|resumed|override/i.test(msg.message || '')) {
      showNotice(msg.message)
    }
  }, [paintSubtitles, showNotice])

  const { connect, disconnect, sendAudio, setLanguage, connectionStatus } = useWebSocket(handleMessage)

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
      channel: 'sum',
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
    <div className="flex h-full flex-col gap-3 bg-base p-2 sm:p-3">
      <section className="panel min-h-0 flex-1 p-2 sm:p-3" aria-label="Presentation">
        <PowerPointViewer mediaSinkId={mediaSinkId} onAudibleMediaChange={setMediaAudible} />
      </section>

      <section
        className="panel relative flex shrink-0 flex-col md:h-[clamp(220px,30vh,340px)] md:flex-row"
        aria-label="Live translation"
      >
        <aside className="flex shrink-0 flex-row gap-4 overflow-y-auto border-b border-border/60 p-3 md:w-56 md:flex-col md:gap-3 md:border-b-0 md:border-r">
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
        </aside>

        <div className={`h-52 min-w-0 flex-1 px-4 py-2 sm:h-60 md:h-auto md:px-6 md:py-3 ${subtitles.interim ? 'opacity-90' : ''}`}>
          <SubtitlePanel subtitles={subtitles} />
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
