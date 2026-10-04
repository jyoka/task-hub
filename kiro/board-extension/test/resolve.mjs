// `npm test` loads this first (--import). The mod's sources (claude/task-board/hooks/panel.ts) import `./parse`
// without the extension, as Claude Code's loader allows; Node does not, so a relative import that is not found is
// tried again with `.ts`. scripts/build.mjs resolves them the same way for out/.
import { registerHooks } from 'node:module'

registerHooks({
  resolve(spec, context, next) {
    try {
      return next(spec, context)
    } catch (err) {
      if (!spec.startsWith('.') || spec.endsWith('.ts') || err?.code !== 'ERR_MODULE_NOT_FOUND') throw err
      return next(`${spec}.ts`, context)
    }
  },
})
