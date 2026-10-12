// The Goal, Changes and Log of one card, in the editor's own read-only tabs: a Markdown document, the diff editor,
// and a text document that follows the log. Each tab's URI carries the task id (/<id>/...), so a tab keeps showing
// its own task whatever is picked on the board afterwards. src/inspect.ts reads the files and runs git.
import * as vscode from 'vscode'
import { unwatchFile, watchFile } from 'node:fs'

import type { Card } from '../../../claude/task-board/types'
import type { Change, Changes } from './inspect.ts'
import { goalText, logPathOf, readChanges, readGoal, readLog, readRun, readSide, validId } from './inspect.ts'

export const GOAL_SCHEME = 'taskhub-goal'
export const DIFF_SCHEME = 'taskhub-diff'
export const LOG_SCHEME = 'taskhub-log'
const FOLLOWING = 'taskHub.logFollowing'
// How often an open log tab looks at its file (fs.watchFile polls: one stat a second, only while the tab is open).
const LOG_POLL_MS = 1000

const idOf = (uri: vscode.Uri): string => uri.path.split('/')[1] ?? ''
const short = (repo: string): string => repo.split('/').pop() || repo
const titled = (id: string, view: string, repo: string): string => `#${id} ${view}${repo ? ` · ${short(repo)}` : ''}`

// The Issue body as board-cache.json has it, read again each time the Goal command opens the tab. A tab already open
// keeps its text when the card later leaves the cache; the command then says why it cannot read it again.
class GoalDocs implements vscode.TextDocumentContentProvider {
  readonly changed = new vscode.EventEmitter<vscode.Uri>()
  readonly onDidChange = this.changed.event

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const id = idOf(uri)
    if (!validId(id)) return '(task-hub: タスクの番号ではありません)\n'
    const g = await readGoal(id)
    return g.found ? goalText(id, g, Date.now()) : `(task-hub: ${g.reason})\n`
  }

  dispose(): void {
    this.changed.dispose()
  }
}

// Both sides of a file's diff: /<id>/base/<path>?<fork> and /<id>/worktree/<path>?<fork>, read when the tab opens.
class DiffDocs implements vscode.TextDocumentContentProvider {
  readonly changed = new vscode.EventEmitter<vscode.Uri>()
  readonly onDidChange = this.changed.event

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    // a diff tab restored in a window that is not trusted: git does not run there
    if (!vscode.workspace.isTrusted) return '(task-hub: 信頼していないワークスペースでは git を動かさないので、出しません)\n'
    const [, id = '', side = '', ...path] = uri.path.split('/')
    return readSide(id, side, path.join('/'), uri.query)
  }

  dispose(): void {
    this.changed.dispose()
  }
}

// shown: a tab has shown it (until then, no tab for it is not a closed tab)
type Watched = { path: string; following: boolean; listener: () => void; shown: boolean }

// A log tab reads the file again when it changes, while it follows. Paused, the tab keeps what it shows, so the
// reader's place never moves; following again reads the file and goes to the end.
class LogDocs implements vscode.TextDocumentContentProvider {
  readonly changed = new vscode.EventEmitter<vscode.Uri>()
  readonly onDidChange = this.changed.event
  readonly open = new Map<string, Watched>()
  closed = false

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const id = idOf(uri)
    if (!validId(id)) return '(task-hub: タスクの番号ではありません)\n'
    return readLog(id, this.open.get(uri.toString())?.path ?? await logPathOf(id))
  }

  watch(uri: vscode.Uri, path: string): Watched {
    const key = uri.toString()
    const have = this.open.get(key)
    if (have) return have
    const w: Watched = { path, following: true, shown: false, listener: () => { if (w.following) this.changed.fire(uri) } }
    watchFile(path, { interval: LOG_POLL_MS, persistent: false }, w.listener)
    this.open.set(key, w)
    return w
  }

  close(key: string): void {
    const w = this.open.get(key)
    if (!w) return
    unwatchFile(w.path, w.listener)
    this.open.delete(key)
  }

  dispose(): void {
    this.closed = true
    for (const w of this.open.values()) unwatchFile(w.path, w.listener)
    this.open.clear()
    this.changed.dispose()
  }
}

const STATUS_TEXT: Record<Change['status'], string> = {
  added: '追加', deleted: '削除', modified: '変更', type: '種類の変更', untracked: '未追跡(まだコミットされていない新しいファイル)',
}

type Pick = vscode.QuickPickItem & { change?: Change }

