/**
 * Buffer checks with the same shape the live translator already sends
 * (Sinhala, English, Tamil). No Gemini call.
 *
 * Run from frontend/:  node src/lib/scriptBuffer.test.mjs
 */

import { appendFinal, scriptSlots, SCRIPT_LIMIT } from './scriptBuffer.js'

function sentence(n) {
  return {
    id: `s${n}`,
    at: 1_700_000_000_000 + n,
    sinhala: `සිංහල ${n}`,
    english: `English ${n}`,
    tamil: `தமிழ் ${n}`,
  }
}

function testKeepsFiveAndEvictsTheOldest() {
  let buffer = []
  for (let n = 1; n <= 5; n += 1) buffer = appendFinal(buffer, sentence(n))
  if (buffer.length !== SCRIPT_LIMIT) throw new Error(`expected 5, got ${buffer.length}`)
  if (buffer[0].id !== 's1' || buffer[4].id !== 's5') throw new Error('order before eviction')
  const before = buffer
  buffer = appendFinal(buffer, sentence(6))
  if (buffer.length !== 5) throw new Error('length after 6th')
  if (buffer.some((item) => item.id === 's1')) throw new Error('oldest was not evicted')
  if (buffer[0].id !== 's2' || buffer[4].id !== 's6') throw new Error('shift order')
  if (buffer === before) throw new Error('buffer should be a new array')
  if (before[0].id !== 's1') throw new Error('previous buffer was mutated')
}

function testIgnoresInterimEmptyAndKeepsReference() {
  const buffer = [sentence(1)]
  const same = appendFinal(buffer, { id: 'x', at: 1, sinhala: '  ', english: '', tamil: '' })
  if (same !== buffer) throw new Error('empty final should not allocate')
}

function testSlotsAlwaysFive() {
  const slots = scriptSlots([sentence(1), sentence(2)])
  if (slots.length !== 5) throw new Error('slots')
  if (slots[0].id !== 's1' || slots[1].id !== 's2') throw new Error('filled order')
  if (slots[2] !== null || slots[4] !== null) throw new Error('empty padding')
}

function testFallbackShape() {
  // What the UI stores when Gemini is off and Google Translate fills the lines.
  const buffer = appendFinal([], {
    id: 1,
    at: Date.now(),
    sinhala: 'ආයුබෝවන්',
    english: 'Hello',
    tamil: 'வணக்கம்',
  })
  if (buffer[0].english !== 'Hello' || buffer[0].tamil !== 'வணக்கம்') {
    throw new Error('fallback fields')
  }
}

const tests = [
  testKeepsFiveAndEvictsTheOldest,
  testIgnoresInterimEmptyAndKeepsReference,
  testSlotsAlwaysFive,
  testFallbackShape,
]
for (const test of tests) {
  test()
  console.log(`ok  ${test.name}`)
}
console.log(`${tests.length} passed`)
