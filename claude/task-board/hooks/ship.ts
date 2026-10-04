import type { Card } from '../types'
import { base, byColumn } from './parse'
import { stage } from './panel'

// The ship above the list: the human is the captain, the agents the crew.
// A running card is a crew member, In review and wait for merge are crates on deck (the more, the more she lists),
// a Blocked card sits on deck with a "?" under an SOS flag, and a Ready card waits on the pier.
export type Pose = 'work' | 'review' | 'retry' | 'idle'
export type Figure = { id: string; title: string; pose?: Pose }
export type Tilt = 0 | 1 | 2
export type Scene = { crew: Figure[]; cargo: Figure[]; stuck: Figure[]; pier: Figure[]; tilt: Tilt; sos: boolean }

// The stage of a running card (bin/task set_stage): the agent at work, the automated review, the agent's retry.
export const pose = (status: string): Pose => {
  const s = stage(status)
  return s === 'agent' ? 'work' : s === 'review' ? 'review' : s === 'retry' ? 'retry' : 'idle'
}
// 0-1 crates sail level, 2-3 list a little, 4 or more list hard.
export const tiltFor = (crates: number): Tilt => crates <= 1 ? 0 : crates <= 3 ? 1 : 2

export const scene = (cards: Card[]): Scene => {
  const sorted = byColumn(cards)
  const fig = (c: Card): Figure => ({ id: c.id, title: c.title })
  const crew = sorted.filter(c => base(c.status) === 'In progress').map(c => ({ ...fig(c), pose: pose(c.status) }))
  const cargo = sorted.filter(c => ['In review', 'wait for merge'].includes(base(c.status))).map(fig)
  const stuck = sorted.filter(c => base(c.status) === 'Blocked').map(fig)
  const pier = sorted.filter(c => base(c.status) === 'Ready').map(fig)
  return { crew, cargo, stuck, pier, tilt: tiltFor(cargo.length), sos: stuck.length > 0 }
}

export const TILT_WORDS = ['まっすぐ', '少し傾いている', '大きく傾いている'] as const

// ---- Terminal: a Raster of half-block pixels, two pixels to a cell (the top one the glyph's, the bottom the cell's).

export const ROWS = 10
const H = ROWS * 2
export const NONE = 0x01000000 // the terminal's default color: a see-through pixel
const C = {
  sea: 0x1f6feb, deep: 0x174ea6, crest: 0x9ecbff, hull: 0x8b5a2b, keel: 0x5c3a1a, deck: 0xc08a4a,
  mast: 0x6b4423, sail: 0xf0f0e8, skin: 0xf2c79b, legs: 0x30363d, crew: 0x56b6c2, stuck: 0xe5534b,
  waiting: 0x9aa0a6, steel: 0xb0b0b0, lens: 0x79c0ff, sweat: 0x79c0ff, crate: 0xd19a66, edge: 0x8a5a2b,
  pier: 0xa0703c, flag: 0xda3633, white: 0xffffff, question: 0xf2cc60,
}
const SEA_Y = 16 // the water line, in pixels
const DECK_Y = 12

// `at`: the column the glyph lists with, so the letters of one flag keep to one row
export type Glyph = { x: number; y: number; ch: string; fg: number; bg: number; at?: number }
// Where a figure is drawn, in pixels, for surfaces that show `#id title` under the pointer (the Kiro extension)
export type Spot = { x: number; y: number; w: number; h: number; figure: Figure }
// `w` is set in the constructor, not as a parameter property: Node's type stripping (the Kiro extension's build) has none
class Canvas {
  readonly w: number
  px: Uint32Array
  glyphs: Glyph[] = []
  spots: Spot[] = []
  constructor(w: number) {
    this.w = w
    this.px = new Uint32Array(w * H).fill(NONE)
  }
  set(x: number, y: number, color: number) {
    if (x >= 0 && x < this.w && y >= 0 && y < H) this.px[y * this.w + x] = color
  }
  get(x: number, y: number): number { return x >= 0 && x < this.w && y >= 0 && y < H ? this.px[y * this.w + x]! : NONE }
  rect(x: number, y: number, w: number, h: number, color: number) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.set(x + i, y + j, color)
  }
}

// How much of the scene fits `columns`: the pier's figures go first, then crates, then crew; the caption lists all.
type Fit = { pier: number; stuck: number; crew: number; cargo: number }
const SHIP_MIN = 14
const pierWidth = (n: number) => n > 0 ? 2 + 3 * n : 0
const shipWidth = (f: Fit) => Math.max(SHIP_MIN, 2 + 1 + 4 * f.stuck + 4 * f.crew + 4 + 3 * Math.ceil(f.cargo / 2) + 1)
export const fit = (s: Scene, columns: number): Fit => {
  const f: Fit = { pier: Math.min(s.pier.length, 3), stuck: Math.min(s.stuck.length, 2),
    crew: Math.min(s.crew.length, 5), cargo: Math.min(s.cargo.length, 8) }
  const need = () => pierWidth(f.pier) + 1 + shipWidth(f) + 1
  while (need() > columns && f.pier > 0) f.pier--
  while (need() > columns && f.cargo > 2) f.cargo--
  while (need() > columns && f.crew > 1) f.crew--
  while (need() > columns && f.stuck > 1) f.stuck--
  return f
}

