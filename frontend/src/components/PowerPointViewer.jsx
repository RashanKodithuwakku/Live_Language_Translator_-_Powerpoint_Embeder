/**
 * PowerPointViewer.jsx
 * ────────────────────
 * Section A: presentation display inside a strict 16:9 stage.
 *
 * File handling:
 *   • .pptx → uploaded to the backend, which converts it with the real
 *     PowerPoint (COM) or LibreOffice into a PDF and extracts embedded
 *     videos/sounds with their on-slide positions (see
 *     backend/presentation_service.py for why this beats in-browser PPTX
 *     rendering). The loaded deck survives a browser refresh.
 *   • .pdf  → rendered directly in the browser; no backend needed.
 *   Both render through pdf.js as vector graphics, sharp at any size.
 *
 * Layout:
 *   The stage is the largest 16:9 box that fits the available space
 *   (measured, not CSS-stretched), so it never distorts at any window size.
 *   A 16:9 deck fills it edge to edge; other slide sizes are centred.
 *
 * Page changes are double-buffered: the next page renders off-screen and
 * replaces the current one only once drawn, so there is no blank flash.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'

import DropZone, { fileKind } from './presentation/DropZone'
import SlideMediaLayer from './presentation/SlideMediaLayer'
import { fitAspect, useElementSize } from '../hooks/useElementSize'
import { backendUrl, deletePresentation, fetchManifest, uploadPptx } from '../lib/presentationApi'

pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const STAGE_ASPECT = 16 / 9
const STORAGE_KEY = 'liveTranslator.presentationId'
const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown', 'PageDown'])
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp', 'PageUp'])

function NavArrow({ direction, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={direction === 'left' ? 'Previous slide' : 'Next slide'}
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-surface-2 text-slate-300 ring-1 ring-border transition hover:bg-surface-3 hover:text-white hover:ring-primary disabled:cursor-not-allowed disabled:opacity-25"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d={direction === 'left' ? 'M15 18l-6-6 6-6' : 'M9 18l6-6-6-6'} />
      </svg>
    </button>
  )
}

function Spinner({ label, progress, onCancel }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-border border-t-primary" />
      <p className="text-base font-medium text-slate-200">{label}</p>
      {progress != null && (
        <div className="h-1.5 w-56 overflow-hidden rounded-full bg-surface-3">
          <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      {onCancel && (
        <button type="button" onClick={onCancel} className="text-sm text-slate-400 underline hover:text-slate-200">
          Cancel
        </button>
      )}
    </div>
  )
}

export default function PowerPointViewer({ mediaSinkId, onAudibleMediaChange }) {
  const [deck, setDeck] = useState(null) // { kind: 'pdf'|'pptx', name, source, manifest? }
  const [loading, setLoading] = useState(null) // { phase, progress }
  const [loadError, setLoadError] = useState(null)
  const [numPages, setNumPages] = useState(0)
  const [page, setPage] = useState(1)
  const [shownPage, setShownPage] = useState(1)
  const [pageAspect, setPageAspect] = useState(STAGE_ASPECT)

  const uploadRef = useRef(null)
  const areaRef = useRef(null)
  const area = useElementSize(areaRef)
  const stage = fitAspect(area.width, area.height, STAGE_ASPECT)
  const pageBox = fitAspect(stage.width, stage.height, pageAspect)

  // ── Audible media aggregation (for pausing captions) ─────────────────────
  const audibleRef = useRef(new Set())
  const handleAudibleChange = useCallback((id, audible) => {
    const set = audibleRef.current
    const before = set.size > 0
    if (audible) set.add(id)
    else set.delete(id)
    if (before !== set.size > 0) onAudibleMediaChange?.(set.size > 0)
  }, [onAudibleMediaChange])

  // ── Loading ──────────────────────────────────────────────────────────────
  const resetView = () => {
    setNumPages(0)
    setPage(1)
    setShownPage(1)
    setPageAspect(STAGE_ASPECT)
  }

  const showPptx = useCallback((manifest) => {
    resetView()
    setDeck({ kind: 'pptx', name: manifest.name, source: backendUrl(manifest.pdfUrl), manifest })
    localStorage.setItem(STORAGE_KEY, manifest.id)
  }, [])

  useEffect(() => {
    const savedId = localStorage.getItem(STORAGE_KEY)
    if (!savedId) return
    fetchManifest(savedId)
      .then(showPptx)
      .catch((err) => {
        if (err.status === 404) localStorage.removeItem(STORAGE_KEY)
      })
  }, [showPptx])

  const handleFile = async (file) => {
    setLoadError(null)
    resetView()
    if (fileKind(file) === 'pdf') {
      setDeck({ kind: 'pdf', name: file.name, source: file })
      return
    }

    setLoading({ phase: 'uploading', progress: 0 })
    const upload = uploadPptx(file, (phase, progress) => setLoading({ phase, progress }))
    uploadRef.current = upload
    try {
      showPptx(await upload.promise)
    } catch (err) {
      if (err.name !== 'AbortError') setLoadError(err.message)
    } finally {
      uploadRef.current = null
      setLoading(null)
    }
  }

  const removeDeck = () => {
    uploadRef.current?.abort()
    if (deck?.kind === 'pptx') deletePresentation(deck.manifest.id)
    localStorage.removeItem(STORAGE_KEY)
    audibleRef.current.clear()
    onAudibleMediaChange?.(false)
    setDeck(null)
    setLoadError(null)
    resetView()
  }

  // ── Navigation ───────────────────────────────────────────────────────────
  const go = useCallback((delta) => {
    setPage((p) => Math.min(Math.max(1, p + delta), Math.max(1, numPages)))
  }, [numPages])

  useEffect(() => {
    if (!numPages) return
    const onKey = (e) => {
      const tag = e.target?.tagName
      if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'VIDEO'].includes(tag)) return
      if (NEXT_KEYS.has(e.key)) {
        e.preventDefault()
        go(1)
      } else if (PREV_KEYS.has(e.key)) {
        e.preventDefault()
        go(-1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [numPages, go])

  // ── Slide ↔ PDF page mapping (hidden slides are omitted from the PDF) ────
  const slideForPage = useMemo(() => {
    const slides = deck?.manifest?.slides
    if (!slides || !numPages) return []
    const visible = slides.filter((s) => !s.hidden)
    return numPages === visible.length ? visible : slides
  }, [deck, numPages])

  const currentMedia = slideForPage[shownPage - 1]?.media

  const onDocumentLoad = async (pdf) => {
    setNumPages(pdf.numPages)
    const first = await pdf.getPage(1)
    const { width, height } = first.getViewport({ scale: 1 })
    setPageAspect(width / height)
  }

  const pagesToRender = shownPage === page ? [page] : [shownPage, page]
  const busyLabel = loading?.phase === 'uploading'
    ? 'Uploading presentation…'
    : 'Preparing slides and videos…'

  return (
    <div className="relative flex h-full w-full items-center gap-2 sm:gap-3">
      {deck && (
        <div className="absolute right-0 top-0 z-30 flex items-center gap-2 rounded-lg bg-surface/90 px-2 py-1 text-xs opacity-60 ring-1 ring-border transition-opacity hover:opacity-100">
          <span className="max-w-[16rem] truncate text-slate-300" title={deck.name}>{deck.name}</span>
          {numPages > 0 && <span className="font-mono text-slate-400">{page} / {numPages}</span>}
          <button
            type="button"
            onClick={removeDeck}
            className="rounded-md bg-red-500/15 px-2 py-0.5 font-semibold text-red-300 ring-1 ring-red-500/40 hover:bg-red-500/30"
          >
            Remove
          </button>
        </div>
      )}

      {deck && <NavArrow direction="left" onClick={() => go(-1)} disabled={page <= 1} />}

      <div ref={areaRef} className="flex h-full min-w-0 flex-1 items-center justify-center">
        <div
          className="relative overflow-hidden rounded-xl bg-surface-2 ring-1 ring-border"
          style={{ width: stage.width, height: stage.height }}
        >
          {loading ? (
            <Spinner
              label={busyLabel}
              progress={loading.phase === 'uploading' ? loading.progress : null}
              onCancel={removeDeck}
            />
          ) : !deck ? (
            <DropZone onFile={handleFile} error={loadError} />
          ) : (
            <Document
              file={deck.source}
              onLoadSuccess={onDocumentLoad}
              onLoadError={(err) => {
                console.error('[PDF] Load error:', err)
                setDeck(null)
                setLoadError(`Could not open "${deck.name}": ${err.message}`)
              }}
              loading={<Spinner label="Opening slides…" />}
              error={null}
              className="flex h-full w-full items-center justify-center"
            >
              {numPages > 0 && pageBox.width > 0 && (
                <div className="relative" style={{ width: pageBox.width, height: pageBox.height }}>
                  {pagesToRender.map((n) => (
                    <div
                      key={n}
                      className="absolute inset-0"
                      style={{ visibility: n === shownPage ? 'visible' : 'hidden' }}
                    >
                      <Page
                        pageNumber={n}
                        width={pageBox.width}
                        renderAnnotationLayer={false}
                        renderTextLayer={false}
                        loading={null}
                        onRenderSuccess={() => n === page && setShownPage(n)}
                      />
                    </div>
                  ))}
                  <SlideMediaLayer
                    key={shownPage}
                    items={currentMedia}
                    sinkId={mediaSinkId}
                    onAudibleChange={handleAudibleChange}
                  />
                </div>
              )}
            </Document>
          )}
        </div>
      </div>

      {deck && <NavArrow direction="right" onClick={() => go(1)} disabled={page >= numPages} />}
    </div>
  )
}
