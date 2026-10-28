/**
 * Renders Script mode with five mock finals. No Gemini call.
 * Run from frontend/:  node scripts/render-script.mjs
 */

import { createRequire } from 'node:module'
import { rm } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const esbuild = require('esbuild')
const outfile = path.resolve('scripts/.render-script.mjs')

try {
  await esbuild.build({
    absWorkingDir: path.resolve('scripts'),
    entryPoints: ['render-entry.jsx'],
    bundle: true,
    format: 'esm',
    platform: 'node',
    packages: 'external',
    outfile,
    jsx: 'automatic',
    logLevel: 'silent',
  })
  await import(pathToFileURL(outfile).href)
} finally {
  await rm(outfile, { force: true })
}
