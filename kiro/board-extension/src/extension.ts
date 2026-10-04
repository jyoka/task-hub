// The task-hub board in Kiro IDE (or VS Code): a view in its own activity bar container, and a status bar entry.
// No LLM: it runs `task list` (read only) every minute and shows what it printed, with what task-hub's own files
// (events.jsonl, metrics.jsonl) say about the cards. Above the list, the Claude Code mod's ship and its badges.
import * as vscode from 'vscode'
import { execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { delimiter, join } from 'node:path'

import type { Board, Details } from '../../../claude/task-board/types'
import type { Files, Node, Outcome } from './board.ts'
import { badge, detailsOf, statusBar, toBoard, tree } from './board.ts'
import { FRAMES, shipHtml, shipState, unlock } from './picture.ts'

const VIEW = 'taskHub.board'
const REFRESH = 'taskHub.board.refresh'
const OPEN = 'taskHub.board.openPr'
const SHIP = 'taskHub.ship'
const EVERY_MS = 60_000
const TIMEOUT_MS = 60_000
// A few frames a second, as the mod's ship.
const FRAME_MS = 300
// What globalState keeps across windows: the ship hidden, and the ids of the badges unlocked (so each is told once).
const HIDDEN_KEY = 'taskHub.shipHidden'
const BADGES_KEY = 'taskHub.badges'

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

export type Read = () => Promise<Files>

// The same files the mod reads, with Node's fs. One that is missing or unreadable reads as empty: the cards still show.
const optional = (path: string): Promise<string> => readFile(path, 'utf8').catch(() => '')
export const readFiles: Read = async () => {
  const state = join(homedir(), '.local', 'state', 'task-hub')
  const [events, metrics, ini] = await Promise.all([
    optional(join(state, 'events.jsonl')),
    optional(join(state, 'metrics.jsonl')),
    optional(join(homedir(), '.config', 'task-hub', 'config.ini')),
  ])
  return { events, metrics, ini }
}

class BoardView implements vscode.TreeDataProvider<Node> {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  board: Board | null = null
  more: Details = {}

  show(board: Board | null, more: Details): void {
    this.board = board
    this.more = more
    this.changed.fire()
  }

  getTreeItem(node: Node): vscode.TreeItem {
    const item = new vscode.TreeItem(node.label, !node.children ? vscode.TreeItemCollapsibleState.None
      : node.open ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed)
    item.id = node.id
    item.description = node.description
    item.tooltip = node.markdown !== undefined ? new vscode.MarkdownString(node.markdown) : node.tooltip || undefined
    if (node.icon !== '') {
      item.iconPath = new vscode.ThemeIcon(node.icon, node.color ? new vscode.ThemeColor(node.color) : undefined)
    }
    if (node.link) item.command = { command: OPEN, title: 'PR を開く', arguments: [node.link] }
    return item
  }

  getChildren(node?: Node): Node[] {
    return node ? node.children ?? [] : tree(this.board, this.more)
  }

  dispose(): void {
    this.changed.dispose()
  }
}

const strings = (v: unknown): string[] => Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

// The ship: a Webview whose bundled script (media/ship.js) paints what shipState() gives it, posted by the extension
// frame by frame. While the view is not visible nothing is drawn or posted; when it shows again, it gets the latest.
class ShipView implements vscode.WebviewViewProvider {
  private readonly context: vscode.ExtensionContext
  private view: vscode.WebviewView | undefined
  private board: Board | null = null
  private columns = 0 // the script tells how wide the view is before anything is drawn
  private frame = 0

  constructor(context: vscode.ExtensionContext) {
    this.context = context
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view
    const media = vscode.Uri.joinPath(this.context.extensionUri, 'media')
    const uri = (file: string): string => view.webview.asWebviewUri(vscode.Uri.joinPath(media, file)).toString()
    view.webview.options = { enableScripts: true, localResourceRoots: [media] }
    view.webview.html = shipHtml(view.webview.cspSource, randomBytes(16).toString('hex'), uri('ship.js'), uri('ship.css'))
    const subs = [
      view.webview.onDidReceiveMessage((m: unknown) => this.receive(m)),
      view.onDidChangeVisibility(() => this.post()),
    ]
    view.onDidDispose(() => {
      for (const d of subs) d.dispose()
      if (this.view === view) this.view = undefined
    })
  }

  // From the script: {type: 'size', columns} when it loads and when the view is resized, {type: 'toggle'} on the button.
  private receive(m: unknown): void {
    if (typeof m !== 'object' || m === null) return
    const { type, columns } = m as { type?: unknown; columns?: unknown }
    if (type === 'size' && typeof columns === 'number') {
      this.columns = columns
      this.post()
    } else if (type === 'toggle') {
      void this.toggle()
    }
  }

  get hidden(): boolean {
    return this.context.globalState.get(HIDDEN_KEY) === true
  }

  async toggle(): Promise<void> {
    try { await this.context.globalState.update(HIDDEN_KEY, !this.hidden) } catch { return }
    this.post()
  }

  show(board: Board | null): void {
    this.board = board
    this.post()
  }

  private post(): void {
    if (!this.view?.visible || this.columns === 0) return
    const state = shipState(this.board, this.columns, this.frame, this.hidden,
      strings(this.context.globalState.get(BADGES_KEY)))
    this.view.webview.postMessage(state).then(undefined, () => {})
  }

  // The next frame, only when there is a ship to see.
  tick(): void {
    if (!this.view?.visible || this.columns === 0 || this.hidden || !this.board || this.board.error !== '') return
    this.frame = (this.frame + 1) % FRAMES
    this.post()
  }
}

// `run` and `read` are replaced in tests; Kiro calls activate(context) and gets the real `task list` and files.
export function activate(context: vscode.ExtensionContext, run: Run = runTaskList, read: Read = readFiles): void {
  const provider = new BoardView()
  const view = vscode.window.createTreeView(VIEW, { treeDataProvider: provider })
  const ship = new ShipView(context)
  const bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  bar.command = `${VIEW}.focus`

  // The status bar entry is always shown (bar.show() below); its text names Blocked as 止まりN whenever the counts
  // line has Blocked=N with N > 0 (summary() in parse.ts).
  const show = (board: Board | null, more: Details = {}): void => {
    provider.show(board, more)
    ship.show(board)
    view.description = board ? `${board.checkedAt} 時点` : ''
    view.badge = badge(board)
    const s = statusBar(board)
    bar.text = s.text
    bar.tooltip = s.tooltip
    bar.backgroundColor = s.warning ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined
  }

  // Achievements, as the mod judges them (metrics.jsonl alone): the new ones are kept in globalState first, then told
  // once. Runs are one at a time (below), so two never tell the same badge. A badge that cannot be kept is not told.
  const judge = async (metrics: string): Promise<void> => {
    const { all, message } = unlock(metrics, strings(context.globalState.get(BADGES_KEY)))
    if (!message) return
    try { await context.globalState.update(BADGES_KEY, all) } catch { return }
    void vscode.window.showInformationMessage(message)
  }

  // One run at a time: the refresh button during a run waits for that run.
  let running: Promise<void> | undefined
  const refresh = (): Promise<void> => running ??= Promise.resolve()
    .then(run)
    .catch((err: unknown) => ({ reason: String(err) }))
    .then(async next => {
      const now = Date.now()
      const board = toBoard(next, new Date(now).toTimeString().slice(0, 5))
      const files = await Promise.resolve().then(read).catch(() => ({ events: '', metrics: '', ini: '' }))
      let more: Details = {}
      try { more = detailsOf(board, files, now) } catch { /* the cards show without the details */ }
      await judge(files.metrics).catch(() => {})
      show(board, more)
    })
    .finally(() => { running = undefined })

  show(null)
  bar.show()
  const timer = setInterval(() => void refresh(), EVERY_MS)
  const frames = setInterval(() => ship.tick(), FRAME_MS)
  context.subscriptions.push(provider, view, bar, vscode.commands.registerCommand(REFRESH, refresh),
    vscode.commands.registerCommand(OPEN, (url: string) => vscode.env.openExternal(vscode.Uri.parse(url))),
    vscode.window.registerWebviewViewProvider(SHIP, ship),
    { dispose: () => { clearInterval(timer); clearInterval(frames) } })
  void refresh()
}

export function deactivate(): void {}
