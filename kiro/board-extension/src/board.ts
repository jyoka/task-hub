// What the view and the status bar show, from one run of `task list` and the files the mod reads too (events.jsonl,
// metrics.jsonl, config.ini). No `vscode` here, so tests run it as is.
import type { Board, Card, Detail, Details } from '../../../claude/task-board/types'
import { base, failure, parseList, summary } from '../../../claude/task-board/hooks/parse.ts'
import {
  STATUS_COLORS, details, elapsedText, groups, prLabel, repoTag, stage, verdictColor,
} from '../../../claude/task-board/hooks/panel.ts'

export type Outcome = { exitCode: number; stdout: string; stderr: string }
// The files besides `task list`; one that is missing or unreadable is ''.
export type Files = { events: string; metrics: string; ini: string }
// One node of the view, a TreeItem without `vscode`: `icon` a codicon ('' for none) and `color` a theme color id for
// it, `markdown` a tooltip in Markdown (else `tooltip` as text), `open` whether a node with children starts expanded,
// `link` the URL a click opens.
export type Node = {
  id: string; label: string; description: string; tooltip: string; markdown?: string; icon: string; color?: string
  children?: Node[]; open?: boolean; link?: string
}
export type Bar = { text: string; tooltip: string; warning: boolean }
export type Badge = { value: number; tooltip: string } | undefined

const ICONS: Record<string, string> = {
  'Blocked': 'error', 'In review': 'eye', 'wait for merge': 'git-merge', 'In progress': 'sync', 'Ready': 'play',
  'Backlog': 'circle-outline',
}
// The mod's colors (STATUS_COLORS, verdictColor) as theme colors, so the icons follow the theme.
const THEME: Record<string, string> = {
  red: 'charts.red', yellow: 'charts.yellow', green: 'charts.green', cyan: 'terminal.ansiCyan',
}
// A running card past its usual time (elapsedText yellow), and past the time bin/task calls slow (red).
const LATE: Record<string, string> = { yellow: 'list.warningForeground', red: 'list.errorForeground' }
const VERDICT_ICONS: Record<string, string> = { 'pass': 'pass', 'needs changes': 'request-changes' }
// Groups that start folded; the mod starts with the same ones (claude/task-board/hooks/panel.ts FOLDED).
const FOLDED = ['backlog', 'other']