// One figure two pixels wide and four tall, standing on `feet`; `sit` is one shorter, legs out in front.
const person = (c: Canvas, x: number, feet: number, shirt: number, sit = false) => {
  if (sit) {
    c.rect(x, feet - 2, 2, 1, C.skin)
    c.rect(x, feet - 1, 2, 1, shirt)
    c.rect(x, feet, 3, 1, C.legs)
    return
  }
  c.rect(x, feet - 3, 2, 1, C.skin)
  c.rect(x, feet - 2, 2, 2, shirt)
  c.set(x, feet, C.legs)
  c.set(x + 1, feet, C.legs)
}

// The ship, upright, with what is on deck; `frame` moves hands, the sweat drop and the waves.
const drawShip = (c: Canvas, s: Scene, f: Fit, x0: number, frame: number) => {
  const w = shipWidth(f)
  // the hull: a deck rail, then a keel narrowing to the water
  for (let i = 0; i < w; i++) c.set(x0 + i, DECK_Y, C.deck)
  for (let j = 1; j <= 4; j++) for (let i = j - 1; i < w - (j - 1); i++) c.set(x0 + i, DECK_Y + j, j === 4 ? C.keel : C.hull)
  const feet = DECK_Y - 1
  let x = x0 + 2
  for (let k = 0; k < f.stuck; k++, x += 4) {
    person(c, x, feet, C.stuck, true)
    c.spots.push({ x, y: feet - 4, w: 3, h: 5, figure: s.stuck[k]! })
    c.glyphs.push({ x, y: feet - 4, ch: '?', fg: C.question, bg: NONE })
  }
  for (let k = 0; k < f.crew; k++, x += 4) {
    const p = s.crew[k]!.pose ?? 'idle'
    person(c, x, feet, C.crew)
    c.spots.push({ x, y: feet - 4, w: 3, h: 5, figure: s.crew[k]! })
    const up = frame % 2 === 0
    if (p === 'work') { c.set(x + 2, feet - (up ? 3 : 2), C.steel); c.set(x + 2, feet - (up ? 2 : 1), C.mast) }
    if (p === 'review') { c.set(x + 2, feet - 3 + (frame % 4 === 3 ? 1 : 0), C.lens); c.set(x + 2, feet - 1, C.mast) }
    if (p === 'retry' && frame % 3 !== 2) c.set(x + 2, feet - 4, C.sweat)
  }
  // the mast and its sail, and the SOS flag at its top while a card is Blocked
  const mast = x + 1
  for (let y = 1; y <= feet; y++) c.set(mast, y, C.mast)
  for (let y = 2; y <= 7; y++) for (let i = 1; i <= Math.min(5, y - 1); i++) c.set(mast + i, y, C.sail)
  if (s.sos) ['S', 'O', 'S'].forEach((ch, i) => c.glyphs.push({ x: mast - 3 + i, y: 0, ch, fg: C.white, bg: C.flag, at: mast }))
  // the crates, two to a stack, astern
  x += 4
  for (let k = 0; k < f.cargo; k++) {
    const cx = x + 3 * Math.floor(k / 2)
    const cy = k % 2 === 0 ? feet - 1 : feet - 3
    c.rect(cx, cy, 2, 2, C.crate)
    c.set(cx + 1, cy + 1, C.edge)
    c.spots.push({ x: cx, y: cy, w: 2, h: 2, figure: s.cargo[k]! })
  }
}

// Lists the ship's layer about its middle, column by column (a shear keeps the pixels whole): astern down, as the
// crates weigh there, so the stern sinks into the water and the bow lifts out of it.
const SLOPES = [0, 1 / 8, 1 / 4]
const list = (layer: Canvas, tilt: Tilt, cx: number): Canvas => {
  if (tilt === 0) return layer
  const out = new Canvas(layer.w)
  const shift = (x: number) => Math.round((x - cx) * SLOPES[tilt]!)
  for (let y = 0; y < H; y++) for (let x = 0; x < layer.w; x++) {
    const v = layer.get(x, y)
    if (v !== NONE) out.set(x, y + shift(x), v)
  }
  out.glyphs = layer.glyphs.map(g => ({ ...g, y: g.y + shift(g.at ?? g.x) }))
  // a spot's columns shift by different amounts: it grows to hold all of them
  out.spots = layer.spots.map(p => {
    const [a, b] = [shift(p.x), shift(p.x + p.w - 1)]
    return { ...p, y: p.y + Math.min(a, b), h: p.h + Math.abs(b - a) }
  })
  return out
}

