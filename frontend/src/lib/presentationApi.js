import { BACKEND_URL } from '../hooks/useBackendHealth'

const OFFLINE_MESSAGE =
  'The backend is not running, so .pptx files cannot be converted. Start the backend (PDF files load without it).'

export const backendUrl = (path) => (path ? `${BACKEND_URL}${path}` : null)

/**
 * Uploads a .pptx for server-side conversion. Returns { promise, abort }.
 * onProgress(phase, fraction): phase is 'uploading' then 'converting'.
 */
export function uploadPptx(file, onProgress) {
  const xhr = new XMLHttpRequest()
  const promise = new Promise((resolve, reject) => {
    xhr.open('POST', `${BACKEND_URL}/api/presentations?filename=${encodeURIComponent(file.name)}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress('uploading', e.loaded / e.total)
    }
    xhr.upload.onload = () => onProgress('converting', 1)
    xhr.onload = () => {
      let body = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new Error(body?.detail || `Conversion failed (HTTP ${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error(OFFLINE_MESSAGE))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    xhr.send(file)
  })
  return { promise, abort: () => xhr.abort() }
}

export async function fetchManifest(id) {
  const res = await fetch(`${BACKEND_URL}/api/presentations/${id}`)
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status })
  return res.json()
}

export function deletePresentation(id) {
  return fetch(`${BACKEND_URL}/api/presentations/${id}`, { method: 'DELETE' }).catch(() => {})
}