// The card a command is for: a card of the board view (its node), an id, or (from the command palette) one picked.
type Target = { id: string; repo: string; title: string }
const resolve = async (arg: unknown, cards: () => Card[]): Promise<Target | undefined> => {
  const fromId = async (id: string): Promise<Target | undefined> => {
    if (!validId(id)) {
      void vscode.window.showWarningMessage(`タスクの番号ではありません: ${id}`)
      return undefined
    }
    const card = cards().find(c => c.id === id)
    const run = card ? null : await readRun(id)
    return { id, repo: card?.repo ?? run?.repo ?? '', title: card?.title ?? run?.title ?? '' }
  }
  if (typeof arg === 'string') return fromId(arg)
  const node = (arg as { task?: unknown } | undefined)?.task
  if (typeof node === 'string') return fromId(node)
  const all = cards()
  if (all.length > 0) {
    const picked = await vscode.window.showQuickPick(all.map(c => ({ label: `#${c.id} ${c.title}`,
      description: [short(c.repo), c.status].filter(s => s).join(' · '), id: c.id })), { placeHolder: 'どのタスク?' })
    return picked ? fromId(picked.id) : undefined
  }
  const typed = await vscode.window.showInputBox({ prompt: 'ボードがまだ読めていません。タスクの番号', validateInput:
    v => validId(v.trim()) ? undefined : '数字で' })
  return typed ? fromId(typed.trim()) : undefined
}

