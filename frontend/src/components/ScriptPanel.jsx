/**
 * Five finished sentences, three languages each.
 * Updates only when the finalized buffer changes (React.memo).
 */

import React, { useMemo } from 'react'

import { scriptSlots } from '../lib/scriptBuffer'

const LINES = [
  { key: 'sinhala', tag: 'සිංහල', text: 'font-semibold text-white', chip: 'text-zinc-100 ring-white/20' },
  { key: 'english', tag: 'English', text: 'font-medium text-zinc-300', chip: 'text-zinc-300 ring-white/15' },
  { key: 'tamil', tag: 'தமிழ்', text: 'font-semibold text-zinc-100', chip: 'text-zinc-300 ring-white/15' },
]

function ScriptPanel({ sentences }) {
  const slots = useMemo(() => scriptSlots(sentences), [sentences])
  const newestId = sentences.length ? sentences[sentences.length - 1].id : null

  return (
    <div
      className="grid h-full min-h-0 grid-rows-5 gap-1.5 font-subtitle"
      aria-live="polite"
      aria-label="Script of the last five sentences"
    >
      {slots.map((item, index) => (
        <article
          key={item ? item.id : `empty-${index}`}
          data-script-block=""
          className={`grid min-h-0 grid-rows-3 gap-0.5 overflow-hidden rounded-xl px-3 py-1 ring-1 ring-white/10 ${
            item ? 'bg-surface-2/80' : 'bg-transparent'
          } ${item && item.id === newestId ? 'animate-slide-up' : ''}`}
        >
          {item ? (
            LINES.map((line) => (
              <p
                key={line.key}
                data-script-line={line.key}
                title={item[line.key]}
                className={`flex min-h-0 items-center gap-2 overflow-hidden leading-snug ${line.text}`}
              >
                <span className={`hidden w-14 shrink-0 rounded-full px-1.5 py-0.5 text-center text-[10px] font-semibold ring-1 sm:inline-block ${line.chip}`}>
                  {line.tag}
                </span>
                <span className="line-clamp-2 min-w-0 break-words text-[clamp(12px,1.7vh,18px)]">
                  {item[line.key]}
                </span>
              </p>
            ))
          ) : (
            <p className="col-span-1 row-span-3 flex items-center text-sm text-slate-600">
              {index === 0 && sentences.length === 0 ? 'Finished sentences will appear here' : ''}
            </p>
          )}
        </article>
      ))}
    </div>
  )
}

export default React.memo(ScriptPanel)
