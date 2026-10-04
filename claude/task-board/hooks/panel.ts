import type { Card, Detail, Details } from '../types'
import { base, byColumn } from './parse'

// The pane's groups, in board order. Ready, Backlog and columns the mod does not know fold into one line each.
export type Group = { key: string; label: string; cards: Card[]; folded: boolean }
const GROUPS: { key: string; label: string; columns: string[]; folded: boolean }[] = [
  { key: 'needs-you', label: '要対応', columns: ['Blocked', 'In review', 'wait for merge'], folded: false },
  { key: 'running', label: '実行中', columns: ['In progress'], folded: false },
  { key: 'ready', label: '待ち', columns: ['Ready'], folded: true },
  { key: 'backlog', label: 'Backlog', columns: ['Backlog'], folded: true },
]
export const groups = (cards: Card[]): Group[] => {
  const sorted = byColumn(cards)
  const known = GROUPS.flatMap(g => g.columns)
  return [
    ...GROUPS.map(g => ({ key: g.key, label: g.label, folded: g.folded,
      cards: sorted.filter(c => g.columns.includes(base(c.status))) })),
    { key: 'other', label: 'その他', folded: true, cards: sorted.filter(c => !known.includes(base(c.status))) },
  ].filter(g => g.cards.length > 0)
}

// Colors by column; a running card's stage (`In progress › review`) is its own small label.
export const STATUS_COLORS: Record<string, string> = {
  'Blocked': 'red', 'In review': 'yellow', 'wait for merge': 'green', 'In progress': 'cyan',
}
export const stage = (status: string): string => status.split(' › ')[1] ?? ''

// `jyoka/aica` -> `aica`, in a color fixed by the repo (a hash, so it never changes between refreshes or machines).
const TAG_COLORS = ['#c678dd', '#61afef', '#98c379', '#d19a66', '#56b6c2', '#ff79c6', '#a9a1e1', '#7ec699']
export const repoTag = (repo: string): { name: string; color: string } => {
  let h = 0
  for (const ch of repo) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0
  return { name: repo.split('/').pop() || repo, color: TAG_COLORS[h % TAG_COLORS.length] ?? TAG_COLORS[0]! }
}

// Terminal cells: CJK and fullwidth characters take two. Titles are cut to the pane by cells, not characters.
const wide = (cp: number): boolean =>
  (cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0xa4cf) || (cp >= 0xac00 && cp <= 0xd7a3)
  || (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe30 && cp <= 0xfe4f) || (cp >= 0xff00 && cp <= 0xff60)
  || (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x1f300 && cp <= 0x1faff) || (cp >= 0x20000 && cp <= 0x3fffd)
export const cells = (s: string): number => [...s].reduce((n, ch) => n + (wide(ch.codePointAt(0) ?? 0) ? 2 : 1), 0)
export const clip = (s: string, width: number): string => {
  if (cells(s) <= width) return s
  let out = ''
  let used = 0
  for (const ch of s) {
    const w = wide(ch.codePointAt(0) ?? 0) ? 2 : 1
    if (used + w > width - 1) break
    out += ch
    used += w
  }
  return out + '…'
}

// One JSON object per line; a line that is not one (cut off mid-write, hand-edited) is skipped.
const jsonLines = (text: string): Record<string, unknown>[] =>
  text.split('\n').flatMap(line => {
    try {
      const v: unknown = JSON.parse(line)
      return v !== null && typeof v === 'object' && !Array.isArray(v) ? [v as Record<string, unknown>] : []
    } catch { return [] }
  })
const str = (v: unknown): string => typeof v === 'string' ? v : ''

// What events.jsonl says about each card: when its last run started (its last `In progress`), the automated review's
// verdict and the PR of its last `In review`, and the reason of its last `Blocked`.
export type Seen = { started?: number; verdict?: string; pr?: string; reason?: string }
export const readEvents = (text: string): Record<string, Seen> => {
  const seen: Record<string, Seen> = {}
  for (const e of jsonLines(text)) {
    const id = str(e.id)
    if (id === '') continue
    const s = seen[id] ??= {}
    const digest = (e.digest !== null && typeof e.digest === 'object' ? e.digest : {}) as Record<string, unknown>
    if (e.event === 'In progress') {
      const t = Date.parse(str(e.time))
      if (!Number.isNaN(t)) s.started = t
    } else if (e.event === 'In review') {
      s.verdict = str(digest.verdict)
      s.pr = str(e.pr) || str(digest.pr)
    } else if (e.event === 'Blocked') {
      s.reason = str(e.reason) || str(digest.reason)
    }
  }
  return seen
}

