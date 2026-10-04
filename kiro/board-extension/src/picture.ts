// What the ship view (the Webview above the board) draws, and the achievements: both decided by the Claude Code
// mod's own code (hooks/ship.ts scene() and pixels(), hooks/badges.ts earned() and fresh()), so the extension
// draws the same scene and unlocks the same badges. No `vscode` here, so tests run it as is.
import type { Board } from '../../../claude/task-board/types'
import type { Figure } from '../../../claude/task-board/hooks/ship.ts'
import { BADGES, earned, fresh } from '../../../claude/task-board/hooks/badges.ts'
import { NONE, ROWS, TILT_WORDS, pixels, scene } from '../../../claude/task-board/hooks/ship.ts'

// The mod's limits on the picture's width, in its pixels (columns).
export const MIN_COLUMNS = 24
export const MAX_COLUMNS = 64
// One loop of the animation: every pose, wave and bob of pixels() repeats after 12 frames.
export const FRAMES = 12

// The picture as the Webview script paints it: `px` row-major, `rows` tall, a color 0xRRGGBB or -1 for see-through;
// each glyph one terminal cell (a column wide, two pixels tall); `spots` where a figure is, for its `#id title`.
export type Picture = {
  columns: number; rows: number; px: number[]
  glyphs: { x: number; y: number; ch: string; fg: number; bg: number }[]
  spots: { x: number; y: number; w: number; h: number; tip: string }[]
}
// Who is aboard, by #id, as the mod lists it under the picture (the picture may leave some out when narrow).
export type Aboard = { label: string; kind: 'crew' | 'cargo' | 'stuck' | 'pier'; after: string; figures: { id: string; tip: string }[] }
export type ShipState = {
  hidden: boolean
  // null while the board is loading or `task list` failed (the list below says why) or the ship is hidden
  picture: Picture | null
  aboard: Aboard[]
  empty: boolean
  badges: { name: string; desc: string }[]
  total: number
}

const color = (v: number): number => v === NONE ? -1 : v & 0xffffff
export const clampColumns = (n: number): number =>
  Number.isFinite(n) ? Math.max(MIN_COLUMNS, Math.min(MAX_COLUMNS, Math.floor(n))) : MIN_COLUMNS

export const picture = (board: Board, columns: number, frame: number): Picture => {
  const width = clampColumns(columns)
  const c = pixels(scene(board.cards), width, frame)
  return {
    columns: width, rows: ROWS * 2, px: Array.from(c.px, color),
    glyphs: c.glyphs.map(g => ({ x: g.x, y: g.y, ch: g.ch, fg: color(g.fg), bg: color(g.bg) })),
    spots: c.spots.map(p => ({ x: p.x, y: p.y, w: p.w, h: p.h, tip: `#${p.figure.id} ${p.figure.title}` })),
  }
}

// `unlocked`: the badge ids kept in globalState, shown in BADGES order.
export const shipState = (board: Board | null, columns: number, frame: number, hidden: boolean,
  unlocked: readonly string[]): ShipState => {
  const ok = board !== null && board.error === ''
  const s = scene(ok ? board.cards : [])
  const list = (label: string, kind: Aboard['kind'], figures: Figure[], after = ''): Aboard[] =>
    figures.length > 0 ? [{ label, kind, after, figures: figures.map(f => ({ id: f.id, tip: `#${f.id} ${f.title}` })) }] : []
  const got = BADGES.filter(b => unlocked.includes(b.id))
  return {
    hidden,
    picture: ok && !hidden ? picture(board, columns, frame) : null,
    aboard: ok && !hidden ? [...list('乗組員', 'crew', s.crew), ...list('荷', 'cargo', s.cargo, `(${TILT_WORDS[s.tilt]})`),
      ...list('SOS', 'stuck', s.stuck), ...list('桟橋', 'pier', s.pier)] : [],
    empty: ok && !hidden && s.crew.length + s.cargo.length + s.stuck.length + s.pier.length === 0,
    badges: got.map(b => ({ name: b.name, desc: b.desc })),
    total: BADGES.length,
  }
}

// The badges metrics.jsonl earns that `known` (globalState) does not hold yet: `all` to keep, and the one message
// for all of them, as the mod's toast. Nothing new: no message, `all` is `known`.
export const unlock = (metrics: string, known: readonly string[]): { all: string[]; message?: string } => {
  const { ids, toast } = fresh(earned(metrics), known)
  return { all: [...known, ...ids], message: toast }
}

const attr = (s: string): string => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')

// The ship view's page. The CSP lets in only the extension's own files (`source`, the webview's cspSource) and the
// one script tag carrying `nonce`: no CDN, which the company network may not reach, and no inline script or style.
export const shipHtml = (source: string, nonce: string, script: string, style: string): string => `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${attr(source)}; style-src ${attr(source)}; script-src 'nonce-${attr(nonce)}';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${attr(style)}">
</head>
<body>
<main id="main">
<div id="stage" hidden><canvas id="ship"></canvas><div id="tip" hidden></div></div>
<div id="aboard"></div>
<div id="badges"></div>
<button id="toggle" type="button">船を隠す</button>
</main>
<script nonce="${attr(nonce)}" src="${attr(script)}"></script>
</body>
</html>
`
