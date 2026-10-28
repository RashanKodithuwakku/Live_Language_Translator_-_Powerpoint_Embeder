/**
 * Rolling window of finished captions.
 * Interim chunks never enter this list. A 6th final drops the oldest.
 */

export const SCRIPT_LIMIT = 5

export function appendFinal(buffer, entry) {
  const sinhala = (entry?.sinhala || '').trim()
  const english = (entry?.english || '').trim()
  const tamil = (entry?.tamil || '').trim()
  if (!sinhala && !english && !tamil) return buffer
  const item = {
    id: entry.id,
    at: entry.at,
    sinhala,
    english,
    tamil,
  }
  const next = buffer.length >= SCRIPT_LIMIT
    ? buffer.slice(buffer.length - SCRIPT_LIMIT + 1)
    : buffer.slice()
  next.push(item)
  return next
}

/** Always 5 slots. Empty slots stay at the bottom so the grid does not jump. */
export function scriptSlots(sentences, limit = SCRIPT_LIMIT) {
  const filled = sentences.slice(-limit)
  const slots = filled.slice()
  while (slots.length < limit) slots.push(null)
  return slots
}