// bin/task slow_threshold(agent): the usual time is the median (the upper one of an even count) of the agent's
// finished runs in metrics.jsonl, leaving out runs where the agent never ran (blocked_by start or setup), once there
// are SLOW_MIN_RUNS; a run counts as slow past max(SLOW_TIMES x usual, SLOW_FLOOR), or SLOW_DEFAULT with no usual.
export const SLOW_TIMES = 3
export const SLOW_FLOOR = 15 * 60
export const SLOW_DEFAULT = 30 * 60
export const SLOW_MIN_RUNS = 3
export type Threshold = { limit: number; usual: number | null }
export const slowThreshold = (metrics: string, agent: string): Threshold => {
  const seconds = jsonLines(metrics)
    .filter(r => r.agent === agent && r.blocked_by !== 'start' && r.blocked_by !== 'setup')
    .map(r => typeof r.seconds === 'number' && Number.isFinite(r.seconds) ? r.seconds : 0)
    .sort((x, y) => x - y)
  const usual = seconds.length >= SLOW_MIN_RUNS ? seconds[Math.floor(seconds.length / 2)] ?? null : null
  return { limit: usual === null ? SLOW_DEFAULT : Math.max(SLOW_TIMES * usual, SLOW_FLOOR), usual }
}

// config.ini `[runner] agent`, the agent of a card whose Agent field is empty (bin/task config(), default claude).
export const defaultAgent = (ini: string): string => {
  let section = ''
  let agent = 'claude'
  for (const raw of ini.split('\n')) {
    const line = raw.replace(/\s[;#].*$/, '').trim()
    if (line === '' || line.startsWith('#') || line.startsWith(';')) continue
    const head = line.match(/^\[(.+)\]$/)
    if (head) { section = head[1]!.trim(); continue }
    const kv = line.match(/^([^=:]+)[=:](.*)$/)
    if (section === 'runner' && kv && kv[1]!.trim().toLowerCase() === 'agent' && kv[2]!.trim() !== '') agent = kv[2]!.trim()
  }
  return agent
}

// Python's round(): half to even, so "usually 9 min" here reads as in bin/task's slow reason.
const roundHalfEven = (x: number): number => {
  const r = Math.round(x)
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r
}
export const minutes = (seconds: number): string => {
  const m = roundHalfEven(seconds / 60)
  return m < 60 ? `${m}分` : `${Math.floor(m / 60)}時間${m % 60 ? `${m % 60}分` : ''}`
}

// Everything the pane shows below the cards, from the two files; a missing or unreadable file shows nothing more.
export const details = (cards: Card[], events: string, metrics: string, ini: string, now: number): Details => {
  const seen = readEvents(events)
  const fallback = defaultAgent(ini)
  const out: Details = {}
  for (const c of cards) {
    const s = seen[c.id]
    if (!s) continue
    const d: Detail = {}
    const col = base(c.status)
    if (col === 'In progress' && s.started !== undefined) {
      const { limit, usual } = slowThreshold(metrics, c.agent || fallback)
      d.elapsed = Math.max(0, Math.floor((now - s.started) / 1000))
      d.usual = usual
      d.limit = limit
    }
    if (col === 'In review') {
      if (s.verdict) d.verdict = s.verdict
      if (s.pr) d.pr = s.pr
    }
    if (col === 'Blocked' && s.reason) d.reason = s.reason.split('\n').map(l => l.trim()).filter(l => l !== '').join(' ')
    if (Object.keys(d).length > 0) out[c.id] = d
  }
  return out
}

// "12分 / 普段9分": dim within the usual time, yellow past it, red once bin/task would call the run slow.
export const elapsedText = (d: Detail): { text: string; color?: string } | undefined => {
  if (d.elapsed === undefined) return undefined
  const text = d.usual == null ? `${minutes(d.elapsed)} / 普段 不明` : `${minutes(d.elapsed)} / 普段${minutes(d.usual)}`
  const color = d.limit !== undefined && d.elapsed >= d.limit ? 'red'
    : d.usual != null && d.elapsed > d.usual ? 'yellow' : undefined
  return { text, color }
}

export const verdictColor = (verdict: string): string | undefined =>
  verdict === 'pass' ? 'green' : verdict === 'needs changes' ? 'yellow' : undefined
export const prLabel = (url: string): string => {
  const n = url.match(/\/pull\/(\d+)/)?.[1]
  return n ? `PR #${n}` : 'PR'
}
