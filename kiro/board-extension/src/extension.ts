// The task-hub board in Kiro IDE (or VS Code): a view in its own activity bar container, and a status bar entry.
// No LLM: it runs `task list` (read only) every minute and shows what it printed.
import * as vscode from 'vscode'
import { execFile } from 'node:child_process'
import { homedir } from 'node:os'
import { delimiter, join } from 'node:path'

import type { Board } from '../../../claude/task-board/types'
import type { Outcome, Row } from './board.ts'
import { rows, statusBar, toBoard } from './board.ts'

const VIEW = 'taskHub.board'
const REFRESH = 'taskHub.board.refresh'
const EVERY_MS = 60_000
const TIMEOUT_MS = 60_000

// The one command this extension runs. Bare `task` would start Ready cards; `task list` starts nothing.
// An absolute path, since Kiro started from the Dock may not have the login shell's PATH.
export const taskPath = (): string => join(homedir(), '.local', 'bin', 'task')

// `task list` calls gh, which the installer puts in ~/.local/bin: add the usual places after the PATH Kiro has.
const childPath = (): string => {
  const have = (process.env.PATH ?? '').split(delimiter).filter(p => p !== '')
  const more = [join(homedir(), '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'].filter(p => !have.includes(p))
  return [...have, ...more].join(delimiter)
}

export type Run = () => Promise<Outcome | { reason: string }>

export const runTaskList: Run = () => new Promise(resolve => {
  const task = taskPath()
  execFile(task, ['list'], { timeout: TIMEOUT_MS, env: { ...process.env, PATH: childPath() } }, (err, stdout, stderr) => {
    if (!err) resolve({ exitCode: 0, stdout, stderr })
    else if (typeof err.code === 'number') resolve({ exitCode: err.code, stdout, stderr })
    else if (err.code === 'ENOENT') resolve({ reason: `${task} がありません` })
    else if (err.killed) resolve({ reason: `${TIMEOUT_MS / 1000} 秒で終わりませんでした` })
    else resolve({ reason: err.message.split('\n')[0] ?? '' })
  })
})

class BoardView implements vscode.TreeDataProvider<Row> {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  board: Board | null = null

  show(board: Board | null): void {
    this.board = board
    this.changed.fire()
  }

  getTreeItem(row: Row): vscode.TreeItem {
    const item = new vscode.TreeItem(row.label)
    item.description = row.description
    item.tooltip = row.tooltip || undefined
    item.iconPath = new vscode.ThemeIcon(row.icon)
    return item
  }

  getChildren(): Row[] {
    return rows(this.board)
  }

  dispose(): void {
    this.changed.dispose()
  }
}

// `run` is replaced in tests; Kiro calls activate(context) and gets the real `task list`.
export function activate(context: vscode.ExtensionContext, run: Run = runTaskList): void {
  const view = new BoardView()
  const tree = vscode.window.createTreeView(VIEW, { treeDataProvider: view })
  const bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  bar.command = `${VIEW}.focus`

  const show = (board: Board | null): void => {
    view.show(board)
    tree.description = board ? `${board.checkedAt} 時点` : ''
    const s = statusBar(board)
    bar.text = s.text
    bar.tooltip = s.tooltip
    bar.backgroundColor = s.warning ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined
  }

  // One run at a time: the refresh button during a run waits for that run.
  let running: Promise<void> | undefined
  const refresh = (): Promise<void> => running ??= Promise.resolve()
    .then(run)
    .catch((err: unknown) => ({ reason: String(err) }))
    .then(next => show(toBoard(next, new Date().toTimeString().slice(0, 5))))
    .finally(() => { running = undefined })

  show(null)
  bar.show()
  const timer = setInterval(() => void refresh(), EVERY_MS)
  context.subscriptions.push(view, tree, bar, vscode.commands.registerCommand(REFRESH, refresh),
    { dispose: () => clearInterval(timer) })
  void refresh()
}

export function deactivate(): void {}
