/**
 * SlideMediaLayer.jsx
 * ───────────────────
 * Overlays the videos / sounds embedded in a .pptx on top of the rendered
 * slide, at the exact rectangle PowerPoint placed them (fractions of slide
 * size, computed by the backend).
 *
 * • Autoplay / loop / volume / "play full screen" follow the deck settings.
 * • Output is routed with HTMLMediaElement.setSinkId() to the device the
 *   operator picked for slide audio (e.g. the HDMI/PA feed).
 * • Every element reports whether it is currently audible, so the app can
 *   pause caption capture while slide media is playing — the soundtrack
 *   must never be transcribed if it leaks back through the mixer.
 * • Leaving the slide unmounts the elements, which stops playback.
 */

import React, { useEffect, useRef, useState } from 'react'
import { backendUrl } from '../../lib/presentationApi'

function isAudible(el) {
  return !el.paused && !el.ended && !el.muted && el.volume > 0
}

function useMediaElement({ item, sinkId, onAudibleChange }) {
  const ref = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [failure, setFailure] = useState(() => {
    if (!item.available) return item.reason
    const probe = document.createElement(item.kind)
    if (item.mime && probe.canPlayType(item.mime) === '') {
      return `${item.mime.split('/')[1].toUpperCase()} can't play in the browser — re-insert it as MP4 (H.264)`
    }
    return null
  })

  useEffect(() => {
    const el = ref.current
    if (!el || failure) return
    el.volume = Math.min(1, Math.max(0, item.volume ?? 1))
    el.muted = Boolean(item.muted)
    if (item.autoplay) el.play().catch(() => {})
    return () => {
      el.pause()
      onAudibleChange(item.id, false)
    }
  }, [item, failure, onAudibleChange])

  useEffect(() => {
    const el = ref.current
    if (!el || failure || typeof el.setSinkId !== 'function') return
    el.setSinkId(sinkId || '').catch((err) => console.warn('[Media] setSinkId failed:', err))
  }, [sinkId, failure])

  const report = () => {
    const el = ref.current
    if (!el) return
    setPlaying(!el.paused && !el.ended)
    onAudibleChange(item.id, isAudible(el))
  }

  const events = {
    onPlay: report,
    onPause: report,
    onEnded: report,
    onVolumeChange: report,
    onError: () => {
      setFailure('This media file could not be played')
      onAudibleChange(item.id, false)
    },
  }

  return { ref, playing, failure, events }
}

function rectStyle(item) {
  return {
    left: `${item.x * 100}%`,
    top: `${item.y * 100}%`,
    width: `${item.w * 100}%`,
    height: `${item.h * 100}%`,
  }
}

function FailureBadge({ text }) {
  return (
    <div className="absolute bottom-1 left-1 right-1 truncate rounded bg-slate-900/85 px-2 py-1 text-[11px] text-amber-300" title={text}>
      ⚠ {text}
    </div>
  )
}

function SlideVideo({ item, sinkId, onAudibleChange }) {
  const { ref, playing, failure, events } = useMediaElement({ item, sinkId, onAudibleChange })
  const expanded = item.fullScreen && playing

  if (failure) {
    return (
      <div className="absolute" style={rectStyle(item)}>
        <FailureBadge text={failure} />
      </div>
    )
  }

  return (
    <video
      ref={ref}
      src={backendUrl(item.url)}
      poster={backendUrl(item.posterUrl) || undefined}
      preload="auto"
      playsInline
      controls
      loop={item.loop}
      className={`absolute bg-slate-900 object-contain ${expanded ? 'z-20' : 'z-10'}`}
      style={expanded ? { inset: 0, width: '100%', height: '100%' } : rectStyle(item)}
      {...events}
    />
  )
}

function SlideAudio({ item, sinkId, onAudibleChange }) {
  const { ref, playing, failure, events } = useMediaElement({ item, sinkId, onAudibleChange })

  if (failure) {
    return (
      <div className="absolute min-w-[12rem]" style={rectStyle(item)}>
        <FailureBadge text={failure} />
      </div>
    )
  }

  const toggle = () => {
    const el = ref.current
    if (!el) return
    if (el.paused) el.play().catch(() => {})
    else el.pause()
  }

  return (
    <>
      <audio ref={ref} src={backendUrl(item.url)} preload="auto" loop={item.loop} {...events} />
      <button
        type="button"
        onClick={toggle}
        title={playing ? 'Pause sound' : 'Play sound'}
        aria-label={playing ? 'Pause slide sound' : 'Play slide sound'}
        className={`absolute z-10 rounded-full transition ${
          playing ? 'animate-pulse-soft ring-4 ring-primary/70' : 'hover:ring-2 hover:ring-primary/60'
        }`}
        style={rectStyle(item)}
      />
    </>
  )
}

export default function SlideMediaLayer({ items, sinkId, onAudibleChange }) {
  if (!items?.length) return null
  return (
    <div className="pointer-events-none absolute inset-0 [&>*]:pointer-events-auto">
      {items.map((item) =>
        item.kind === 'video' ? (
          <SlideVideo key={item.id} item={item} sinkId={sinkId} onAudibleChange={onAudibleChange} />
        ) : (
          <SlideAudio key={item.id} item={item} sinkId={sinkId} onAudibleChange={onAudibleChange} />
        ),
      )}
    </div>
  )
}
