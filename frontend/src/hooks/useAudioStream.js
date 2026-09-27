/**
 * useAudioStream.js
 * ─────────────────
 * Captures audio from the selected input device via getUserMedia,
 * processes it through a ScriptProcessorNode (AudioWorklet-compatible
 * fallback used for broad browser support in Chromium-based browsers
 * that ship with Electron or are run at events on a fixed browser version),
 * and streams raw LINEAR16 PCM chunks to the backend via a provided
 * sendAudio() callback.
 *
 * Audio parameters (must match backend audio_processor.py constants):
 *   Sample rate:   16 000 Hz
 *   Channels:      1 (mono)
 *   Bit depth:     16-bit signed integer (int16 / LINEAR16)
 *   Chunk size:    4 096 samples ≈ 256 ms per chunk
 *
 * Why ScriptProcessorNode instead of AudioWorklet?
 *   ScriptProcessorNode is deprecated but still fully functional in all
 *   Chromium-based browsers (Chrome, Edge, Electron). AudioWorklet requires
 *   HTTPS or localhost AND a separate worklet JS file registered via
 *   AudioContext.audioWorklet.addModule(). For a localhost event tool with
 *   no build complexity requirements, ScriptProcessorNode is the pragmatic
 *   choice. If the project is ever migrated to HTTPS, replace with an
 *   AudioWorklet module.
 *
 * USB device auto-selection (see also: DeviceSelector.jsx):
 *   Pass `deviceId` from the DeviceSelector component. The hook pins
 *   getUserMedia to that exact deviceId so the USB sound card is used
 *   instead of the laptop's built-in mic.
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const SAMPLE_RATE = 16_000        // Hz — must match backend
const BUFFER_SIZE = 4_096         // samples per chunk (~256 ms)
const CHANNELS = 1                // mono

/**
 * Converts a Float32Array [-1, 1] to Int16Array (LINEAR16 PCM).
 * This matches what Google STT expects as LINEAR16 encoding.
 */
function float32ToInt16(float32Array) {
  const int16Array = new Int16Array(float32Array.length)
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]))
    int16Array[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
  }
  return int16Array
}

export function useAudioStream(sendAudio) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [audioLevel, setAudioLevel] = useState(0) // 0–100 for VU meter

  const audioContextRef = useRef(null)
  const streamRef = useRef(null)
  const processorRef = useRef(null)
  const sourceRef = useRef(null)
  const analyserRef = useRef(null)
  const animFrameRef = useRef(null)

  // ── VU meter animation ──────────────────────────────────────────────────
  const updateAudioLevel = useCallback(() => {
    if (!analyserRef.current) return
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteTimeDomainData(dataArray)

    // RMS amplitude
    let sum = 0
    for (let i = 0; i < dataArray.length; i++) {
      const val = (dataArray[i] - 128) / 128
      sum += val * val
    }
    const rms = Math.sqrt(sum / dataArray.length)
    setAudioLevel(Math.min(100, Math.round(rms * 300)))

    animFrameRef.current = requestAnimationFrame(updateAudioLevel)
  }, [])

  // ── Start capturing ──────────────────────────────────────────────────────
  const startStreaming = useCallback(async (deviceId) => {
    try {
      setError(null)

      // Build getUserMedia constraints, pinned to the chosen deviceId
      const constraints = {
        audio: deviceId
          ? {
              deviceId: { exact: deviceId },
              channelCount: CHANNELS,
              sampleRate: SAMPLE_RATE,
              echoCancellation: false, // we handle noise in the backend
              noiseSuppression: false, // same — let noisereduce handle it
              autoGainControl: false,  // avoid gain fluctuation on speech
            }
          : {
              channelCount: CHANNELS,
              sampleRate: SAMPLE_RATE,
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false,
            },
        video: false,
      }

      const stream = await navigator.mediaDevices.getUserMedia(constraints)
      streamRef.current = stream

      // AudioContext must be created / resumed after a user gesture
      const audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE })
      audioContextRef.current = audioCtx

      const source = audioCtx.createMediaStreamSource(stream)
      sourceRef.current = source

      // Analyser for VU meter
      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 256
      analyserRef.current = analyser
      source.connect(analyser)

      // ScriptProcessor for PCM extraction
      // eslint-disable-next-line no-undef
      const processor = audioCtx.createScriptProcessor(BUFFER_SIZE, CHANNELS, CHANNELS)
      processorRef.current = processor

      processor.onaudioprocess = (event) => {
        const float32 = event.inputBuffer.getChannelData(0)
        const int16 = float32ToInt16(float32)
        // Send as raw ArrayBuffer (binary WebSocket frame)
        sendAudio(int16.buffer)
      }

      source.connect(processor)
      processor.connect(audioCtx.destination) // must be connected to stay active

      setIsStreaming(true)
      updateAudioLevel()

      console.log('[Audio] Streaming started, device:', deviceId || 'default')
    } catch (err) {
      console.error('[Audio] Failed to start streaming:', err)
      setError(err.message || 'Microphone access denied')
      setIsStreaming(false)
    }
  }, [sendAudio, updateAudioLevel])

  // ── Stop capturing ───────────────────────────────────────────────────────
  const stopStreaming = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
      animFrameRef.current = null
    }

    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current.onaudioprocess = null
      processorRef.current = null
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }

    if (analyserRef.current) {
      analyserRef.current.disconnect()
      analyserRef.current = null
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    setIsStreaming(false)
    setAudioLevel(0)
    console.log('[Audio] Streaming stopped')
  }, [])

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopStreaming()
    }
  }, [stopStreaming])

  return { isStreaming, startStreaming, stopStreaming, error, audioLevel }
}
