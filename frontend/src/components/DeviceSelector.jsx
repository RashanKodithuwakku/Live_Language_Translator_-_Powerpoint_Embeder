/**
 * DeviceSelector.jsx
 * ──────────────────
 * Compact operator control: one input dropdown (auto-picks mixer, then
 * Bluetooth/headset, then laptop mic) plus the slide-media audio options. Deliberately small so the audience's eyes stay
 * on the slides and subtitles, but the active input is always spelled out
 * in one line — the wrong input is the biggest live failure risk.
 */

import React from 'react'

const selectClass =
  'w-full min-w-0 truncate rounded-md border border-border bg-surface-2 px-2 py-1 text-xs text-slate-200 outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-60'

// Google weighs the first language far more than the alternatives, so the
// speaker's main language must be first or their speech is misrecognized.
const SPEAKER_LANGUAGES = [
  { code: 'si-LK', label: 'Speaker: Sinhala' },
  { code: 'ta-LK', label: 'Speaker: Tamil' },
  { code: 'en-US', label: 'Speaker: English' },
]

const PROFILES = [
  { code: 'eco', label: 'Profile: ECO (save credit)' },
  { code: 'event', label: 'Profile: EVENT (best quality)' },
]

const KIND = {
  mixer: { tag: 'Mixer', status: 'Mixer / line input', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  headset: { tag: 'Bluetooth', status: 'Bluetooth / headset mic', color: 'text-sky-400', dot: 'bg-sky-400' },
  mic: { tag: 'Mic', status: 'Laptop mic', color: 'text-sky-400', dot: 'bg-sky-400' },
}

export default function DeviceSelector({
  inputs,
  outputs,
  selectedDeviceId,
  onSelect,
  locked,
  permissionError,
  enumerating,
  onRefresh,
  speakerLanguage,
  onSpeakerLanguageChange,
  profile,
  onProfileChange,
  mediaSinkId,
  onMediaSinkChange,
  pauseDuringMedia,
  onPauseDuringMediaChange,
}) {
  const selected = inputs.find((d) => d.deviceId === selectedDeviceId)

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <select
        value={profile}
        onChange={(e) => onProfileChange(e.target.value)}
        disabled={locked}
        className={selectClass}
        title="ECO for daily testing · EVENT for rehearsal and Oct 5–6"
        aria-label="Operating profile"
      >
        {PROFILES.map((p) => (
          <option key={p.code} value={p.code}>{p.label}</option>
        ))}
      </select>
      <select
        value={speakerLanguage}
        onChange={(e) => onSpeakerLanguageChange(e.target.value)}
        className={selectClass}
        title="Main language of the current speaker — can be changed while live"
        aria-label="Speaker language"
      >
        {SPEAKER_LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>{l.label}</option>
        ))}
      </select>
      {permissionError ? (
        <div className="flex flex-col items-start gap-1 rounded-md bg-red-950/50 px-2 py-1 text-[11px] leading-snug text-red-300 ring-1 ring-red-800/50">
          {permissionError}
          <button type="button" onClick={onRefresh} disabled={enumerating} className="font-semibold underline hover:text-white">
            {enumerating ? 'Checking…' : 'Retry'}
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-1">
            <select
              value={selectedDeviceId || ''}
              onChange={(e) => onSelect(e.target.value)}
              disabled={locked || inputs.length === 0}
              className={selectClass}
              title={selected ? `Audio input: ${selected.label}` : 'Audio input'}
              aria-label="Audio input device"
            >
              {inputs.length === 0 && <option value="">No inputs found</option>}
              {inputs.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {KIND[d.kind].tag} · {d.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onRefresh}
              disabled={locked || enumerating}
              className={`shrink-0 rounded-md px-1 text-sm text-slate-500 hover:text-primary disabled:opacity-40 ${enumerating ? 'animate-spin' : ''}`}
              title="Rescan audio devices"
              aria-label="Rescan audio devices"
            >
              ↻
            </button>
          </div>
          {selected && (
            <p className={`flex items-center gap-1 truncate text-[10px] ${KIND[selected.kind].color}`} title={selected.label}>
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${KIND[selected.kind].dot}`} />
              {KIND[selected.kind].status}
            </p>
          )}
        </>
      )}

      <details className="group text-[10px] text-slate-500">
        <summary className="cursor-pointer select-none list-none hover:text-slate-300">
          <span className="inline-block transition-transform group-open:rotate-90">›</span> Slide video audio
        </summary>
        <div className="mt-1 flex flex-col gap-1">
          <select
            value={mediaSinkId}
            onChange={(e) => onMediaSinkChange(e.target.value)}
            className={selectClass}
            aria-label="Output device for slide videos"
          >
            <option value="">System default output</option>
            {outputs
              .filter((d) => d.deviceId !== 'default' && d.deviceId !== 'communications')
              .map((d) => (
                <option key={d.deviceId} value={d.deviceId}>{d.label}</option>
              ))}
          </select>
          <label className="flex cursor-pointer items-center gap-1.5 text-slate-400">
            <input
              type="checkbox"
              checked={pauseDuringMedia}
              onChange={(e) => onPauseDuringMediaChange(e.target.checked)}
              className="accent-sky-400"
            />
            Pause captions while slide media plays
          </label>
        </div>
      </details>
    </div>
  )
}