// Registers the providers and the commands taskHub.task.goal / changes / log, taskHub.log.follow / pause.
// `cards` gives the board's cards as last read.
export const registerTabs = (context: vscode.ExtensionContext, cards: () => Card[]): void => {
  const goals = new GoalDocs()
  const diffs = new DiffDocs()
  const logs = new LogDocs()
  let picker: vscode.QuickPick<Pick> | undefined
  let asked = 0 // the last Changes command: an earlier one that finishes later shows nothing

  const following = (uri: vscode.Uri | undefined): boolean =>
    uri?.scheme === LOG_SCHEME && logs.open.get(uri.toString())?.following === true
  const showFollowing = (): void => {
    void vscode.commands.executeCommand('setContext', FOLLOWING, following(vscode.window.activeTextEditor?.document.uri))
  }
  // Scrolls each visible editor of the log to its last line; the focus stays where it is.
  const toEnd = (uri: vscode.Uri): void => {
    for (const ed of vscode.window.visibleTextEditors) {
      if (ed.document.uri.toString() !== uri.toString()) continue
      const last = Math.max(0, ed.document.lineCount - 1)
      ed.revealRange(new vscode.Range(last, 0, last, 0), vscode.TextEditorRevealType.Default)
    }
  }
  const logUri = (arg: unknown): vscode.Uri | undefined => {
    const uri = arg instanceof Object && (arg as vscode.Uri).scheme === LOG_SCHEME ? arg as vscode.Uri
      : vscode.window.activeTextEditor?.document.uri
    return uri?.scheme === LOG_SCHEME ? uri : undefined
  }

  // A log tab that came back without the Log command (Reopen Closed Editor, a window that restores its tabs) is
  // looked at again, following, as the Log command opens it.
  const adopt = async (uri: vscode.Uri): Promise<Watched | undefined> => {
    const id = idOf(uri)
    if (!validId(id)) return undefined
    const have = logs.open.get(uri.toString())
    if (have) return have
    const path = await logPathOf(id)
    const again = logs.open.get(uri.toString()) // the Log command, meanwhile
    if (again || logs.closed) return again
    const w = logs.watch(uri, path)
    w.shown = true
    logs.changed.fire(uri)
    toEnd(uri)
    showFollowing()
    return w
  }
  const tabUris = (): string[] => vscode.window.tabGroups.all.flatMap(g => g.tabs)
    .map(t => t.input instanceof vscode.TabInputText ? t.input.uri.toString() : '')
  const adoptTabs = async (): Promise<void> => {
    for (const t of vscode.window.tabGroups.all.flatMap(g => g.tabs)) {
      const uri = t.input instanceof vscode.TabInputText ? t.input.uri : undefined
      if (uri?.scheme === LOG_SCHEME && !logs.open.has(uri.toString())) await adopt(uri)
    }
  }

  const openGoal = async (arg: unknown): Promise<void> => {
    const t = await resolve(arg, cards)
    if (!t) return
    const g = await readGoal(t.id)
    if (!g.found) {
      void vscode.window.showWarningMessage(g.reason)
      return
    }
    const uri = vscode.Uri.from({ scheme: GOAL_SCHEME, path: `/${t.id}/${titled(t.id, 'Goal', g.repo || t.repo)}.md` })
    goals.changed.fire(uri) // an open tab reads the cache again
    let doc = await vscode.workspace.openTextDocument(uri)
    if (doc.languageId !== 'markdown') doc = await vscode.languages.setTextDocumentLanguage(doc, 'markdown')
    await vscode.window.showTextDocument(doc, { preview: false })
  }

  const openDiff = async (id: string, c: Changes, f: Change): Promise<void> => {
    const side = (s: string): vscode.Uri => vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${id}/${s}/${f.path}`, query: c.fork })
    const [left, right] = [side('base'), side('worktree')]
    diffs.changed.fire(left) // an open tab reads the worktree again
    diffs.changed.fire(right)
    await vscode.commands.executeCommand('vscode.diff', left, right,
      `${titled(id, f.path, c.repo)} (${c.baseRef} ↔ 作業中)`, { preview: true, preserveFocus: true })
  }

  const openChanges = async (arg: unknown): Promise<void> => {
    const t = await resolve(arg, cards)
    if (!t) return
    if (!vscode.workspace.isTrusted) {
      void vscode.window.showWarningMessage('信頼していないワークスペースでは git を動かさないので、変更は出しません。' +
        'Goal とログは開けます')
      return
    }
    const mine = ++asked
    const c = await readChanges(t.id)
    if (mine !== asked) return
    if ('reason' in c) {
      void vscode.window.showWarningMessage(c.reason)
      return
    }
    if (c.files.length === 0) {
      void vscode.window.showInformationMessage(`#${t.id}: ${c.baseRef} から変わったファイルはありません`)
      return
    }
    picker?.hide()
    const p = vscode.window.createQuickPick<Pick>()
    picker = p
    p.title = `${titled(t.id, 'Changes', c.repo)} · ${c.branch || `task/${t.id}`} ← ${c.baseRef}(${c.fork.slice(0, 7)} から)`
    p.placeholder = `${c.files.length + c.more} 件(コミット済み、作業中、未追跡を含む)。Enter で差分を開く、Esc で閉じる`
    p.matchOnDescription = true
    p.ignoreFocusOut = true
    p.items = [
      ...c.files.map(f => ({ label: f.path, description: STATUS_TEXT[f.status] + (f.binary ? '・バイナリ' : ''), change: f })),
      ...(c.more > 0 ? [{ label: `ほか ${c.more} 件は省略`, kind: vscode.QuickPickItemKind.Separator }] : []),
    ]
    p.onDidAccept(() => {
      const f = p.activeItems[0]?.change
      if (f) void openDiff(t.id, c, f)
    })
    p.onDidHide(() => {
      p.dispose()
      if (picker === p) picker = undefined
    })
    p.show()
  }

  const openLog = async (arg: unknown): Promise<void> => {
    const t = await resolve(arg, cards)
    if (!t) return
    const repo = t.repo || (await readRun(t.id))?.repo || ''
    const uri = vscode.Uri.from({ scheme: LOG_SCHEME, path: `/${t.id}/${titled(t.id, 'Log', repo)}.log` })
    const w = logs.watch(uri, await logPathOf(t.id))
    if (w.following) logs.changed.fire(uri)
    const doc = await vscode.workspace.openTextDocument(uri)
    await vscode.window.showTextDocument(doc, { preview: false })
    w.shown = true
    if (w.following) toEnd(uri)
    showFollowing()
  }

  const follow = (on: boolean) => async (arg: unknown): Promise<void> => {
    const uri = logUri(arg)
    const w = uri && await adopt(uri)
    if (!uri || !w) return
    w.following = on
    if (on) {
      logs.changed.fire(uri)
      toEnd(uri)
    }
    showFollowing()
  }

  context.subscriptions.push(goals, diffs, logs,
    vscode.workspace.registerTextDocumentContentProvider(GOAL_SCHEME, goals),
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, diffs),
    vscode.workspace.registerTextDocumentContentProvider(LOG_SCHEME, logs),
    vscode.commands.registerCommand('taskHub.task.goal', openGoal),
    vscode.commands.registerCommand('taskHub.task.changes', openChanges),
    vscode.commands.registerCommand('taskHub.task.log', openLog),
    vscode.commands.registerCommand('taskHub.log.follow', follow(true)),
    vscode.commands.registerCommand('taskHub.log.pause', follow(false)),
    vscode.commands.registerCommand('taskHub.board.show', () => vscode.commands.executeCommand('taskHub.board.focus')),
    vscode.workspace.onDidChangeTextDocument(e => {
      if (following(e.document.uri)) toEnd(e.document.uri)
    }),
    // A log is looked at while a tab shows it (VS Code may keep the document itself for minutes after the tab closes).
    vscode.window.tabGroups.onDidChangeTabs(() => {
      const shown = new Set(tabUris())
      for (const [key, w] of [...logs.open]) if (w.shown && !shown.has(key)) logs.close(key)
      void adoptTabs()
    }),
    // A following log that comes into view again shows its end.
    vscode.window.onDidChangeVisibleTextEditors(eds => {
      for (const ed of eds) if (following(ed.document.uri)) toEnd(ed.document.uri)
    }),
    vscode.window.onDidChangeActiveTextEditor(showFollowing),
    { dispose: () => picker?.hide() })
  void adoptTabs() // log tabs the window restored before the extension started
}
