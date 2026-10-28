import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ScriptPanel from '../src/components/ScriptPanel.jsx'
import { appendFinal } from '../src/lib/scriptBuffer.js'

function mock(n) {
  return {
    id: `s${n}`,
    at: n,
    sinhala: `සිංහල-${n}`,
    english: `English-${n}`,
    tamil: `தமிழ்-${n}`,
  }
}

let buffer = []
for (let n = 1; n <= 5; n += 1) buffer = appendFinal(buffer, mock(n))
const html = renderToStaticMarkup(React.createElement(ScriptPanel, { sentences: buffer }))
const blocks = html.split('data-script-block').length - 1
const lines = html.split('data-script-line').length - 1
if (blocks !== 5) throw new Error(`blocks ${blocks}`)
if (lines !== 15) throw new Error(`lines ${lines}`)
for (const text of ['සිංහල-1', 'English-5', 'தமிழ்-3']) {
  if (!html.includes(text)) throw new Error(`missing ${text}`)
}

buffer = appendFinal(buffer, mock(6))
const next = renderToStaticMarkup(React.createElement(ScriptPanel, { sentences: buffer }))
if (next.includes('සිංහල-1')) throw new Error('oldest still rendered')
if (!next.includes('English-6') || !next.includes('සිංහල-2')) throw new Error('window did not roll')
if (next.split('data-script-line').length - 1 !== 15) throw new Error('lines after roll')
console.log('ok  script view renders 5 blocks and 15 lines, then evicts the oldest')
