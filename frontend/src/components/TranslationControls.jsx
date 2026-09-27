/**
 * TranslationControls.jsx
 * ───────────────────────
 * Start/Stop buttons + VU meter for the live translation session.
 *
 * Visual design:
 *   - Large circular buttons (80px diameter) — impossible to miss under
 *     stage lighting with reduced screen brightness
 *   - Green Start (radial gradient, glow shadow)
 *   - Red Stop (radial gradient, glow shadow)
 *   - VU meter below buttons shows current microphone signal level
 *   - Connection status shown as a badge
 */

import React from 'react'

// ── VU Meter ──────────────────────────────────────────────────────────────
function VUMeter({ level }) {
  const bars = 20
  const activeCount = Math.round((level / 100) * bars)

  return (
    <div className="flex items-end gap-0.5 h-5" title={`Input level: ${level}%`}>
      {Array.from({ length: bars }).map((_, i) => {
        const active = i < activeCount
        const isHot = i >= bars * 0.8
        const isMid = i >= bars * 0.6

        return (
          <div
            key={i}
            className="w-1.5 rounded-sm transition-all duration-75"
            style={{
              height: `${50 + (i / bars) * 50}%`,
              background: active
                ? isHot
                  ? '#f87171'
                  : isMid
                  ? '#fbbf24'
                  : '#34d399'
                : 'rgba(51,65,85,0.5)',
            }}
          />
        )
      })}
    </div>
  )
}

// ── Connection status badge ────────────────────────────────────────────────
function StatusBadge({ status }) {
  const config = {
    idle:         { color: 'text-slate-500', bg: 'bg-slate-800',   dot: 'bg-slate-600',  label: 'Idle' },
    connecting:   { color: 'text-sky-400',   bg: 'bg-sky-900/30',  dot: 'bg-sky-400',    label: 'Connecting…' },
    connected:    { color: 'text-emerald-400',bg: 'bg-emerald-900/30', dot: 'bg-success', label: 'Connected' },
    error:        { color: 'text-red-400',   bg: 'bg-red-900/30',  dot: 'bg-red-400',    label: 'Error' },
    disconnected: { color: 'text-slate-400', bg: 'bg-slate-800',   dot: 'bg-slate-500',  label: 'Disconnected' },
  }

  const cfg = config[status] || config.idle

  return (
    <div className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${cfg.bg} ${cfg.color}`}>
      <div className={`h-1.5 w-1.5 rounded-full ${cfg.dot} ${status === 'connecting' ? 'animate-pulse' : ''}`} />
      {cfg.label}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────
export default function TranslationControls({
  isStreaming,
  connectionStatus,
  audioLevel,
  onStart,
  onStop,
}) {
  return (
    <div className="flex flex-col items-center gap-4">
      {/* Status badge */}
      <StatusBadge status={isStreaming ? 'connected' : connectionStatus} />

      {/* Start / Stop buttons */}
      <div className="flex items-center gap-8">
        {/* START */}
        <button
          id="btn-start-translation"
          onClick={onStart}
          disabled={isStreaming}
          className="btn-start w-20 h-20 flex-col gap-1"
          aria-label="Start Translation"
          title="Start Translation"
        >
          {/* Play icon */}
          <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7z" />
          </svg>
          <span className="text-[10px] font-bold uppercase tracking-wider">Start</span>
        </button>

        {/* STOP */}
        <button
          id="btn-stop-translation"
          onClick={onStop}
          disabled={!isStreaming}
          className="btn-stop w-20 h-20 flex-col gap-1"
          aria-label="Stop Translation"
          title="Stop Translation"
        >
          {/* Stop icon */}
          <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
            <path d="M6 6h12v12H6z" />
          </svg>
          <span className="text-[10px] font-bold uppercase tracking-wider">Stop</span>
        </button>
      </div>

      {/* VU meter */}
      <div className="flex flex-col items-center gap-1.5">
        <VUMeter level={audioLevel} />
        <span className="text-[10px] text-slate-600 uppercase tracking-widest">
          Input Level
        </span>
      </div>
    </div>
  )
}