const clip = (s: string, n: number): string => s.length > n ? s.slice(0, n - 1) + '…' : s
const md = (s: string): string => s.replace(/[\\`*_{}[\]()#+\-.!|<>~&]/g, '\\$&')
const http = (url: string): boolean => /^https?:\/\//.test(url)
// A URL as a Markdown link target: what would end it early, percent-encoded (encodeURIComponent keeps the parentheses).
const href = (url: string): string => url.replace(/[()<> ]/g, ch => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`)

// A failed run (non-zero exit, output without the counts line, or `reason` when it could not run at all) is never
// an empty board.
export const toBoard = (run: Outcome | { reason: string }, checkedAt: string): Board =>
  'reason' in run ? { counts: {}, cards: [], checkedAt, error: run.reason }
  : run.exitCode !== 0 ? { counts: {}, cards: [], checkedAt, error: failure(run.exitCode, run.stdout, run.stderr) }
  : !/^counts:/m.test(run.stdout) ? { counts: {}, cards: [], checkedAt, error: 'task list の出力に counts: の行がありません' }
  : parseList(run.stdout, checkedAt)

// Elapsed and usual time, verdict, PR and reason, read as the mod reads them (panel.ts details()).
export const detailsOf = (board: Board, files: Files, now: number): Details =>
  board.cards.length > 0 ? details(board.cards, files.events, files.metrics, files.ini, now) : {}

// One card: the repo tag, then a running card's stage and time, or the column in the needs-you group, then what it
// waits on. Under it, what to judge it by: the verdict or the reason, and the PR.
const cardNode = (c: Card, d: Detail, group: string): Node => {
  const col = base(c.status)
  const id = `card/${c.id}`
  const time = elapsedText(d)
  const label = group === 'running' ? stage(c.status) : group === 'ready' || group === 'backlog' ? '' : c.status
  const waits = c.waitsFor !== '' ? `待ち: ${c.waitsFor}` : ''
  const children: Node[] = []
  if (d.verdict) {
    const color = verdictColor(d.verdict)
    children.push({ id: `${id}/verdict`, label: `判定: ${d.verdict}`, description: '', tooltip: '自動レビューの判定',
      icon: VERDICT_ICONS[d.verdict] ?? 'comment', color: color && THEME[color] })
  }
  if (d.reason) {
    children.push({ id: `${id}/reason`, label: `理由: ${d.reason}`, description: '', tooltip: d.reason, icon: 'info' })
  }
  if (d.pr && http(d.pr)) {
    children.push({ id: `${id}/pr`, label: prLabel(d.pr), description: 'クリックで開く', tooltip: d.pr,
      icon: 'git-pull-request', link: d.pr })
  }
  const markdown = [
    `**#${c.id} ${md(c.title)}**`,
    md([c.status, c.repo, time?.text ?? '', waits].filter(s => s !== '').join(' · ')),
    d.verdict ? `判定: ${md(d.verdict)}` : '',
    d.reason ? `理由: ${md(d.reason)}` : '',
    d.pr && http(d.pr) ? `[${prLabel(d.pr)}](${href(d.pr)})` : '',
  ].filter(s => s !== '').join('\n\n')
  return {
    id, label: `#${c.id} ${c.title}`,
    description: [repoTag(c.repo).name, label, time?.text ?? '', waits].filter(s => s !== '').join(' · '),
    tooltip: '', markdown, icon: ICONS[col] ?? 'question',
    color: col === 'In progress' && time?.color ? LATE[time.color] : THEME[STATUS_COLORS[col] ?? ''],
    ...(children.length > 0 ? { children, open: true } : {}),
  }
}

const message = (label: string, icon: string, tooltip = ''): Node[] =>
  [{ id: 'message', label, description: '', tooltip, icon }]

// The groups of the mod's pane (要対応, 実行中, 待ち, Backlog, その他), each a node with its count; empty ones are left out.
export const tree = (board: Board | null, more: Details = {}): Node[] => {
  if (!board) return message('読み込み中...', 'loading~spin')
  if (board.error) return message(`読めませんでした: ${board.error}`, 'error', `task list が失敗しました: ${board.error}`)
  if (board.cards.length === 0) return message('開いているカードはありません。', 'check')
  return groups(board.cards).map(g => ({
    id: `group/${g.key}`, label: `${g.label} ${g.cards.length}`, description: '', tooltip: '', icon: '',
    children: g.cards.map(c => cardNode(c, more[c.id] ?? {}, g.key)), open: !FOLDED.includes(g.key),
  }))
}

// The activity bar badge: the cards in the needs-you group (Blocked, In review, wait for merge); none at 0.
export const badge = (board: Board | null): Badge => {
  const n = board && !board.error ? groups(board.cards).find(g => g.key === 'needs-you')?.cards.length ?? 0 : 0
  return n > 0 ? { value: n, tooltip: `要対応 ${n} 件` } : undefined
}

// summary() (shared with the Claude Code mod) names only the counts that are not 0.
export const statusBar = (board: Board | null): Bar => {
  if (!board) return { text: '$(checklist) task', tooltip: 'task-hub: 読み込み中', warning: false }
  const text = summary(board)
  if (board.error) {
    return { text: `$(warning) ${text} (${clip(board.error, 40)})`,
      tooltip: `task list が失敗しました (${board.checkedAt} 時点): ${board.error}`, warning: true }
  }
  return text
    ? { text: `$(checklist) ${text}`, tooltip: `task-hub のボード (${board.checkedAt} 時点)`, warning: false }
    : { text: '$(checklist) task', tooltip: `実行中、レビュー待ち、止まりのカードはありません (${board.checkedAt} 時点)`,
      warning: false }
}
