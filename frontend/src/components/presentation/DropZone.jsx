import React, { useRef, useState } from 'react'

const ACCEPTED = ['pptx', 'pdf']

export function fileKind(file) {
  const ext = file?.name?.split('.').pop()?.toLowerCase()
  return ACCEPTED.includes(ext) ? ext : null
}

export default function DropZone({ onFile, error }) {
  const [dragOver, setDragOver] = useState(false)
  const [rejected, setRejected] = useState(null)
  const inputRef = useRef(null)

  const accept = (file) => {
    if (!file) return
    if (!fileKind(file)) {
      setRejected(`"${file.name}" is not a .pptx or .pdf file.`)
      return
    }
    setRejected(null)
    onFile(file)
  }

  const message = rejected || error

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        accept(e.dataTransfer.files[0])
      }}
      className={`flex h-full w-full flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed px-6 text-center transition-colors ${
        dragOver ? 'border-primary bg-primary/10' : 'border-border hover:border-slate-500'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pptx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        className="hidden"
        onChange={(e) => {
          accept(e.target.files[0])
          e.target.value = ''
        }}
      />

      <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="text-slate-500">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8M12 17v4M12 7v6M9 10l3-3 3 3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>

      <div>
        <p className="text-lg font-semibold text-slate-200">
          {dragOver ? 'Drop to load the presentation' : 'Drag & drop your presentation here'}
        </p>
        <p className="mt-1 text-sm text-slate-400">PowerPoint (.pptx) or PDF — videos in the .pptx play in place</p>
      </div>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="rounded-lg bg-primary/15 px-5 py-2 text-sm font-semibold text-primary ring-1 ring-primary/40 transition-colors hover:bg-primary/25"
      >
        Choose from device
      </button>

      {message && (
        <p className="max-w-lg rounded-lg bg-red-950/60 px-4 py-2 text-sm text-red-300 ring-1 ring-red-800/60">
          {message}
        </p>
      )}
    </div>
  )
}
