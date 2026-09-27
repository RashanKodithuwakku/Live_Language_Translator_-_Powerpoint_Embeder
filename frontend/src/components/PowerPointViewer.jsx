/**
 * PowerPointViewer.jsx
 * ────────────────────
 * Accepts .pptx or .pdf files and renders slides in a strict 16:9 frame.
 *
 * Implementation decision — PPTX rendering strategy:
 *   Rendering .pptx natively in the browser requires parsing the Open XML
 *   format (a ZIP archive with XML inside). Client-side libraries like
 *   pptxjs and officegen are either unmaintained, produce unreliable output,
 *   or require a Node.js server process. For a production event tool, the
 *   safest approach is:
 *
 *     1. PDF files → rendered directly via react-pdf (pdfjs-dist), which
 *        is battle-tested and handles fonts, images, and vector graphics
 *        correctly in all Chromium browsers.
 *
 *     2. PPTX files → the operator should export from PowerPoint/Keynote/
 *        LibreOffice as PDF BEFORE the event (a 30-second step). This is
 *        the standard industry practice for presentation display systems.
 *        We guide them with a clear in-app message if they drop a .pptx.
 *
 *   This decision is intentional, not a limitation — it avoids the runtime
 *   failure modes of in-browser PPTX parsing under live-event pressure.
 *
 * 16:9 enforcement:
 *   The viewer uses CSS aspect-ratio: 16/9 with overflow: hidden.
 *   react-pdf's Page component is given explicit width via a ResizeObserver
 *   so the canvas fills the container perfectly without any gutter.
 *
 * Navigation:
 *   Left/right arrow buttons on the outer edges of the viewer frame.
 *   Keyboard arrow keys also work (when the viewer is focused).
 */

import React, { useState, useRef, useCallback, useEffect } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

// Configure PDF.js worker (required by react-pdf v7+)
// Using the bundled worker via CDN-compatible path for Vite
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

