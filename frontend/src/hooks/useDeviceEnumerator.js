/**
 * useDeviceEnumerator.js
 * ──────────────────────
 * Lists audio inputs (for the mixer feed) and audio outputs (for slide
 * video sound), and auto-selects the best input: mixer / USB sound card,
 * then a Bluetooth or headset mic, then the built-in laptop mic.
 *
 * Each input gets a `kind` (mixer | headset | mic) from its label, which
 * also decides the capture mode (mixer = browser DSP off). Windows' virtual
 * "Default - …" / "Communications - …" aliases are hidden so capture stays
 * pinned to a real device even if the Windows default changes mid-event.
 *
 * Labels are only exposed after microphone permission is granted, so a
 * short permission probe runs first.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

const HEADSET_PATTERN = /bluetooth|hands-?free|headset|airpods|buds|\bbt\b/i
const MIXER_PATTERN =
  /\busb\b|line ?in|behringer|focusrite|scarlett|presonus|steinberg|roland|tascam|yamaha|audient|motu|mackie|m-audio|zoom|ugreen|sound ?blaster|creative|u-phoria|umc\d/i

// Higher rank wins auto-selection: mixer feed > headset/Bluetooth mic > built-in mic.
const RANK = { mixer: 3, headset: 2, mic: 1 }

const ALIAS_IDS = new Set(['default', 'communications'])

function classify(label) {
  if (HEADSET_PATTERN.test(label)) return 'headset'
  if (MIXER_PATTERN.test(label)) return 'mixer'
  return 'mic'
}

function cleanLabel(label) {
  return label.replace(/^(Default|Communications) - /, '').replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$/i, '')
}

function describePermissionError(err) {
  switch (err?.name) {
    case 'NotAllowedError':
      return 'Microphone access is blocked for this page. Click the lock icon in the address bar → allow Microphone → Retry.'
    case 'NotFoundError':
      return 'No audio input found. Plug in the USB sound card, then Retry.'
    case 'NotReadableError':
      return 'Audio input is busy (another app may be using it). Close it, then Retry.'
    default:
      return err?.message || 'Could not access audio devices.'
  }
}

function pickPreferred(inputs) {
  return inputs.reduce((best, d) => (!best || RANK[d.kind] > RANK[best.kind] ? d : best), null)
}

export function useDeviceEnumerator() {
  const [inputs, setInputs] = useState([])
  const [outputs, setOutputs] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState(null)
  const [permissionError, setPermissionError] = useState(null)
  const [enumerating, setEnumerating] = useState(false)
  const permissionGrantedRef = useRef(false)
  const knownIdsRef = useRef(null)

  const enumerate = useCallback(async () => {
    setEnumerating(true)
    try {
      if (!permissionGrantedRef.current) {
        try {
          const probe = await navigator.mediaDevices.getUserMedia({ audio: true })
          probe.getTracks().forEach((t) => t.stop())
          permissionGrantedRef.current = true
        } catch (err) {
          setPermissionError(describePermissionError(err))
          return
        }
      }
      setPermissionError(null)

      const all = await navigator.mediaDevices.enumerateDevices()
      const rawInputs = all.filter((d) => d.kind === 'audioinput')
      const concrete = rawInputs.filter((d) => !ALIAS_IDS.has(d.deviceId))
      const audioInputs = (concrete.length ? concrete : rawInputs).map((d) => {
        const label = d.label || `Audio input ${d.deviceId.slice(0, 6)}`
        return { deviceId: d.deviceId, label: cleanLabel(label), kind: classify(label) }
      })
      const audioOutputs = all
        .filter((d) => d.kind === 'audiooutput')
        .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Audio output' }))

      // A newly plugged-in device that outranks the current one takes over,
      // so connecting a mixer or Bluetooth mic needs no clicks.
      const known = knownIdsRef.current
      const fresh = known ? audioInputs.filter((d) => !known.has(d.deviceId)) : []
      knownIdsRef.current = new Set(audioInputs.map((d) => d.deviceId))

      setInputs(audioInputs)
      setOutputs(audioOutputs)
      setSelectedDeviceId((prev) => {
        const current = audioInputs.find((d) => d.deviceId === prev)
        if (!current) return pickPreferred(audioInputs)?.deviceId ?? null
        const bestFresh = pickPreferred(fresh)
        return bestFresh && RANK[bestFresh.kind] > RANK[current.kind] ? bestFresh.deviceId : prev
      })
    } catch (err) {
      console.error('[Devices] Enumeration failed:', err)
      setPermissionError(describePermissionError(err))
    } finally {
      setEnumerating(false)
    }
  }, [])

  useEffect(() => {
    enumerate()
    navigator.mediaDevices.addEventListener('devicechange', enumerate)
    return () => navigator.mediaDevices.removeEventListener('devicechange', enumerate)
  }, [enumerate])

  return {
    inputs,
    outputs,
    selectedDeviceId,
    setSelectedDeviceId,
    permissionError,
    enumerating,
    refresh: enumerate,
  }
}
