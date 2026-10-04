/**
 * Captures USB / mic audio as LINEAR16 16 kHz mono ~100 ms WebSocket frames.
 *
 * Modes (persisted by caller):
 *   mixer — DSP off, prefer 48 kHz device rate, worklet downsamples (production)
 *   mic   — browser EC/NS/AGC on (laptop testing)
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const TARGET_RATE = 16_000
const CHUNK_SAMPLES = 1_600
const WORKLET_URL = '/worklets/pcm-capture-processor.js'
const CLIP_HOLD_MS = 1_500

function describeGetUserMediaError(err) {
  switch (err?.name) {
    case 'NotAllowedError':
      return 'Microphone access is blocked. Allow Microphone in the address bar, then Start again.'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'Selected audio input not found. Check the USB sound card, then Refresh.'
    case 'NotReadableError':
      return 'Audio input is busy. Close Zoom/Teams/OBS and try again.'
    default:
      return err?.message || 'Could not open the audio input.'
  }
}

function constraintsFor(mode, deviceId, channelCount) {
  const base = {
    ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    channelCount: { ideal: channelCount },
  }
  if (mode === 'mic') {
    return {
      ...base,
      sampleRate: { ideal: 48000 },
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    }
  }
  // mixer / line — never let the browser "improve" a clean feed
  return {
    ...base,
    sampleRate: { ideal: 48000 },
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  }
}

export function useAudioStream(sendAudio) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [level, setLevel] = useState({ db: -90, clipping: false, snr: null })

  const graphRef = useRef(null)
  const wantStreamingRef = useRef(false)
  const deviceIdRef = useRef(null)
  const modeRef = useRef('mixer')
  const channelRef = useRef('auto')
  const gatedRef = useRef(false)
  const clipUntilRef = useRef(0)
  const sendAudioRef = useRef(sendAudio)
  const levelListeners = useRef(new Set())
  const lastLevelRef = useRef({ db: -90, clipping: false, snr: null })
  const rafRef = useRef(0)
  sendAudioRef.current = sendAudio

  const publishLevel = useCallback((next) => {
    lastLevelRef.current = next
    if (rafRef.current) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      const snap = lastLevelRef.current
      setLevel(snap)
      levelListeners.current.forEach((fn) => fn(snap))
    })
  }, [])

  const subscribeLevel = useCallback((fn) => {
    levelListeners.current.add(fn)
    fn(lastLevelRef.current)
    return () => levelListeners.current.delete(fn)
  }, [])

  const teardownGraph = useCallback(() => {
    const graph = graphRef.current
    graphRef.current = null
    if (!graph) return
    graph.node.port.onmessage = null
    graph.stream.getTracks().forEach((track) => {
      track.onended = null
      track.stop()
    })
    graph.context.close().catch(() => {})
  }, [])

  const openGraph = useCallback(async (deviceId) => {
    const mode = modeRef.current
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: constraintsFor(mode, deviceId, mode === 'mixer' ? 2 : 1),
      video: false,
    })

    // Prefer device native rate; worklet downsamples to 16 kHz.
    const track = stream.getAudioTracks()[0]
    const settings = track?.getSettings?.() || {}
    const nativeRate = settings.sampleRate || 48000
    const context = new AudioContext({
      sampleRate: nativeRate,
      latencyHint: 'interactive',
    })
    try {
      await context.audioWorklet.addModule(WORKLET_URL)
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop())
      context.close().catch(() => {})
      throw err
    }

    const source = context.createMediaStreamSource(stream)
    const node = new AudioWorkletNode(context, 'pcm-capture-processor', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: Math.min(2, source.channelCount || 2),
      channelCountMode: 'explicit',
      channelInterpretation: 'speakers',
      processorOptions: {
        chunkSamples: CHUNK_SAMPLES,
        targetRate: TARGET_RATE,
        channelMode: channelRef.current,
      },
    })
    const mute = context.createGain()
    mute.gain.value = 0
    source.connect(node).connect(mute).connect(context.destination)

    let noiseFloor = -60
    node.port.onmessage = ({ data }) => {
      if (data.channel) {
        console.info(`[Audio] Using ${data.channel} channel of the stereo input`)
        return
      }
      const payload = gatedRef.current ? new ArrayBuffer(data.pcm.byteLength) : data.pcm
      sendAudioRef.current(payload)

      const now = performance.now()
      if (data.peak >= 0.99) clipUntilRef.current = now + CLIP_HOLD_MS
      const db = data.rms > 0 ? Math.max(-90, 20 * Math.log10(data.rms)) : -90
      if (db < noiseFloor + 6) noiseFloor = noiseFloor * 0.95 + db * 0.05
      publishLevel({
        db,
        clipping: now < clipUntilRef.current,
        snr: db > -85 ? Math.round(db - noiseFloor) : null,
      })
    }

    track.onended = () => {
      if (!wantStreamingRef.current) return
      teardownGraph()
      setIsStreaming(false)
      publishLevel({ db: -90, clipping: false, snr: null })
      setError('Audio input disconnected — reconnect the USB card. Capture resumes automatically.')
    }

    if (context.state === 'suspended') await context.resume()
    graphRef.current = { stream, context, node }
  }, [teardownGraph, publishLevel])

  const startStreaming = useCallback(async (deviceId, { mode = 'mixer', channel = 'auto' } = {}) => {
    setError(null)
    wantStreamingRef.current = true
    deviceIdRef.current = deviceId
    modeRef.current = mode
    channelRef.current = channel
    teardownGraph()
    try {
      await openGraph(deviceId)
      setIsStreaming(true)
      return true
    } catch (err) {
      console.error('[Audio] Failed to start capture:', err)
      wantStreamingRef.current = false
      setError(describeGetUserMediaError(err))
      setIsStreaming(false)
      return false
    }
  }, [openGraph, teardownGraph])

  const stopStreaming = useCallback(() => {
    wantStreamingRef.current = false
    teardownGraph()
    setIsStreaming(false)
    publishLevel({ db: -90, clipping: false, snr: null })
  }, [teardownGraph, publishLevel])

  const setGated = useCallback((gated) => {
    gatedRef.current = gated
  }, [])

  useEffect(() => {
    const onDeviceChange = async () => {
      if (!wantStreamingRef.current || graphRef.current) return
      const devices = await navigator.mediaDevices.enumerateDevices()
      const back = devices.some((d) => d.kind === 'audioinput' && d.deviceId === deviceIdRef.current)
      if (!back) return
      try {
        await openGraph(deviceIdRef.current)
        setIsStreaming(true)
        setError(null)
      } catch (err) {
        setError(describeGetUserMediaError(err))
      }
    }
    navigator.mediaDevices.addEventListener('devicechange', onDeviceChange)
    return () => navigator.mediaDevices.removeEventListener('devicechange', onDeviceChange)
  }, [openGraph])

  useEffect(() => () => {
    wantStreamingRef.current = false
    teardownGraph()
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
  }, [teardownGraph])

  return {
    isStreaming,
    startStreaming,
    stopStreaming,
    setGated,
    error,
    level,
    subscribeLevel,
  }
}
