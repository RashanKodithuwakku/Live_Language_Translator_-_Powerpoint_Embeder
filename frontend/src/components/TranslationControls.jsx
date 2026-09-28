/**
 * Compact operator controls: Start/Stop, status, profile chip, meter.
 */

import React, { useEffect, useState } from 'react'

const STATUS = {
  idle: { label: 'Idle', dot: 'bg-slate-500', text: 'text-slate-400' },
  starting: { label: 'Starting…', dot: 'bg-sky-400 animate-pulse', text: 'text-sky-300' },
  connecting: { label: 'Connecting…', dot: 'bg-sky-400 animate-pulse', text: 'text-sky-300' },
  live: { label: 'Live', dot: 'bg-emerald-400 recording-glow', text: 'text-emerald-300' },
  reconnecting: { label: 'Reconnecting…', dot: 'bg-amber-400 animate-pulse', text: 'text-amber-300' },
  paused: { label: 'Paused — slide media', dot: 'bg-amber-400', text: 'text-amber-300' },
  inputLost: { label: 'Input lost', dot: 'bg-red-500 animate-pulse', text: 'text-red-300' },
}

const SERVER = {
  checking: { label: 'Server…', dot: 'bg-slate-500', text: 'text-slate-500', title: 'Checking backend' },
  ok: { label: 'Server', dot: 'bg-emerald-500', text: 'text-slate-500', title: 'Backend online' },
  nokey: {
    label: 'Key missing', dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400',
    title: 'Google key file missing — see README',
  },
  offline: {
    label: 'Server offline', dot: 'bg-red-500 animate-pulse', text: 'text-red-400',
    title: 'Backend offline — start uvicorn',
  },
}

function InputMeter({ db, clipping, snr, active }) {
  const fraction = Math.min(1, Math.max(0, (db + 60) / 60))
  return (
    <div className="flex w-full items-center gap-1.5" title={`Input ${db.toFixed(0)} dBFS${snr != null ? ` · SNR ~${snr} dB` : ''}`}>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
        <div
          className={`h-full rounded-full transition-[width] duration-100 ${
            clipping ? 'bg-red-500' : fraction > 0.85 ? 'bg-amber-400' : 'bg-emerald-400'
          }`}
          style={{ width: `${active ? fraction * 100 : 0}%` }}
        />
      </div>
      <span className={`w-7 text-right text-[9px] font-semibold ${clipping ? 'text-red-400' : 'text-slate-600'}`}>
        {clipping ? 'CLIP' : 'IN'}
      </span>
    </div>
  )
}

function RoundButton({ color, label, onClick, disabled, children }) {
  const palette =
    color === 'green'
      ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/50 focus-visible:ring-emerald-300'
      : 'bg-red-600 hover:bg-red-500 shadow-red-900/50 focus-visible:ring-red-300'
  return (
    <div className="flex flex-col items-center gap-0.5">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={`${label} Translation`}
        title={`${label} Translation`}
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white shadow-lg outline-none transition focus-visible:ring-2 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:shadow-none ${palette}`}
      >
        {children}
      </button>
      <span className="text-[10px] font-medium text-slate-400">{label}</span>
    </div>
  )
}

export default function TranslationControls({
  status, backend, level, active, busy, onStart, onStop, profile, cacheMode,
}) {
  const cfg = STATUS[status] || STATUS.idle
  const [meter, setMeter] = useState(level)

  useEffect(() => {
    setMeter(level)
  }, [level])

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between text-[11px]">
        <span className={`flex items-center gap-1.5 font-semibold ${cfg.text}`}>
          <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
          {cfg.label}
          {cacheMode && <span className="ml-1 text-[9px] font-normal text-amber-400">CACHE</span>}
        </span>
        <span className={`flex items-center gap-1 ${SERVER[backend].text}`} title={SERVER[backend].title}>
          <span className={`h-1.5 w-1.5 rounded-full ${SERVER[backend].dot}`} />
          {SERVER[backend].label}
        </span>
      </div>

      <div className="flex items-center">
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${
          profile === 'event' ? 'bg-emerald-950 text-emerald-300' : 'bg-slate-800 text-slate-400'
        }`}>
          {profile}
        </span>
      </div>

      <div className="flex items-start justify-center gap-6">
        <RoundButton color="green" label="Start" onClick={onStart} disabled={active || busy}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
        </RoundButton>
        <RoundButton color="red" label="Stop" onClick={onStop} disabled={!active}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="1.5" /></svg>
        </RoundButton>
      </div>

      <InputMeter db={meter.db} clipping={meter.clipping} snr={meter.snr} active={active} />
    </div>
  )
}
