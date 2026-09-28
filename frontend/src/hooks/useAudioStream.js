/**
 * useAudioStream.js
 * ─────────────────
 * Captures the USB sound card (pinned by deviceId) and streams LINEAR16
 * PCM, 16 kHz mono, in 100 ms binary chunks via `sendAudio`.
 *
 * Signal path:
 *   getUserMedia(deviceId: exact) → MediaStreamSource → AudioWorklet
 *   (public/worklets/pcm-capture-processor.js) → port → sendAudio()
 *                                              └→ Gain(0) → destination
 * The zero-gain branch only keeps the worklet in the rendered graph; the
 * mixer feed is never played back out of the laptop (no feedback loop).
 *
 * All browser DSP (echo cancellation, noise suppression, AGC) is disabled:
 * the mixer already delivers a controlled line-level signal and AGC
 * pumping hurts recognition. Cleanup happens in the backend.
 *
 * Gate: while `gated` is true (a slide video/audio is audible), chunks of
 * digital silence are sent instead of the mic feed. The Google stream stays
 * alive (it errors after ~10 s without audio) but never transcribes the
 * video's soundtrack if it leaks back through the mixer.
 *
 * Recovery: if the USB device disappears mid-event (cable knocked out), the
 * track ends; we report it and automatically re-open the same device as
 * soon as it is plugged back in.
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const SAMPLE_RATE = 16_000
const CHUNK_SAMPLES = 1_600 // 100 ms — Google's recommended streaming frame
const WORKLET_URL = '/worklets/pcm-capture-processor.js'
const CLIP_HOLD_MS = 1_500

function describeGetUserMediaError(err) {
  switch (err?.name) {
    case 'NotAllowedError':
      return 'Microphone access is blocked. Click the lock icon in the address bar, allow Microphone, then press Start again.'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'The selected audio input was not found. Check the USB sound card is plugged in, then press Refresh.'
    case 'NotReadableError':
      return 'The audio input is busy or unavailable. Close other apps using it (Zoom, Teams, OBS) and try again.'
    default:
      return err?.message || 'Could not open the audio input.'
  }
}

export function useAudioStream(sendAudio) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [level, setLevel] = useState({ db: -90, clipping: false })

  const graphRef = useRef(null)
  const wantStreamingRef = useRef(false)
  const deviceIdRef = useRef(null)
  const gatedRef = useRef(false)
  const clipUntilRef = useRef(0)
  const sendAudioRef = useRef(sendAudio)
  sendAudioRef.current = sendAudio

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
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        channelCount: { ideal: 1 },
        sampleRate: { ideal: SAMPLE_RATE },
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    })

    const context = new AudioContext({ sampleRate: SAMPLE_RATE, latencyHint: 'interactive' })
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
      channelCount: 1,
      channelCountMode: 'explicit',
      channelInterpretation: 'speakers',
      processorOptions: { chunkSamples: CHUNK_SAMPLES },
    })
    const mute = context.createGain()
    mute.gain.value = 0
    source.connect(node).connect(mute).connect(context.destination)

    node.port.onmessage = ({ data }) => {
      const payload = gatedRef.current ? new ArrayBuffer(data.pcm.byteLength) : data.pcm
      sendAudioRef.current(payload)

      const now = performance.now()
      if (data.peak >= 0.99) clipUntilRef.current = now + CLIP_HOLD_MS
      setLevel({
        db: data.rms > 0 ? Math.max(-90, 20 * Math.log10(data.rms)) : -90,
        clipping: now < clipUntilRef.current,
      })
    }

    const [track] = stream.getAudioTracks()
    track.onended = () => {
      if (!wantStreamingRef.current) return
      teardownGraph()
      setIsStreaming(false)
      setLevel({ db: -90, clipping: false })
      setError('Audio input disconnected — reconnect the USB sound card. Capture will resume automatically.')
    }

    if (context.state === 'suspended') await context.resume()
    graphRef.current = { stream, context, node }
  }, [teardownGraph])

  const startStreaming = useCallback(async (deviceId) => {
    setError(null)
    wantStreamingRef.current = true
    deviceIdRef.current = deviceId
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
    setLevel({ db: -90, clipping: false })
  }, [teardownGraph])

  const setGated = useCallback((gated) => {
    gatedRef.current = gated
  }, [])

  // Auto-recover when the lost device is plugged back in.
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
  }, [teardownGraph])

  return { isStreaming, startStreaming, stopStreaming, setGated, error, level }
}
