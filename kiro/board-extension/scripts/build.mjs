// Builds out/*.js, the CommonJS the extension host loads, from src/*.ts and the parse.ts and panel.ts shared with
// claude/task-board. No dependencies: Node strips the types, and the few import/export forms the sources use
// become require/exports. Anything else stops the build instead of being copied as it is.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const SOURCES = ['src/extension.ts', 'src/board.ts', '../../claude/task-board/hooks/parse.ts',
  '../../claude/task-board/hooks/panel.ts'].map(f => join(ROOT, f))

const out = file => `${basename(file, '.ts')}.js`

// A relative import must be one of SOURCES (all built side by side in out/); a bare one is left to require.
// The mod's sources leave out `.ts` (`./parse`), as Claude Code's loader allows.
const target = (spec, file) => {
  if (!spec.startsWith('.')) return spec
  const path = [resolve(dirname(file), spec), resolve(dirname(file), `${spec}.ts`)].find(p => SOURCES.includes(p))
  if (!path) throw new Error(`${file}: imports ${spec}, which is not in SOURCES`)
  return `./${out(path)}`
}

export const toCommonJS = (ts, file) => {
  const names = []
  const js = stripTypeScriptTypes(ts, { mode: 'strip' })
    .replace(/^import \* as (\w+) from '([^']+)'$/gm,
      (_, name, spec) => `const ${name} = require(${JSON.stringify(target(spec, file))})`)
    .replace(/^import \{([^}]*)\} from '([^']+)'$/gm,
      (_, list, spec) => `const {${list.replace(/\s+as\s+/g, ': ')}} = require(${JSON.stringify(target(spec, file))})`)
    .replace(/^export (const|function|async function|class) (\w+)/gm, (_, kind, name) => {
      names.push(name)
      return `${kind} ${name}`
    })
  const left = js.match(/^\s*(import|export)\b.*$/m)
  if (left) throw new Error(`${file}: the build does not handle: ${left[0].trim()}`)
  return `'use strict';${js}\n${names.map(n => `exports.${n} = ${n}`).join('\n')}\n`
}

export const build = (dir = join(ROOT, 'out')) => {
  rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  for (const file of SOURCES) writeFileSync(join(dir, out(file)), toCommonJS(readFileSync(file, 'utf8'), file))
  return dir
}

if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(`built ${build()}`)
