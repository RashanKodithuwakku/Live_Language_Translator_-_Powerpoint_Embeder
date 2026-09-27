/**
 * useDeviceEnumerator.js
 * ──────────────────────
 * Enumerates available audio input devices and attempts to auto-select
 * the USB sound card if one is detected.
 *
 * USB device identification heuristic:
 *   We match device labels containing "USB Audio", "USB", "CODEC",
 *   or any common USB audio interface brand (Behringer, Focusrite,
 *   MOTU, PreSonus, Scarlett, Yamaha, Roland, Tascam, etc.).
 *   The operator can always override via the dropdown.
 *
 * Permission note:
 *   enumerateDevices() returns full labels only AFTER the user has
 *   granted microphone permission. We therefore trigger an initial
 *   getUserMedia() call to prompt for permission, then enumerate.
 */

import { useState, useEffect, useCallback } from 'react'

const USB_KEYWORDS = [
  'usb audio',
  'usb',
  'codec',
  'focusrite',
  'scarlett',
  'behringer',
  'motu',
  'presonus',
  'roland',
  'tascam',
  'yamaha',
  'steinberg',
  'audient',
  'universal audio',
  'mackie',
  'sound card',
  'line in',
  'external',
]

function isLikelyUSBDevice(label) {
  const lower = label.toLowerCase()
  return USB_KEYWORDS.some((kw) => lower.includes(kw))
}

export function useDeviceEnumerator() {
  const [devices, setDevices] = useState([]) // { deviceId, label, isUSB }[]
  const [selectedDeviceId, setSelectedDeviceId] = useState(null)
  const [permissionGranted, setPermissionGranted] = useState(false)
  const [enumerating, setEnumerating] = useState(false)
  const [permissionError, setPermissionError] = useState(null)

  const enumerate = useCallback(async () => {
    setEnumerating(true)
    try {
      // Trigger permission prompt if not already granted
      // (labels are empty strings until permission is granted)
      if (!permissionGranted) {
        try {
          const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true })
          tempStream.getTracks().forEach((t) => t.stop())
          setPermissionGranted(true)
        } catch (permErr) {
          setPermissionError('Microphone permission denied. Please allow microphone access.')
          setEnumerating(false)
          return
        }
      }

      const all = await navigator.mediaDevices.enumerateDevices()
      const audioInputs = all
        .filter((d) => d.kind === 'audioinput')
        .map((d) => ({
          deviceId: d.deviceId,
          label: d.label || `Microphone (${d.deviceId.slice(0, 8)}...)`,
          isUSB: isLikelyUSBDevice(d.label),
        }))

      setDevices(audioInputs)

      // Auto-select: prefer first USB-like device, fall back to first device
      const usbDevice = audioInputs.find((d) => d.isUSB)
      const defaultDevice = audioInputs.find((d) => d.deviceId === 'default') || audioInputs[0]

      setSelectedDeviceId((prev) => {
        // Don't override a manual selection
        if (prev && audioInputs.some((d) => d.deviceId === prev)) return prev
        return usbDevice?.deviceId || defaultDevice?.deviceId || null
      })
    } catch (err) {
      console.error('[Devices] Enumeration failed:', err)
    } finally {
      setEnumerating(false)
    }
  }, [permissionGranted])

  // Enumerate on mount
  useEffect(() => {
    enumerate()
  }, [enumerate])

  // Re-enumerate when devices change (USB plug/unplug)
  useEffect(() => {
    const handler = () => enumerate()
    navigator.mediaDevices.addEventListener('devicechange', handler)
    return () => navigator.mediaDevices.removeEventListener('devicechange', handler)
  }, [enumerate])

  return {
    devices,
    selectedDeviceId,
    setSelectedDeviceId,
    permissionGranted,
    permissionError,
    enumerating,
    refresh: enumerate,
  }
}
