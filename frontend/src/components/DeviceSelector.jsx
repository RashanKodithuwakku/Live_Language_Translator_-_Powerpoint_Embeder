/**
 * DeviceSelector.jsx
 * ──────────────────
 * Dropdown + status display for audio input device selection.
 *
 * Critical UX note (from spec):
 *   Getting the wrong audio device live is the single biggest failure risk.
 *   This component prominently shows which device is ACTIVE, highlights
 *   USB-detected devices with a badge, and always keeps the full list
 *   visible so the operator can verify and override.
 */

import React from 'react'

export default function DeviceSelector({
  devices,
  selectedDeviceId,
  onSelect,
  disabled,
  permissionError,
  enumerating,
  onRefresh,
}) {
  const selectedDevice = devices.find((d) => d.deviceId === selectedDeviceId)

  return (
    <div className="flex flex-col gap-2">
      {/* Label row */}
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Audio Input Device
        </label>
        <button
          onClick={onRefresh}
          disabled={disabled || enumerating}
          className="text-xs text-primary hover:text-sky-300 transition-colors disabled:opacity-40"
          title="Refresh device list"
        >
          {enumerating ? '↻ Scanning…' : '↻ Refresh'}
        </button>
      </div>

      {/* Permission error */}
      {permissionError && (
        <div className="flex items-center gap-2 rounded-lg bg-red-900/30 border border-red-700/50 px-3 py-2 text-xs text-red-300">
          <span>⚠</span>
          <span>{permissionError}</span>
        </div>
      )}

      {/* Dropdown */}
      <div className="relative">
        <select
          value={selectedDeviceId || ''}
          onChange={(e) => onSelect(e.target.value)}
          disabled={disabled || enumerating || devices.length === 0}
          className={`
            w-full appearance-none rounded-xl px-4 py-2.5 pr-10 text-sm font-medium
            bg-surface-2 border transition-all duration-200 outline-none cursor-pointer
            ${disabled
              ? 'border-border text-slate-500 cursor-not-allowed'
              : 'border-border text-slate-100 hover:border-primary focus:border-primary focus:ring-1 focus:ring-primary/40'
            }
          `}
        >
          {devices.length === 0 ? (
            <option value="">No audio devices found</option>
          ) : (
            devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.isUSB ? '🔌 ' : '🎤 '}
                {device.label}
                {device.isUSB ? ' [USB]' : ''}
              </option>
            ))
          )}
        </select>

        {/* Custom chevron */}
        <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>

      {/* Active device status */}
      {selectedDevice && (
        <div className={`
          flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium border
          ${selectedDevice.isUSB
            ? 'bg-emerald-900/20 border-emerald-700/40 text-emerald-300'
            : 'bg-sky-900/20 border-sky-700/40 text-sky-300'
          }
        `}>
          <span className="flex-shrink-0">
            {selectedDevice.isUSB ? '✓ USB Device Active:' : '✓ Active:'}
          </span>
          <span className="truncate font-semibold">{selectedDevice.label}</span>
          {selectedDevice.isUSB && (
            <span className="ml-auto flex-shrink-0 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-400 border border-emerald-500/30">
              USB
            </span>
          )}
        </div>
      )}

      {/* Hint */}
      <p className="text-[11px] text-slate-500 leading-relaxed">
        Select the <strong className="text-slate-400">USB sound card</strong> connected to the audio mixer.
        The active device is shown above — verify this before starting.
      </p>
    </div>
  )
}