// The whole picture as a Raster's `cells`: `columns` wide, ROWS tall.
export const pixels = (s: Scene, columns: number, frame: number): Canvas => {
  const f = fit(s, columns)
  const c = new Canvas(columns)
  const pw = pierWidth(f.pier)
  const shipX = pw + 1
  const layer = new Canvas(columns)
  drawShip(layer, s, f, shipX, frame)
  const bob = Math.floor(frame / 2) % 2
  const turned = list(layer, s.tilt, shipX + shipWidth(f) / 2)
  for (let y = 0; y < H; y++) for (let x = 0; x < columns; x++) {
    const v = turned.get(x, y - bob)
    if (v !== NONE) c.set(x, y, v)
  }
  // the bow lifts the SOS flag above the picture as she lists hard: it stays on the top row instead
  c.glyphs = turned.glyphs.map(g => ({ ...g, y: Math.max(0, g.y + bob) }))
  c.spots = turned.spots.map(p => ({ ...p, y: p.y + bob }))
  // the pier and who waits on it
  if (pw > 0) {
    for (let i = 0; i < pw; i++) c.set(i, SEA_Y - 1, C.pier)
    for (let k = 0; k < f.pier; k++) {
      person(c, 1 + 3 * k, SEA_Y - 2, C.waiting)
      c.spots.push({ x: 1 + 3 * k, y: SEA_Y - 5, w: 2, h: 4, figure: s.pier[k]! })
    }
  }
  // the sea over the bottom of the hull, its crests drifting with the frame
  for (let y = SEA_Y; y < H; y++) for (let x = 0; x < columns; x++) {
    c.set(x, y, y === SEA_Y && (x + frame) % 6 === 0 ? C.crest : y >= SEA_Y + 2 ? C.deep : C.sea)
  }
  if (pw > 0) for (let y = SEA_Y; y < H; y++) { c.set(0, y, C.mast); c.set(pw - 1, y, C.mast) }
  return c
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
export const base64 = (bytes: Uint8Array): string => {
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i]! << 16) | ((bytes[i + 1] ?? 0) << 8) | (bytes[i + 2] ?? 0)
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]!
      + (i + 1 < bytes.length ? B64[(n >> 6) & 63]! : '=') + (i + 2 < bytes.length ? B64[n & 63]! : '=')
  }
  return out
}

// RasterProps.cells: per cell [codePoint, foreground, background] as little-endian u32s, row-major, base64.
export const cells = (s: Scene, columns: number, frame: number): string => {
  const c = pixels(s, columns, frame)
  const view = new DataView(new ArrayBuffer(columns * ROWS * 12))
  const put = (i: number, cp: number, fg: number, bg: number) => {
    view.setUint32(i * 12, cp, true)
    view.setUint32(i * 12 + 4, fg, true)
    view.setUint32(i * 12 + 8, bg, true)
  }
  for (let r = 0; r < ROWS; r++) for (let x = 0; x < columns; x++) {
    const top = c.get(x, 2 * r)
    const bottom = c.get(x, 2 * r + 1)
    const i = r * columns + x
    if (top === NONE && bottom === NONE) put(i, 0x20, NONE, NONE)
    else if (top === NONE) put(i, 0x2584, bottom, NONE) // ▄
    else put(i, 0x2580, top, bottom) // ▀
  }
  for (const g of c.glyphs) {
    const r = Math.floor(g.y / 2)
    if (g.x >= 0 && g.x < columns && r >= 0 && r < ROWS) put(r * columns + g.x, g.ch.codePointAt(0)!, g.fg, g.bg)
  }
  return base64(new Uint8Array(view.buffer))
}

// ---- Other surfaces: the same scene in characters, one column of four lines per thing on deck, the columns
// stepping down astern as she lists.

export type Column = { lines: [string, string, string]; hull: string; figure?: Figure; kind: 'stuck' | 'crew' | 'cargo' | 'mast' | 'end' }
const TOOLS: Record<Pose, string> = { work: '🔨', review: '🔍', retry: '💦', idle: '  ' }
export const deck = (s: Scene): Column[] => {
  const blank = '  '
  return [
    { kind: 'end', lines: [blank, blank, blank], hull: '◥' },
    ...s.stuck.map((f): Column => ({ kind: 'stuck', figure: f, lines: [blank, '❓', '🙇'], hull: '▀▀' })),
    ...s.crew.map((f): Column => ({ kind: 'crew', figure: f, lines: [blank, TOOLS[f.pose ?? 'idle'], '👷'], hull: '▀▀' })),
    { kind: 'mast', lines: [s.sos ? '🆘' : '⛵', '┃', '┃'], hull: '▀▀' },
    ...s.cargo.map((f): Column => ({ kind: 'cargo', figure: f, lines: [blank, blank, '📦'], hull: '▀▀' })),
    { kind: 'end', lines: [blank, blank, blank], hull: '◤' },
  ]
}
// How many lines column `i` of `n` sits lower than the bow.
export const drop = (tilt: Tilt, i: number, n: number): number => n <= 1 ? 0 : Math.round((tilt * i) / (n - 1))