// ── Arrow button ──────────────────────────────────────────────────────────
function NavArrow({ direction, onClick, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        flex items-center justify-center w-10 h-10 rounded-full
        bg-surface/80 border border-border text-slate-300
        hover:bg-surface-3 hover:text-white hover:border-primary
        disabled:opacity-20 disabled:cursor-not-allowed
        transition-all duration-150 flex-shrink-0
        backdrop-blur-sm
      `}
      aria-label={direction === 'left' ? 'Previous slide' : 'Next slide'}
    >
      {direction === 'left' ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
      )}
    </button>
  )
}

// ── Drop zone / File picker ────────────────────────────────────────────────
function DropZone({ onFile }) {
  const [isDragOver, setIsDragOver] = useState(false)
  const inputRef = useRef(null)

  const handleFile = useCallback((file) => {
    if (!file) return
    const ext = file.name.split('.').pop().toLowerCase()
    if (!['pdf', 'pptx'].includes(ext)) {
      alert('Please select a .pdf or .pptx file.')
      return
    }
    onFile(file)
  }, [onFile])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    handleFile(file)
  }, [handleFile])

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      className={`
        flex flex-col items-center justify-center h-full gap-5 cursor-pointer
        rounded-2xl border-2 border-dashed transition-all duration-200
        ${isDragOver ? 'drop-active' : 'border-border/50 hover:border-border'}
      `}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.pptx"
        className="hidden"
        onChange={(e) => handleFile(e.target.files[0])}
      />

      {/* Icon */}
      <div className="flex flex-col items-center gap-3 text-slate-500">
        <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="text-slate-600">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
        <div className="text-center">
          <p className="text-base font-semibold text-slate-300">
            {isDragOver ? 'Drop your presentation here' : 'Load Presentation'}
          </p>
          <p className="text-sm text-slate-500 mt-1">
            Drag & drop or click to choose a <strong className="text-slate-400">.pdf</strong> file
          </p>
          <p className="text-xs text-slate-600 mt-3 max-w-xs leading-relaxed">
            For <strong className="text-slate-500">.pptx</strong> files: export as PDF from
            PowerPoint first (File → Export → PDF). This ensures pixel-perfect rendering
            during the live event.
          </p>
        </div>
      </div>

      <button
        className="px-5 py-2 rounded-xl bg-primary/10 border border-primary/30 text-primary text-sm font-semibold hover:bg-primary/20 transition-colors"
        onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}
      >
        Choose File
      </button>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────
export default function PowerPointViewer() {
  const [file, setFile] = useState(null)
  const [fileType, setFileType] = useState(null) // 'pdf' | 'pptx'
  const [numPages, setNumPages] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [containerWidth, setContainerWidth] = useState(0)

  const containerRef = useRef(null)
  const pageRef = useRef(null)

  // ResizeObserver to get accurate container width for react-pdf
  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width)
      }
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [file])

  // Keyboard navigation
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        setCurrentPage((p) => Math.max(1, p - 1))
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {
        setCurrentPage((p) => Math.min(numPages, p + 1))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [numPages])

  const handleFile = useCallback((f) => {
    const ext = f.name.split('.').pop().toLowerCase()
    setFile(f)
    setFileType(ext)
    setCurrentPage(1)
    setNumPages(0)
  }, [])

  const handleDocumentLoad = ({ numPages }) => {
    setNumPages(numPages)
    setCurrentPage(1)
  }

  const isPPTX = fileType === 'pptx'

  return (
    <div className="flex flex-col h-full gap-3">
      {/* File info bar (when file is loaded) */}
      {file && (
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">
              Presentation
            </span>
            <span className="text-xs text-slate-300 font-medium truncate max-w-xs">
              {file.name}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {numPages > 0 && (
              <span className="text-xs text-slate-500 font-mono">
                {currentPage} / {numPages}
              </span>
            )}
            <button
              onClick={() => { setFile(null); setFileType(null); setNumPages(0) }}
              className="text-xs text-slate-500 hover:text-red-400 transition-colors"
              title="Close file"
            >
              ✕ Close
            </button>
          </div>
        </div>
      )}

      {/* 16:9 viewer frame + nav arrows */}
      <div className="flex items-center gap-3 flex-1 min-h-0">
        {/* Left arrow */}
        <NavArrow
          direction="left"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={!file || currentPage <= 1}
        />

        {/* 16:9 frame */}
        <div
          className="relative flex-1 min-h-0 rounded-2xl overflow-hidden bg-surface border border-border/60"
          style={{ aspectRatio: '16/9' }}
          ref={containerRef}
        >
          {!file ? (
            <DropZone onFile={handleFile} />
          ) : isPPTX ? (
            // PPTX guidance overlay
            <div className="flex flex-col items-center justify-center h-full gap-4 px-8 text-center">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="1.5">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <div>
                <p className="text-base font-semibold text-red-300">PPTX Direct Rendering Not Supported</p>
                <p className="text-sm text-slate-400 mt-2 leading-relaxed max-w-sm">
                  Please export your presentation as <strong className="text-slate-300">PDF</strong> from PowerPoint
                  (File → Export → PDF), then load the PDF file here.
                </p>
              </div>
              <button
                onClick={() => { setFile(null); setFileType(null) }}
                className="px-4 py-2 rounded-xl bg-primary/10 border border-primary/30 text-primary text-sm hover:bg-primary/20 transition-colors"
              >
                Load a Different File
              </button>
            </div>
          ) : (
            // PDF viewer
            <div className="flex items-center justify-center h-full w-full" ref={pageRef}>
              <Document
                file={file}
                onLoadSuccess={handleDocumentLoad}
                onLoadError={(err) => console.error('[PDF] Load error:', err)}
                loading={
                  <div className="flex items-center justify-center h-full text-slate-500 text-sm">
                    Loading PDF…
                  </div>
                }
                error={
                  <div className="flex items-center justify-center h-full text-red-400 text-sm">
                    Failed to load PDF
                  </div>
                }
                className="h-full w-full"
              >
                <Page
                  pageNumber={currentPage}
                  width={containerWidth || undefined}
                  renderAnnotationLayer={false}
                  renderTextLayer={false}
                  className="h-full w-full"
                  loading={null}
                />
              </Document>
            </div>
          )}
        </div>

        {/* Right arrow */}
        <NavArrow
          direction="right"
          onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
          disabled={!file || currentPage >= numPages || isPPTX}
        />
      </div>
    </div>
  )
}
