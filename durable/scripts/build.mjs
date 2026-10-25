// Builds dist/*.js, the ES modules `node durable/dist/cli.js` runs, from src/*.ts. No dependencies, as in
// kiro/board-extension: Node strips the types, and a relative import of `./x.ts` becomes `./x.js`.
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'src')
const DIST = join(ROOT, 'dist')

export const toModule = ts =>
  stripTypeScriptTypes(ts, { mode: 'strip' }).replace(/(from\s+|import\s*\(\s*)(["'])(\.{1,2}\/[^"']+)\.ts\2/g,
    (_, head, quote, path) => `${head}${quote}${path}.js${quote}`)

rmSync(DIST, { recursive: true, force: true })
mkdirSync(DIST, { recursive: true })
for (const file of readdirSync(SRC).filter(f => f.endsWith('.ts'))) {
  writeFileSync(join(DIST, file.replace(/\.ts$/, '.js')), toModule(readFileSync(join(SRC, file), 'utf8')))
}
console.log(`built ${DIST}`)
