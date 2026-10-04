// What the view and the status bar show, from one run of `task list`. No `vscode` here, so tests run it as is.
import type { Board } from '../../../claude/task-board/types'
import { base, byColumn, failure, parseList, summary } from '../../../claude/task-board/hooks/parse.ts'

export type Outcome = { exitCode: number; stdout: string; stderr: string }
// One line of the view: a TreeItem's label, description, tooltip and codicon.
export type Row = { label: string; description: string; tooltip: string; icon: string }
export type Bar = { text: string; tooltip: string; warning: boolean }

const ICONS: Record<string, string> = {
  'Blocked': 'error', 'In review': 'eye', 'wait for merge': 'git-merge', 'In progress': 'sync', 'Ready': 'play',
  'Backlog': 'circle-outline',
}

const clip = (s: string, n: number): string => s.length > n ? s.slice(0, n - 1) + '…' : s

// A failed run (non-zero exit, output without the counts line, or `reason` when it could not run at all) is never
// an empty board.
export const toBoard = (run: Outcome | { reason: string }, checkedAt: string): Board =>
  'reason' in run ? { counts: {}, cards: [], checkedAt, error: run.reason }
  : run.exitCode !== 0 ? { counts: {}, cards: [], checkedAt, error: failure(run.exitCode, run.stdout, run.stderr) }
  : !/^counts:/m.test(run.stdout) ? { counts: {}, cards: [], checkedAt, error: 'task list の出力に counts: の行がありません' }
  : parseList(run.stdout, checkedAt)

export const rows = (board: Board | null): Row[] => {
  if (!board) return [{ label: '読み込み中...', description: '', tooltip: '', icon: 'loading~spin' }]
  if (board.error) {
    return [{ label: `読めませんでした: ${board.error}`, description: '', tooltip: `task list が失敗しました: ${board.error}`, icon: 'error' }]
  }
  if (board.cards.length === 0) {
    return [{ label: '開いているカードはありません。', description: '', tooltip: '', icon: 'check' }]
  }
  return byColumn(board.cards).map(c => {
    const waits = c.waitsFor !== '' ? `待ち: ${c.waitsFor}` : ''
    return {
      label: `#${c.id} ${c.title}`,
      description: [c.status, waits].filter(s => s !== '').join(' · '),
      tooltip: [`#${c.id} ${c.title}`, c.status, c.repo, waits].filter(s => s !== '').join('\n'),
      icon: ICONS[base(c.status)] ?? 'question',
    }
  })
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
