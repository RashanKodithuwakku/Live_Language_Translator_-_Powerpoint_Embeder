/**
 * SubtitlePanel.jsx
 * ─────────────────
 * Exactly three lines, current sentence only — no history, no scrolling.
 * A new final sentence replaces all three lines in place.
 *
 *   Line 1  Sinhala translation   (largest)
 *   Line 2  Tamil translation
 *   Line 3  English translation
 *
 * Each line owns a fixed share of the panel height. Text starts as large as
 * that row allows (for readability from the back of the hall) and shrinks
 * only as much as needed for a long sentence to fit — it is never clipped
 * and never scrolls.
 */

import React, { useLayoutEffect, useRef } from 'react'

const LINES = [
  { key: 'sinhala', tag: 'සිංහල', share: 1.2, maxPx: 60, minPx: 11, lineRatio: 0.62,
    textClass: 'font-semibold text-white', tagClass: 'text-zinc-100 ring-white/20' },
  { key: 'tamil', tag: 'தமிழ்', share: 1.1, maxPx: 54, minPx: 11, lineRatio: 0.6,
    textClass: 'font-semibold text-zinc-100', tagClass: 'text-zinc-300 ring-white/15' },
  { key: 'original', tag: 'English', share: 0.7, maxPx: 30, minPx: 10, lineRatio: 0.6,
    textClass: 'font-normal text-zinc-400', tagClass: 'text-zinc-400 ring-white/10' },
]

const GLYPH_SAFETY_PX = 4

function FitText({ text, maxPx, minPx, lineRatio, className }) {
  const boxRef = useRef(null)
  const textRef = useRef(null)

  useLayoutEffect(() => {
    const box = boxRef.current
    const el = textRef.current
    if (!box || !el) return

    // Sinhala/Tamil vowel signs reach above and below the line box.
    const fits = () => el.scrollHeight <= box.clientHeight - GLYPH_SAFETY_PX

    const fit = () => {
      const ceiling = Math.min(maxPx, Math.max(minPx, box.clientHeight * lineRatio))
      let lo = minPx
      let hi = ceiling
      el.style.fontSize = `${hi}px`
      if (fits()) return
      while (hi - lo > 0.5) {
        const mid = (lo + hi) / 2
        el.style.fontSize = `${mid}px`
        if (fits()) lo = mid
        else hi = mid
      }
      el.style.fontSize = `${lo}px`
    }

    fit()
    // Refit when the panel resizes, and when the Noto web fonts finish
    // loading (their glyphs are taller than the fallback font's).
    const observer = new ResizeObserver(fit)
    observer.observe(box)
    document.fonts.addEventListener('loadingdone', fit)
    document.fonts.ready.then(fit)
    return () => {
      observer.disconnect()
      document.fonts.removeEventListener('loadingdone', fit)
    }
  }, [text, maxPx, minPx, lineRatio])

  return (
    <div ref={boxRef} className="flex h-full min-w-0 flex-1 items-center overflow-hidden">
      <p ref={textRef} className={`w-full break-words leading-[1.3] ${className}`}>
        {text}
      </p>
    </div>
  )
}

// Translation-only view has the whole screen, so let lines grow larger.
const LARGE_SCALE = 2.2

export default function SubtitlePanel({ subtitles, large = false }) {
  const scale = large ? LARGE_SCALE : 1
  const hasContent = Boolean(subtitles.sinhala || subtitles.tamil || subtitles.original)

  return (
    <div
      className="grid h-full min-h-0 gap-1 font-subtitle"
      style={{ gridTemplateRows: LINES.map((l) => `${l.share}fr`).join(' ') }}
      aria-live="polite"
    >
      {LINES.map((line, index) => (
        <div
          key={line.key}
          className={`flex min-h-0 items-center gap-3 ${index === 2 ? 'border-t border-border/60 pt-1' : ''}`}
        >
          <span
            className={`hidden w-[4.5rem] shrink-0 rounded-full px-2 py-0.5 text-center text-[11px] font-semibold ring-1 sm:inline-block ${line.tagClass}`}
          >
            {line.tag}
          </span>
          {hasContent ? (
            <FitText
              key={`${line.key}-${subtitles.seq}`}
              text={subtitles[line.key]}
              maxPx={line.maxPx * scale}
              minPx={line.minPx}
              lineRatio={line.lineRatio}
              className={`animate-slide-up ${line.textClass}`}
            />
          ) : (
            <p className="truncate text-lg text-slate-600">
              {index === 0 ? 'Live subtitles will appear here' : ''}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
