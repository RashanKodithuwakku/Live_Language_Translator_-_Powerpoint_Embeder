/**
 * SubtitlePanel.jsx
 * ─────────────────
 * Displays exactly THREE lines of subtitle text.
 *
 * CRITICAL BEHAVIOR (from spec):
 *   - No history, no scrolling. Only the current sentence is visible.
 *   - When a new sentence is finalized, all three lines replace in-place.
 *   - The previous sentence disappears completely.
 *
 * Line layout:
 *   Line 1 (top, most prominent)  — Sinhala translation
 *   Line 2 (middle)               — Tamil translation
 *   Line 3 (bottom, smaller)      — Original spoken text (never translated)
 *
 * Visual language:
 *   Line 1: purple (#a78bfa) — culturally neutral, visually distinct
 *   Line 2: amber (#fbbf24)  — warm, high-contrast against dark background
 *   Line 3: slate (#94a3b8)  — subdued, clearly secondary
 *
 * The `key` prop on each line forces a React re-mount on every update,
 * which triggers the CSS slide-up animation reliably even if the new
 * text happens to be identical to the previous sentence.
 */

import React, { useEffect, useRef } from 'react'

// Language label pill
function LangBadge({ label, color }) {
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest mr-3 flex-shrink-0 self-start mt-1"
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
    >
      {label}
    </span>
  )
}

function SubtitleLine({ text, color, label, animKey, size = 'normal', isPlaceholder = false }) {
  return (
    <div
      key={animKey}
      className={`flex items-start gap-1 ${isPlaceholder ? 'opacity-30' : 'subtitle-enter'}`}
    >
      <LangBadge label={label} color={color} />
      <span
        className={`leading-snug font-medium break-words flex-1 ${
          size === 'small' ? 'text-sm text-slate-400' : ''
        }`}
        style={size !== 'small' ? { color, fontSize: size === 'large' ? '1.35rem' : '1.1rem' } : {}}
      >
        {isPlaceholder ? '—' : text || '—'}
      </span>
    </div>
  )
}

export default function SubtitlePanel({ subtitles, isConnected, isStreaming }) {
  const { sinhala, tamil, original, animKey } = subtitles

  const hasContent = sinhala || tamil || original

  return (
    <div className="flex flex-col gap-3 py-2">
      {/* Status strip */}
      <div className="flex items-center gap-2 mb-1">
        <div className={`
          h-2 w-2 rounded-full flex-shrink-0 transition-all duration-500
          ${isStreaming ? 'bg-success recording-glow' : isConnected ? 'bg-primary animate-pulse-soft' : 'bg-border'}
        `} />
        <span className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">
          {isStreaming
            ? 'Live — translating'
            : isConnected
            ? 'Connected — waiting for audio'
            : 'Not connected'}
        </span>
      </div>

      {/* Divider */}
      <div className="h-px bg-gradient-to-r from-transparent via-border to-transparent" />

      {/* Subtitle lines */}
      <div className="flex flex-col gap-4">
        {/* Line 1 — Sinhala */}
        <SubtitleLine
          key={`si-${animKey}`}
          animKey={`si-${animKey}`}
          text={sinhala}
          label="සිං"
          color="#a78bfa"
          size="large"
          isPlaceholder={!hasContent}
        />

        {/* Line 2 — Tamil */}
        <SubtitleLine
          key={`ta-${animKey}`}
          animKey={`ta-${animKey}`}
          text={tamil}
          label="த"
          color="#fbbf24"
          size="normal"
          isPlaceholder={!hasContent}
        />

        {/* Divider before original */}
        <div className="h-px bg-gradient-to-r from-transparent via-border/60 to-transparent" />

        {/* Line 3 — Original (never translated) */}
        <SubtitleLine
          key={`orig-${animKey}`}
          animKey={`orig-${animKey}`}
          text={original}
          label="orig"
          color="#94a3b8"
          size="small"
          isPlaceholder={!hasContent}
        />
      </div>

      {!hasContent && !isStreaming && (
        <p className="text-center text-xs text-slate-600 mt-2">
          Subtitles will appear here when translation starts.
        </p>
      )}
    </div>
  )
}
