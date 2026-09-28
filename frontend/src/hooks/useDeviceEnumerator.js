/**
 * useDeviceEnumerator.js
 * ──────────────────────
 * Lists audio inputs (for the mixer feed) and audio outputs (for slide
 * video sound), and auto-selects the USB sound card.
 *
 * USB detection: device labels containing "USB" or a common audio-interface
 * brand. Windows also lists virtual "Default - …" and "Communications - …"
 * aliases; we prefer the concrete device so capture stays pinned to the
 * sound card even if someone changes the Windows default mid-event.
 *
 * Labels are only exposed after microphone permission is granted, so a
 * short permission probe runs first.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

const USB_PATTERN =
  /\busb\b|behringer|focusrite|scarlett|presonus|steinberg|roland|tascam|yamaha|audient|motu|mackie|m-audio|zoom|ugreen|sound ?blaster|creative|u-phoria|umc\d/i

const ALIAS_IDS = new Set(['default', 'communications'])

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
  const concrete = inputs.filter((d) => !ALIAS_IDS.has(d.deviceId))
  return (
    concrete.find((d) => d.isUSB) ||
    inputs.find((d) => d.isUSB) ||
    inputs.find((d) => d.deviceId === 'default') ||
    inputs[0]
  )
}

export function useDeviceEnumerator() {
  const [inputs, setInputs] = useState([])
  const [outputs, setOutputs] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState(null)
  const [permissionError, setPermissionError] = useState(null)
  const [enumerating, setEnumerating] = useState(false)
  const permissionGrantedRef = useRef(false)

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
      const audioInputs = all
        .filter((d) => d.kind === 'audioinput')
        .map((d) => ({
          deviceId: d.deviceId,
          label: d.label || `Audio input ${d.deviceId.slice(0, 6)}`,
          isUSB: USB_PATTERN.test(d.label),
        }))
      const audioOutputs = all
        .filter((d) => d.kind === 'audiooutput')
        .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Audio output' }))

      setInputs(audioInputs)
      setOutputs(audioOutputs)
      setSelectedDeviceId((prev) =>
        prev && audioInputs.some((d) => d.deviceId === prev)
          ? prev
          : pickPreferred(audioInputs)?.deviceId ?? null,
      )
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
