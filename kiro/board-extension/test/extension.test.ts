// Runs the built out/extension.js (what goes in the VSIX) against a stand-in for the `vscode` module.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  appendFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync,
  utimesSync, writeFileSync,
} from 'node:fs'
import Module, { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, mock, test } from 'node:test'

import { NONE, pixels, scene } from '../../../claude/task-board/hooks/ship.ts'
import { ROOT, build } from '../scripts/build.mjs'
import { parseList } from '../../../claude/task-board/hooks/parse.ts'
import { CONFIG, EVENTS, LIST, METRICS, NOW } from './fixtures.ts'

const temps: string[] = []
const temp = (): string => {
  const dir = mkdtempSync(join(tmpdir(), 'task-hub-board-test-'))
  temps.push(dir)
  return dir
}
afterEach(() => {
  for (const dir of temps.splice(0)) rmSync(dir, { recursive: true, force: true })
})

// Just what the extension uses of the VS Code API, recording what it was given. Text document content providers work
// as in VS Code: a document is read once when opened and again when its provider fires onDidChange.
const fakeVscode = () => {
  const seen = { trees: [] as any[], bars: [] as any[], commands: new Map<string, (...args: any[]) => unknown>(),
    opened: [] as string[], webviews: new Map<string, any>(), messages: [] as string[], warnings: [] as string[],
    executed: [] as any[][], shown: [] as any[], pickers: [] as any[], providers: new Map<string, any>(),
    docs: new Map<string, any>(), provided: [] as string[], pending: [] as Promise<unknown>[],
    onChange: [] as Array<(e: any) => void>, editors: [] as any[],
    onTabs: [] as Array<() => void>, onVisible: [] as Array<(eds: any[]) => void>,
    context: new Map<string, unknown>() }
  class EventEmitter {
    listeners: Array<(v?: unknown) => void> = []
    event = (l: (v?: unknown) => void) => (this.listeners.push(l), { dispose: () => {
      this.listeners = this.listeners.filter(x => x !== l)
    } })
    fire(v?: unknown) { for (const l of this.listeners) l(v) }
    dispose() { this.listeners = [] }
  }
  class TreeItem {
    label: string
    collapsibleState: number
    constructor(label: string, collapsibleState = 0) { this.label = label; this.collapsibleState = collapsibleState }
  }
  class ThemeColor {
    id: string
    constructor(id: string) { this.id = id }
  }
  class ThemeIcon {
    id: string
    color?: ThemeColor
    constructor(id: string, color?: ThemeColor) { this.id = id; this.color = color }
  }
  class MarkdownString {
    value: string
    constructor(value: string) { this.value = value }
  }
  class Range {
    start: { line: number; character: number }
    constructor(line: number, character: number) { this.start = { line, character } }
  }
  class TabInputText {
    uri: any
    constructor(uri: any) { this.uri = uri }
  }
  const uri = ({ scheme, path, query = '' }: { scheme: string; path: string; query?: string }) =>
    ({ scheme, path, query, toString: () => `${scheme}:${path}${query ? `?${query}` : ''}` })
  const provide = async (u: any): Promise<string> => {
    seen.provided.push(u.toString())
    return seen.providers.get(u.scheme).provideTextDocumentContent(u)
  }
  const openDoc = async (u: any) => {
    const key = u.toString()
    if (!seen.docs.has(key)) {
      const text = await provide(u)
      seen.docs.set(key, { uri: u, text, languageId: u.path.endsWith('.md') ? 'markdown' : 'plaintext',
        getText() { return this.text }, get lineCount() { return this.text.split('\n').length } })
    }
    return seen.docs.get(key)
  }
  const window = {
    activeTextEditor: undefined as any,
    visibleTextEditors: [] as any[],
    createTreeView: (id: string, { treeDataProvider }: any) => {
      const tree = { id, provider: treeDataProvider, description: '', badge: undefined as unknown, dispose() {} }
      seen.trees.push(tree)
      return tree
    },
    createStatusBarItem: () => {
      const bar = { text: '', tooltip: '', command: '', backgroundColor: undefined, shown: false,
        show() { this.shown = true }, dispose() {} }
      seen.bars.push(bar)
      return bar
    },
    registerWebviewViewProvider: (id: string, provider: unknown) => (seen.webviews.set(id, provider), { dispose() {} }),
    showInformationMessage: async (text: string) => (seen.messages.push(text), undefined),
    showWarningMessage: async (text: string) => (seen.warnings.push(text), undefined),
    showTextDocument: async (document: any, options: unknown) => {
      seen.shown.push({ uri: document.uri.toString(), options })
      const editor = { document, revealed: [] as number[], revealRange(r: Range) { this.revealed.push(r.start.line) } }
      seen.editors.push(editor)
      window.visibleTextEditors.push(editor)
      window.activeTextEditor = editor
      for (const l of seen.onTabs) l()
      return editor
    },
    createQuickPick: () => {
      const on = { accept: [] as Array<() => void>, hide: [] as Array<() => void> }
      const p = { title: '', placeholder: '', items: [] as any[], activeItems: [] as any[], matchOnDescription: false,
        ignoreFocusOut: false, visible: false, disposed: false,
        show() { this.visible = true; seen.pickers.push(this) },
        hide() { if (this.visible) { this.visible = false; for (const l of on.hide) l() } },
        dispose() { this.disposed = true },
        onDidAccept: (l: () => void) => (on.accept.push(l), { dispose() {} }),
        onDidHide: (l: () => void) => (on.hide.push(l), { dispose() {} }),
        accept(label: string) { this.activeItems = this.items.filter((i: any) => i.label === label); for (const l of on.accept) l() } }
      return p
    },
    showQuickPick: async () => undefined,
    showInputBox: async () => undefined,
    onDidChangeActiveTextEditor: () => ({ dispose() {} }),
    onDidChangeVisibleTextEditors: (l: (eds: any[]) => void) => (seen.onVisible.push(l), { dispose() {} }),
    // one tab per editor shown
    tabGroups: {
      get all() { return [{ tabs: window.visibleTextEditors.map(e => ({ input: new TabInputText(e.document.uri) })) }] },
      onDidChangeTabs: (l: () => void) => (seen.onTabs.push(l), { dispose() {} }),
    },
  }
  const vscode = {
    EventEmitter, TreeItem, ThemeIcon, ThemeColor, MarkdownString, Range, TabInputText, StatusBarAlignment: { Left: 1, Right: 2 },
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 }, TextEditorRevealType: { Default: 0 },
    QuickPickItemKind: { Separator: -1 },
    Uri: {
      parse: (url: string) => ({ url }),
      joinPath: (base: { path: string }, ...parts: string[]) => ({ path: [base.path, ...parts].join('/') }),
      from: uri,
    },
    env: { openExternal: async (uri: { url: string }) => (seen.opened.push(uri.url), true) },
    window,
    workspace: {
      isTrusted: true,
      registerTextDocumentContentProvider: (scheme: string, provider: any) => {
        seen.providers.set(scheme, provider)
        const sub = provider.onDidChange((u: any) => {
          const doc = seen.docs.get(u.toString())
          if (doc) seen.pending.push(provide(u).then(text => {
            if (text === doc.text) return
            doc.text = text
            for (const l of seen.onChange) l({ document: doc })
          }))
        })
        return { dispose: () => { sub.dispose(); seen.providers.delete(scheme) } }
      },
      openTextDocument: openDoc,
      onDidChangeTextDocument: (l: (e: any) => void) => (seen.onChange.push(l), { dispose() {
        seen.onChange.splice(seen.onChange.indexOf(l), 1)
      } }),
    },
    languages: { setTextDocumentLanguage: async (doc: any, id: string) => (doc.languageId = id, doc) },
    commands: {
      registerCommand: (id: string, fn: (...args: any[]) => unknown) => (seen.commands.set(id, fn), { dispose() {} }),
      executeCommand: async (id: string, ...args: any[]) => {
        seen.executed.push([id, ...args])
        if (id === 'setContext') seen.context.set(args[0], args[1])
        if (id === 'vscode.diff') await Promise.all([openDoc(args[0]), openDoc(args[1])])
      },
    },
  }
  // The tab of `key` closed. The document stays, as VS Code may keep it for minutes after the tab closes.
  const close = (key: string) => {
    window.visibleTextEditors = window.visibleTextEditors.filter(e => e.document.uri.toString() !== key)
    for (const l of seen.onTabs) l()
  }
  return { vscode, seen, close }
}

// context.globalState, kept in `kept` (shared between activations to stand for the next window), recording each write.
const memento = (kept = new Map<string, unknown>()) => {
  const writes: [string, unknown][] = []
  return { kept, writes, fail: false, keys: () => [...kept.keys()], get: (key: string) => kept.get(key),
    async update(key: string, value: unknown) {
      if (this.fail) throw new Error('cannot write')
      writes.push([key, value])
      kept.set(key, value)
    } }
}
const fakeContext = (globalState = memento()) =>
  ({ subscriptions: [] as Array<{ dispose(): void }>, extensionUri: { path: '/ext' }, globalState })

// A WebviewView as Kiro hands it to resolveWebviewView: what the extension posts is kept in `posted`.
const fakeWebviewView = () => {
  const posted: any[] = []
  const on = { message: (_: unknown) => {}, visibility: () => {}, dispose: () => {} }
  const view = {
    visible: true,
    webview: {
      options: {} as any, html: '', cspSource: 'vscode-webview://x',
      asWebviewUri: (uri: { path: string }) => ({ toString: () => `vscode-webview://x${uri.path}` }),
      postMessage: async (m: unknown) => (posted.push(m), true),
      onDidReceiveMessage: (l: (m: unknown) => void) => (on.message = l, { dispose() {} }),
    },
    onDidChangeVisibility: (l: () => void) => (on.visibility = l, { dispose() {} }),
    onDidDispose: (l: () => void) => (on.dispose = l, { dispose() {} }),
  }
  return { view, posted, send: (m: unknown) => on.message(m),
    setVisible: (v: boolean) => { view.visible = v; on.visibility() }, dispose: () => on.dispose() }
}

// A fresh build each time, so each test gets its own module.
const load = (vscode: unknown): any => {
  const dir = build(temp())
  const original = (Module as any)._load
  ;(Module as any)._load = function (request: string, ...rest: unknown[]) {
    return request === 'vscode' ? vscode : original.call(this, request, ...rest)
  }
  try {
    return createRequire(import.meta.url)(join(dir, 'extension.js'))
  } finally {
    ;(Module as any)._load = original
  }
}

// The fixture's events, moved so that NOW is now: the extension takes the time from the clock.
const eventsNow = (): string => {
  const shift = Date.now() - NOW
  return EVENTS.replace(/"(2026-10-04T[\d:]+Z)"/g, (_, t) => JSON.stringify(new Date(Date.parse(t) + shift).toISOString()))
}
const FILES = async () => ({ events: eventsNow(), metrics: METRICS, ini: CONFIG })
const NO_FILES = async () => ({ events: '', metrics: '', ini: '' })

const start = (run: (fresh?: boolean) => Promise<unknown>, read: () => Promise<unknown> = NO_FILES, globalState = memento()) => {
  const { vscode, seen, close } = fakeVscode()
  const ext = load(vscode)
  const context = fakeContext(globalState)
  ext.activate(context, run, read)
  const provider = () => seen.trees[0].provider
  // The top level, or the children of the node `path` names (labels, from the top).
  const view = (...path: string[]) => {
    let nodes = provider().getChildren()
    for (const label of path) {
      nodes = provider().getChildren(nodes.find((n: any) => provider().getTreeItem(n).label === label))
    }
    return nodes.map((n: unknown) => provider().getTreeItem(n))
  }
  const stop = () => { for (const d of context.subscriptions) d.dispose() }
  // The ship view, opened as Kiro opens it, and told its width as media/ship.js tells it.
  const ship = (columns = 40) => {
    const w = fakeWebviewView()
    seen.webviews.get('taskHub.ship').resolveWebviewView(w.view)
    if (columns > 0) w.send({ type: 'size', columns })
    return w
  }
  return { seen, view, stop, ship, globalState, vscode, close, provider,
    refresh: () => seen.commands.get('taskHub.board.refresh')!() as Promise<void> }
}

test('ビューに並べ、ステータスバーに数を出し、更新ボタンで task list を読み直す', async () => {
  let runs = 0
  const fresh: boolean[] = []
  const { seen, view, stop, refresh } = start(async f => (runs++, fresh.push(f === true), { exitCode: 0, stdout: LIST, stderr: '' }))
  try {
    assert.equal(seen.trees[0].id, 'taskHub.board')
    await refresh() // the run started by activate: the button waits for it instead of starting another
    assert.equal(runs, 1)
    assert.deepEqual(fresh, [false]) // activate and the minute's look: the shared cache
    const groups = view()
    assert.deepEqual(groups.map((i: any) => [i.label, i.collapsibleState, i.iconPath]), [
      ['要対応 3', 2, undefined], ['実行中 2', 2, undefined], ['待ち 1', 2, undefined], ['Backlog 1', 1, undefined],
      ['その他 1', 1, undefined]])
    const needs = view('要対応 3')
    assert.deepEqual(needs.map((i: any) => i.label), ['#110 画面, 検索', '#75 Test kiro automation workflow', '#90 merge を待つカード'])
    assert.equal(needs[0].description, 'aica · Blocked · 待ち: #109')
    assert.equal(needs[0].iconPath.id, 'error')
    assert.equal(needs[0].iconPath.color.id, 'charts.red')
    assert.equal(needs[0].collapsibleState, 0) // no events.jsonl: nothing under it
    assert.equal(needs[0].tooltip.value, '**#110 画面, 検索**\n\nBlocked · jyoka/aica · 待ち: \\#109')
    assert.equal(needs[0].id, 'card/110')
    const running = view('実行中 2')
    assert.deepEqual(running.map((i: any) => i.description), ['aica', 'task-hub · review'])
    assert.equal(running[1].iconPath.color.id, 'terminal.ansiCyan')
    assert.match(seen.trees[0].description, /^\d\d:\d\d 時点$/)
    assert.deepEqual(seen.trees[0].badge, { value: 3, tooltip: '要対応 3 件' })
    const bar = seen.bars[0]
    assert.equal(bar.shown, true)
    assert.equal(bar.text, '$(checklist) task: 実行中2 レビュー待ち1 止まり1')
    assert.equal(bar.command, 'taskHub.board.focus')
    assert.equal(bar.backgroundColor, undefined)
    await refresh()
    assert.equal(runs, 2)
    assert.deepEqual(fresh, [false, true]) // the button asks GitHub
  } finally {
    stop()
  }
})

test('task list が失敗したら、ビューとステータスバーに読めないことと理由を出す', async () => {
  const stdout = 'error: the board is not configured in ~/.config/task-hub/config.ini\nhelp: add:  [board]  project = <owner>/<project number>\n'
  const { seen, view, stop, refresh } = start(async () => ({ exitCode: 1, stdout, stderr: '' }))
  try {
    await refresh()
    assert.deepEqual(view().map((i: any) => i.label), ['読めませんでした: the board is not configured in ~/.config/task-hub/config.ini'])
    assert.equal(seen.trees[0].badge, undefined)
    assert.match(seen.bars[0].text, /^\$\(warning\) task: 読めない \(the board is not configured/)
    assert.match(seen.bars[0].tooltip, /the board is not configured in ~\/\.config\/task-hub\/config\.ini$/)
    assert.equal(seen.bars[0].backgroundColor.id, 'statusBarItem.warningBackground')
  } finally {
    stop()
  }
})

test('run がその場で投げても読めないと出し、次の更新でまた実行する', async () => {
  let runs = 0
  const { seen, stop, refresh } = start(() => { runs++; throw new Error('sync') })
  try {
    await refresh()
    await refresh()
    assert.equal(runs, 2)
    assert.match(seen.bars[0].text, /読めない \(Error: sync\)/)
  } finally {
    stop()
  }
})

test('実行そのものが投げても、読めないと出す', async () => {
  const { seen, view, stop, refresh } = start(async () => { throw new Error('boom') })
  try {
    await refresh()
    assert.deepEqual(view().map((i: any) => i.label), ['読めませんでした: Error: boom'])
    assert.match(seen.bars[0].text, /読めない \(Error: boom\)/)
  } finally {
    stop()
  }
})

test('events と metrics から経過時間・判定・理由・PR を出し、PR の子ノードを押すと既定のブラウザで開く', async () => {
  const { seen, view, stop, refresh } = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), FILES)
  try {
    await refresh()
    const running = view('実行中 2')
    assert.deepEqual(running.map((i: any) => i.description), ['aica · 12分 / 普段9分', 'task-hub · review · 5分 / 普段 不明'])
    assert.equal(running[0].iconPath.color.id, 'list.warningForeground')
    const needs = view('要対応 3')
    assert.deepEqual(needs.map((i: any) => i.collapsibleState), [2, 2, 0])
    assert.deepEqual(view('要対応 3', '#110 画面, 検索').map((i: any) => i.label), ['理由: 前提の PR #26 が まだマージされていない'])
    const review = view('要対応 3', '#75 Test kiro automation workflow')
    assert.deepEqual(review.map((i: any) => [i.label, i.iconPath.id, i.iconPath.color?.id, i.command]), [
      ['判定: needs changes', 'request-changes', 'charts.yellow', undefined],
      ['PR #36', 'git-pull-request', undefined,
        { command: 'taskHub.board.openPr', title: 'PR を開く', arguments: ['https://github.com/jyoka/task-hub/pull/36'] }],
    ])
    const { command, arguments: args } = review[1].command
    await seen.commands.get(command)!(...args)
    assert.deepEqual(seen.opened, ['https://github.com/jyoka/task-hub/pull/36'])
  } finally {
    stop()
  }
})

test('ファイルを読むところが投げても、一覧は出す', async () => {
  const { seen, view, stop, refresh } = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }),
    async () => { throw new Error('EACCES') })
  try {
    await refresh()
    assert.deepEqual(view().map((i: any) => i.label), ['要対応 3', '実行中 2', '待ち 1', 'Backlog 1', 'その他 1'])
    assert.equal(seen.bars[0].text, '$(checklist) task: 実行中2 レビュー待ち1 止まり1')
  } finally {
    stop()
  }
})

// The real child_process call, with HOME pointing at a stand-in ~/.local/bin/task that records its arguments.
const withHome = async (script: string | null, body: (home: string) => Promise<void>) => {
  const home = temp()
  if (script !== null) {
    mkdirSync(join(home, '.local', 'bin'), { recursive: true })
    writeFileSync(join(home, '.local', 'bin', 'task'), script)
    chmodSync(join(home, '.local', 'bin', 'task'), 0o755)
  }
  const saved = process.env.HOME
  process.env.HOME = home
  try {
    await body(home)
  } finally {
    process.env.HOME = saved
  }
}

test('実行するのは ~/.local/bin/task list だけ(ホームを展開した絶対パス)', async () => {
  const { vscode } = fakeVscode()
  const ext = load(vscode)
  await withHome(`#!/bin/sh\nprintf '%s\\n' "$0" "$@" > "$HOME/argv"\necho 'counts: Blocked=1'\n`, async home => {
    const out = await ext.runTaskList()
    assert.deepEqual(out, { exitCode: 0, stdout: 'counts: Blocked=1\n', stderr: '' })
    assert.equal(readFileSync(join(home, 'argv'), 'utf8'), `${home}/.local/bin/task\nlist\n`)
  })
  await withHome(`#!/bin/sh\necho 'error: no board'\nexit 1\n`, async () => {
    assert.deepEqual(await ext.runTaskList(), { exitCode: 1, stdout: 'error: no board\n', stderr: '' })
  })
  await withHome(null, async home => {
    assert.deepEqual(await ext.runTaskList(), { reason: `${home}/.local/bin/task がありません` })
  })
  // the refresh button: --max-age 0, and without it on a bin/task from before the flag
  await withHome(`#!/bin/sh\nprintf '%s\\n' "$@" >> "$HOME/argv"\necho 'counts: Blocked=1'\n`, async home => {
    assert.deepEqual(await ext.runTaskList(true), { exitCode: 0, stdout: 'counts: Blocked=1\n', stderr: '' })
    assert.equal(readFileSync(join(home, 'argv'), 'utf8'), 'list\n--max-age\n0\n')
  })
  const old = `#!/bin/sh\nprintf '%s\\n' "$*" >> "$HOME/argv"\n[ "$2" = --max-age ] && { echo 'error: unknown flag --max-age for \`list\`'; exit 2; }\necho 'counts: Blocked=1'\n`
  await withHome(old, async home => {
    assert.deepEqual(await ext.runTaskList(true), { exitCode: 0, stdout: 'counts: Blocked=1\n', stderr: '' })
    assert.equal(readFileSync(join(home, 'argv'), 'utf8'), 'list --max-age 0\nlist\n')
  })
})

// Windows: windows\install.ps1's ~\.local\bin\task.cmd, which Node runs only through cmd.exe, from a home with a space
// and Japanese in its name (as C:\Users\<名前>). Run by .github/workflows/windows.yml.
test('Windows: ~\\.local\\bin\\task.cmd list を cmd.exe で動かす', { skip: process.platform !== 'win32' && 'Windows only' }, async () => {
  const { vscode } = fakeVscode()
  const ext = load(vscode)
  const saved = process.env.USERPROFILE
  const home = join(temp(), 'ユー ザー')
  const bin = join(home, '.local', 'bin')
  process.env.USERPROFILE = home
  try {
    mkdirSync(bin, { recursive: true })
    assert.deepEqual(await ext.runTaskList(), { reason: `${join(bin, 'task.cmd')} がありません` })
    writeFileSync(join(bin, 'task'), '#!/bin/sh\necho wrong\n')  // Git Bash's, not run
    writeFileSync(join(bin, 'task.cmd'), '@echo off\r\necho %*>> "%USERPROFILE%\\argv"\r\necho counts: Blocked=1\r\n')
    assert.deepEqual(await ext.runTaskList(), { exitCode: 0, stdout: 'counts: Blocked=1\r\n', stderr: '' })
    assert.deepEqual(await ext.runTaskList(true), { exitCode: 0, stdout: 'counts: Blocked=1\r\n', stderr: '' })
    assert.equal(readFileSync(join(home, 'argv'), 'utf8'), 'list\r\nlist --max-age 0\r\n')
    writeFileSync(join(bin, 'task.cmd'), '@echo off\r\necho error: no board\r\nexit /b 1\r\n')
    assert.deepEqual(await ext.runTaskList(), { exitCode: 1, stdout: 'error: no board\r\n', stderr: '' })
  } finally {
    process.env.USERPROFILE = saved
  }
})

test('読むファイルは ~/.local/state/task-hub/ の events.jsonl と metrics.jsonl と config.ini、ないものは空', async () => {
  const { vscode } = fakeVscode()
  const ext = load(vscode)
  await withHome(null, async home => {
    assert.deepEqual(await ext.readFiles(), { events: '', metrics: '', ini: '' })
    mkdirSync(join(home, '.local', 'state', 'task-hub'), { recursive: true })
    writeFileSync(join(home, '.local', 'state', 'task-hub', 'events.jsonl'), '{"broken\n')
    mkdirSync(join(home, '.local', 'state', 'task-hub', 'metrics.jsonl')) // a directory: readFile fails
    mkdirSync(join(home, '.config', 'task-hub'), { recursive: true })
    writeFileSync(join(home, '.config', 'task-hub', 'config.ini'), CONFIG)
    assert.deepEqual(await ext.readFiles(), { events: '{"broken\n', metrics: '', ini: CONFIG })
  })
})

test('ステータスバーは位置を変えず(左、優先度 100)いつも出し、Blocked があれば「止まり」を出す', async () => {
  const { vscode, seen } = fakeVscode()
  const made: unknown[][] = []
  const create = vscode.window.createStatusBarItem
  vscode.window.createStatusBarItem = (...args: unknown[]) => (made.push(args), create())
  const ext = load(vscode)
  const context = fakeContext()
  const blocked = 'counts: Backlog=0, Ready=0, In progress=0, In review=0, wait for merge=0, Blocked=1\n' +
    'tasks[1]{id,title,status,repo,agent,waits_for}:\n  "109",計測,Blocked,jyoka/aica,"",""\n'
  ext.activate(context, async () => ({ exitCode: 0, stdout: blocked, stderr: '' }), NO_FILES)
  try {
    await (seen.commands.get('taskHub.board.refresh')!() as Promise<void>)
    assert.deepEqual(made, [[1, 100]])
    assert.equal(seen.bars[0].shown, true)
    assert.equal(seen.bars[0].text, '$(checklist) task: 止まり1')
    assert.deepEqual(seen.trees[0].badge, { value: 1, tooltip: '要対応 1 件' })
  } finally {
    for (const d of context.subscriptions) d.dispose()
  }
})

test('素の task を呼ぶコードがない: プロセスを起動するのは task list と、読むだけの git の 2 か所だけ', async () => {
  const dir = build(temp())
  const sources = [...readdirSync(join(ROOT, 'src')).map(f => join(ROOT, 'src', f)),
    ...readdirSync(dir).map(f => join(dir, f))]
  const calls = sources.flatMap(f => readFileSync(f, 'utf8').match(/\b(execFile|execFileSync|exec|execSync|spawn|spawnSync|fork)\(.*/g) ?? [])
  assert.equal(calls.length, 4) // src/extension.ts, src/inspect.ts and their out/*.js
  // the shell only on Windows, for task.cmd (cmd.exe), with the fixed words list and --max-age 0
  assert.deepEqual(calls.filter(c => /^execFile\(WINDOWS \? `"\$\{task\}"` : task, \['list', \.\.\.\(fresh \? \['--max-age', '0'\] : \[\]\)\], \{$/.test(c)).length, 2)
  assert.deepEqual(calls.filter(c => /^execFile\('git', \[\.\.\.SAFE, '-C', wt, \.\.\.args\], \{$/.test(c)).length, 2)
  for (const f of sources) {
    const text = readFileSync(f, 'utf8')
    if (/const task = /.test(text)) assert.match(text, /const task = taskPath\(\)/)
    assert.doesNotMatch(text, /shell: true/)
    assert.equal((text.match(/shell:/g) ?? []).length, /const task = /.test(text) ? 1 : 0)
    if (/shell:/.test(text)) assert.match(text, /shell: WINDOWS,/)
  }
  // git: only subcommands that read, and never one that writes
  const { vscode } = fakeVscode()
  load(vscode)
  const inspect = createRequire(import.meta.url)(join(dir, 'inspect.js'))
  assert.deepEqual(inspect.READ_ONLY, ['rev-parse', 'merge-base', 'symbolic-ref', 'diff', 'ls-files', 'cat-file'])
  for (const sub of ['add', 'update-index', 'checkout', 'stash', 'reset', 'commit', 'fetch']) {
    await assert.rejects(inspect.git(temp(), [sub]), /は使いません/)
  }
})

test('package.json: 信頼していないワークスペースでは一部だけ動く、engines は Kiro 1.2.4 の 1.131.0 以下', () => {
  const p = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  assert.equal(p.capabilities.untrustedWorkspaces.supported, 'limited')
  assert.match(p.capabilities.untrustedWorkspaces.description, /変更/)
  const [major, minor] = p.engines.vscode.replace(/^\^/, '').split('.').map(Number)
  assert.ok(major === 1 && minor <= 131)
  assert.equal(p.main, './out/extension.js')
  assert.deepEqual(p.dependencies ?? {}, {})
  assert.ok(p.contributes.menus['view/title'].some((m: any) => m.command === 'taskHub.board.refresh' && m.when === 'view == taskHub.board'))
})

const settle = () => new Promise(resolve => setImmediate(resolve))

test('船のビュー: ボードの上の Webview、CSP つきで同梱のスクリプトだけ、場面は mod の ship.ts から', async () => {
  const p = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  assert.deepEqual(p.contributes.views.taskHub.map((v: any) => [v.id, v.type]), [['taskHub.ship', 'webview'], ['taskHub.board', undefined]])
  const { stop, ship, refresh } = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }))
  try {
    await refresh()
    const w = ship(0)
    assert.deepEqual(w.posted, []) // nothing until the script tells the width
    assert.equal(w.view.webview.options.enableScripts, true)
    assert.deepEqual(w.view.webview.options.localResourceRoots, [{ path: '/ext/media' }])
    const html = w.view.webview.html
    const nonce = html.match(/script-src 'nonce-([0-9a-f]{32})'/)?.[1]
    assert.ok(nonce)
    assert.deepEqual(html.match(/<script[^>]*>/g), [`<script nonce="${nonce}" src="vscode-webview://x/ext/media/ship.js">`])
    assert.match(html, /<link rel="stylesheet" href="vscode-webview:\/\/x\/ext\/media\/ship.css">/)
    assert.doesNotMatch(html, /https?:/)

    w.send({ type: 'size', columns: 48 })
    assert.equal(w.posted.length, 1)
    const state = w.posted[0]
    const c = pixels(scene(parseList(LIST, '11:00').cards), 48, 0)
    assert.equal(state.picture.columns, 48)
    assert.deepEqual(state.picture.px, Array.from(c.px, v => v === NONE ? -1 : v))
    assert.deepEqual(state.aboard.map((a: any) => a.label), ['乗組員', '荷', 'SOS', '桟橋'])
    assert.equal(state.hidden, false)
    // the files and messages the script and page need ship in the VSIX's media/
    for (const f of ['ship.js', 'ship.css']) assert.ok(readdirSync(join(ROOT, 'media')).includes(f))
  } finally {
    stop()
  }
})

test('船は毎秒数コマ動き、ビューが見えていないときは描き直さず、見えたら最新を送る', async () => {
  mock.timers.enable({ apis: ['setInterval'] })
  const { stop, ship, refresh } = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }))
  try {
    await refresh()
    const w = ship()
    assert.equal(w.posted.length, 1)
    mock.timers.tick(300)
    mock.timers.tick(300)
    assert.equal(w.posted.length, 3)
    assert.notDeepEqual(w.posted[1].picture.px, w.posted[0].picture.px)
    w.setVisible(false)
    mock.timers.tick(3000)
    await refresh()
    w.send({ type: 'size', columns: 50 })
    assert.equal(w.posted.length, 3)
    w.setVisible(true)
    assert.equal(w.posted.length, 4)
    assert.equal(w.posted[3].picture.columns, 50)
    // the view goes away: nothing more is posted to it
    w.dispose()
    mock.timers.tick(3000)
    assert.equal(w.posted.length, 4)
  } finally {
    stop()
    mock.timers.reset()
  }
})

test('船を隠すボタン: globalState に覚え、隠している間は絵を送らず、次に開いても隠れたまま', async () => {
  mock.timers.enable({ apis: ['setInterval'] })
  const kept = new Map<string, unknown>()
  const first = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), NO_FILES, memento(kept))
  try {
    await first.refresh()
    const w = first.ship()
    w.send({ type: 'toggle' })
    await settle()
    assert.deepEqual(first.globalState.writes, [['taskHub.shipHidden', true]])
    const last = w.posted.at(-1)
    assert.deepEqual([last.hidden, last.picture, last.aboard], [true, null, []])
    const n = w.posted.length
    mock.timers.tick(3000) // no frames while hidden
    assert.equal(w.posted.length, n)
  } finally {
    first.stop()
  }
  const next = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), NO_FILES, memento(kept))
  try {
    await next.refresh()
    const w = next.ship()
    assert.deepEqual([w.posted[0].hidden, w.posted[0].picture], [true, null])
    w.send({ type: 'toggle' })
    await settle()
    assert.equal(kept.get('taskHub.shipHidden'), false)
    assert.equal(w.posted.at(-1).picture.columns, 40)
  } finally {
    next.stop()
    mock.timers.reset()
  }
})

test('実績: 解除したら showInformationMessage で 1 回だけ知らせ、globalState に覚え、船の下に並べる', async () => {
  const kept = new Map<string, unknown>()
  const metrics = async () => ({ events: '', metrics: METRICS, ini: '' })
  const first = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), metrics, memento(kept))
  try {
    await first.refresh()
    const w = first.ship()
    await first.refresh()
    await first.refresh()
    assert.deepEqual(first.seen.messages, ['実績解除: 初航海 claude、初航海 kiro'])
    assert.deepEqual(first.globalState.writes, [['taskHub.badges', ['first-claude', 'first-kiro']]])
    assert.deepEqual(w.posted.at(-1).badges.map((b: any) => b.name), ['初航海 claude', '初航海 kiro'])
  } finally {
    first.stop()
  }
  // the next window: already told, so not again
  const next = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), metrics, memento(kept))
  try {
    await next.refresh()
    assert.deepEqual(next.seen.messages, [])
    assert.deepEqual(next.globalState.writes, [])
  } finally {
    next.stop()
  }
})

test('実績を globalState に覚えられないときは知らせない(次の更新でまた試す)', async () => {
  const state = memento()
  state.fail = true
  const { seen, stop, refresh } = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }),
    async () => ({ events: '', metrics: METRICS, ini: '' }), state)
  try {
    await refresh()
    assert.deepEqual(seen.messages, [])
    state.fail = false
    await refresh()
    assert.deepEqual(seen.messages, ['実績解除: 初航海 claude、初航海 kiro'])
  } finally {
    stop()
  }
})

// ---------- a card's Goal, Changes and Log ----------

// The board `task list` prints with card 900 (whose run is on this machine) and card 901 (never run here).
const INSPECT_LIST = 'counts: In progress=1, Blocked=1\ntasks[2]{id,title,status,repo,agent,waits_for}:\n' +
  '  "900",Demo task,In progress,jyoka/demo,claude,""\n  "901",Other task,Blocked,jyoka/demo,claude,""\n'
const inspectRun = async () => ({ exitCode: 0, stdout: INSPECT_LIST, stderr: '' })

// git with no global or system config (no signing, no hooks of the user's), as task-hub's own clone would be.
const GIT_ENV = { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_AUTHOR_NAME: 't',
  GIT_AUTHOR_EMAIL: 't@example.com', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@example.com' }
const g = (cwd: string, ...args: string[]): string => execFileSync('git', args, { cwd, env: GIT_ENV, encoding: 'utf8' })

// A HOME as task-hub leaves it for task 900: its repo cloned under share/repos, its worktree on task/900 from
// origin/main, runs/900.json, logs/900.log and board-cache.json. origin/main moved on after the task branched.
const taskHome = (home: string, { base = '' } = {}) => {
  const origin = join(home, 'origin')
  mkdirSync(origin)
  g(origin, 'init', '-q', '-b', 'main')
  writeFileSync(join(origin, 'a.txt'), 'one\ntwo\n')
  writeFileSync(join(origin, 'b.txt'), 'gone soon\n')
  writeFileSync(join(origin, 'd.txt'), 'dee\n')
  writeFileSync(join(origin, 'same.txt'), 'unchanged\n')
  g(origin, 'add', '-A')
  g(origin, 'commit', '-q', '-m', 'base')
  const clone = join(home, '.local', 'share', 'task-hub', 'repos', 'jyoka', 'demo')
  mkdirSync(join(clone, '..'), { recursive: true })
  g(home, 'clone', '-q', origin, clone)
  const wt = join(home, '.local', 'share', 'task-hub', 'worktrees', '900')
  g(clone, 'worktree', 'add', '-q', '-b', 'task/900', wt, 'origin/main')
  writeFileSync(join(origin, 'upstream.txt'), 'not the task\n')
  g(origin, 'add', '-A')
  g(origin, 'commit', '-q', '-m', 'upstream')
  g(clone, 'fetch', '-q')
  const state = join(home, '.local', 'state', 'task-hub')
  mkdirSync(join(state, 'runs'), { recursive: true })
  mkdirSync(join(state, 'logs'), { recursive: true })
  const log = join(state, 'logs', '900.log')
  writeFileSync(join(state, 'runs', '900.json'), JSON.stringify({ repo: 'jyoka/demo', title: 'Demo task', agent: 'claude',
    base, branch: 'task/900', worktree: wt, log, pr: '', stage: 'agent' }))
  const item = (repo: string, n: number, body: string) => ({ id: `I${n}${repo}`, content: { number: n, title: 'Demo task',
    url: `https://github.com/${repo}/issues/${n}`, body, state: 'OPEN', repository: { nameWithOwner: repo } },
    status: { name: 'In progress' }, repo: { text: 'jyoka/demo' } })
  writeFileSync(join(state, 'board-cache.json'), JSON.stringify({ key: ['jyoka', '2', 'jyoka/tasks'],
    fetched_at: Date.now() / 1000 - 300,
    items: [item('jyoka/other', 900, 'NOT THIS ONE'), item('jyoka/tasks', 900, '### Goal\nMake **demo** work.\n')] }))
  return { wt, clone, origin, state, log }
}

// The task's committed and uncommitted work, in every kind git has.
const work = (wt: string) => {
  writeFileSync(join(wt, 'a.txt'), 'one\nTWO\n')
  rmSync(join(wt, 'b.txt'))
  writeFileSync(join(wt, 'c.txt'), 'new file\n')
  writeFileSync(join(wt, 'bin.dat'), Buffer.from([0, 1, 2, 3, 0, 255]))
  writeFileSync(join(wt, 'big.txt'), 'x'.repeat(1024 * 1024 + 10))
  g(wt, 'add', '-A')
  g(wt, 'commit', '-q', '-m', 'task work')
  writeFileSync(join(wt, 'd.txt'), 'dee changed, not staged\n')
  writeFileSync(join(wt, 'e.txt'), 'staged, not committed\n')
  g(wt, 'add', 'e.txt')
  writeFileSync(join(wt, 'f.txt'), 'untracked\n')
  writeFileSync(join(wt, '.task-report.md'), '## Report\n')
}

// What inspection must leave as it found it: the index (bytes and time), HEAD, every ref, and what git status says.
const gitState = (wt: string) => {
  const index = g(wt, 'rev-parse', '--git-path', 'index').trim()
  const path = index.startsWith('/') ? index : join(wt, index)
  return { index: createHash('sha256').update(readFileSync(path)).digest('hex'), mtime: statSync(path).mtimeMs,
    head: g(wt, 'rev-parse', 'HEAD'), refs: g(wt, 'for-each-ref'),
    status: execFileSync('git', ['status', '--porcelain', '-uall'], { cwd: wt, env: { ...GIT_ENV, GIT_OPTIONAL_LOCKS: '0' },
      encoding: 'utf8' }) }
}

// Waits for `cond` at most `ms`: a log tab is updated by fs.watchFile, which looks once a second.
const until = async (cond: () => boolean, ms = 5000) => {
  const end = Date.now() + ms
  while (!cond()) {
    if (Date.now() > end) throw new Error(`not within ${ms} ms`)
    await new Promise(r => setTimeout(r, 25))
  }
}
const cardNode = (b: ReturnType<typeof start>, id: string) => {
  const groups = b.provider().getChildren()
  return groups.flatMap((gr: any) => b.provider().getChildren(gr)).find((n: any) => n.task === id)
}

test('カードの行に Goal・変更・ログの操作が出て、PR の行はこれまでどおりブラウザで開く', async () => {
  const p = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  const items = p.contributes.menus['view/item/context']
  for (const c of ['taskHub.task.goal', 'taskHub.task.changes', 'taskHub.task.log']) {
    assert.ok(p.contributes.commands.some((x: any) => x.command === c && x.category === 'task-hub'), c)
    assert.deepEqual(items.filter((m: any) => m.command === c).map((m: any) => m.when),
      ['view == taskHub.board && viewItem == taskHub.card', 'view == taskHub.board && viewItem == taskHub.card'])
  }
  const titles = p.contributes.menus['editor/title'].map((m: any) => [m.command, m.when])
  assert.deepEqual(titles, [
    ['taskHub.log.pause', 'resourceScheme == taskhub-log && taskHub.logFollowing'],
    ['taskHub.log.follow', 'resourceScheme == taskhub-log && !taskHub.logFollowing'],
    ['taskHub.board.show', 'resourceScheme =~ /^taskhub-(goal|diff|log)$/']])
  const b = start(async () => ({ exitCode: 0, stdout: LIST, stderr: '' }), FILES)
  try {
    await b.refresh()
    const review = b.view('要対応 3')
    assert.deepEqual(review.map((i: any) => i.contextValue), ['taskHub.card', 'taskHub.card', 'taskHub.card'])
    assert.equal(review[1].command, undefined) // the card's own row opens nothing by itself, as before
    const children = b.view('要対応 3', '#75 Test kiro automation workflow')
    assert.deepEqual(children.map((i: any) => i.contextValue), [undefined, undefined]) // verdict and PR rows: no actions
    assert.equal(children[1].command.command, 'taskHub.board.openPr')
    await b.seen.commands.get('taskHub.board.show')!()
    assert.deepEqual(b.seen.executed.at(-1), ['taskHub.board.focus'])
  } finally {
    b.stop()
  }
})

test('Goal: カードの Issue 本文を、番号と repo の付いた読み取り専用の Markdown のタブで開く', async () => {
  await withHome(null, async home => {
    const { state } = taskHome(home)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.goal')!(cardNode(b, '900'))
      assert.deepEqual(b.seen.warnings, [])
      const [shown] = b.seen.shown
      assert.equal(shown.uri, 'taskhub-goal:/900/#900 Goal · demo.md')
      const doc = b.seen.docs.get(shown.uri)
      assert.equal(doc.languageId, 'markdown')
      assert.match(doc.text, /^<!-- task-hub #900: 読み取り専用/)
      assert.match(doc.text, /> \*\*#900 Demo task\*\* · jyoka\/demo · https:\/\/github\.com\/jyoka\/tasks\/issues\/900/)
      assert.match(doc.text, /\(5 分前\)/)
      assert.match(doc.text, /---\n\n### Goal\nMake \*\*demo\*\* work\.\n$/)
      assert.doesNotMatch(doc.text, /NOT THIS ONE/) // the same number in another repo of the Project
      assert.doesNotMatch(doc.text, /ボードを変えています/)

      // a board change after the read is said; the open tab reads the cache again when opened again
      writeFileSync(join(state, 'board-cache.stale'), String(Date.now() / 1000))
      await b.seen.commands.get('taskHub.task.goal')!('900')
      await Promise.all(b.seen.pending)
      assert.match(b.seen.docs.get(shown.uri).text, /そのあと task-hub がボードを変えています/)

      // a card not in the cache: said, nothing opened, the open tab stays as it is
      await b.seen.commands.get('taskHub.task.goal')!('901')
      assert.match(b.seen.warnings[0], /#901 はボードのキャッシュにありません.*task show 901 --full/)
      writeFileSync(join(state, 'board-cache.json'), '{"items": []}')
      await b.seen.commands.get('taskHub.task.goal')!('900')
      assert.match(b.seen.warnings[1], /#900 はボードのキャッシュにありません/)
      assert.match(b.seen.docs.get(shown.uri).text, /Make \*\*demo\*\* work/)
      rmSync(join(state, 'board-cache.json'))
      await b.seen.commands.get('taskHub.task.goal')!('900')
      assert.match(b.seen.warnings[2], /board-cache\.json\)がありません/)
      assert.equal(b.seen.shown.length, 2)
    } finally {
      b.stop()
    }
  })
})

test('変更: base との分かれ目から今の worktree まで(コミット済み・作業中・未追跡)を並べ、選ぶと差分を開く。index も ref も変えない', async () => {
  await withHome(null, async home => {
    const { wt } = taskHome(home)
    work(wt)
    utimesSync(join(wt, 'same.txt'), new Date(), new Date(Date.now() + 5000)) // stat-dirty: `git diff` would refresh the index
    const before = gitState(wt)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!(cardNode(b, '900'))
      assert.deepEqual(b.seen.warnings, [])
      const picker = b.seen.pickers[0]
      assert.match(picker.title, /^#900 Changes · demo · task\/900 ← origin\/main\([0-9a-f]{7} から\)$/)
      assert.deepEqual(picker.items.map((i: any) => [i.label, i.description]), [
        ['a.txt', '変更'], ['b.txt', '削除'], ['big.txt', '追加'], ['bin.dat', '追加・バイナリ'], ['c.txt', '追加'],
        ['d.txt', '変更'], ['e.txt', '追加'], ['f.txt', '未追跡(まだコミットされていない新しいファイル)']])
      assert.equal(picker.ignoreFocusOut, true) // stays open to pick the next file

      const fork = g(wt, 'merge-base', 'origin/main', 'HEAD').trim()
      const diff = async (label: string) => {
        picker.accept(label)
        await until(() => b.seen.executed.filter(e => e[0] === 'vscode.diff').length > 0 &&
          b.seen.executed.at(-1)![1].path.endsWith(`/${label}`))
        const [, left, right, title, options] = b.seen.executed.at(-1)!
        await Promise.all([left, right].map(u => until(() => b.seen.docs.has(u.toString()))))
        return { left: left.toString(), right: right.toString(), title, options,
          base: b.seen.docs.get(left.toString()).text, now: b.seen.docs.get(right.toString()).text }
      }
      const a = await diff('a.txt')
      assert.equal(a.left, `taskhub-diff:/900/base/a.txt?${fork}`)
      assert.equal(a.right, `taskhub-diff:/900/worktree/a.txt?${fork}`)
      assert.equal(a.title, '#900 a.txt · demo (origin/main ↔ 作業中)')
      assert.deepEqual(a.options, { preview: true, preserveFocus: true })
      assert.deepEqual([a.base, a.now], ['one\ntwo\n', 'one\nTWO\n'])
      const deleted = await diff('b.txt')
      assert.deepEqual([deleted.base, deleted.now], ['gone soon\n', ''])
      const added = await diff('c.txt')
      assert.deepEqual([added.base, added.now], ['', 'new file\n'])
      const unstaged = await diff('d.txt')
      assert.deepEqual([unstaged.base, unstaged.now], ['dee\n', 'dee changed, not staged\n'])
      const untracked = await diff('f.txt')
      assert.deepEqual([untracked.base, untracked.now], ['', 'untracked\n'])
      const binary = await diff('bin.dat')
      assert.match(binary.now, /^\(task-hub: 作業中の版はバイナリ\(6 バイト\)なので、テキストとして出しません\)\n$/)
      const big = await diff('big.txt')
      assert.match(big.now, /^\(task-hub: 作業中の版は 1048586 バイトあり、大きすぎる/)

      assert.deepEqual(gitState(wt), before)
      assert.ok(readFileSync(join(wt, '.task-report.md'))) // left where it was, only not listed
    } finally {
      b.stop()
    }
  })
})

test('変更: 読むだけを守る(clean フィルタを動かさない、GIT_DIR に引かれない、worktree の外へのリンクを読まない、信頼のない窓)', async () => {
  await withHome(null, async home => {
    const { wt, clone, origin } = taskHome(home)
    // a clean filter the repo asks for (as Git LFS does): it must not run
    const marker = join(home, 'filter-ran')
    g(clone, 'config', 'filter.mark.clean', `sh -c 'echo ran >> "${marker}"; cat'`)
    writeFileSync(join(wt, '.gitattributes'), '*.txt filter=mark\n')
    // a directory of the base that became a symlink to a folder outside the worktree
    mkdirSync(join(origin, '..', 'outside'))
    writeFileSync(join(origin, '..', 'outside', 'hosts'), 'SECRET outside the worktree\n')
    g(wt, 'rm', '-q', 'a.txt')
    g(wt, 'commit', '-q', '-m', 'a.txt is gone')
    mkdirSync(join(wt, 'conf'))
    writeFileSync(join(wt, 'conf', 'hosts'), 'inside\n')
    g(wt, 'add', 'conf')
    g(wt, 'commit', '-q', '-m', 'conf')
    rmSync(join(wt, 'conf'), { recursive: true })
    symlinkSync(join(origin, '..', 'outside'), join(wt, 'conf'))
    utimesSync(join(wt, 'same.txt'), new Date(), new Date(Date.now() + 5000))
    const before = gitState(wt)
    rmSync(marker, { force: true }) // the test's own `git status` (gitState) runs the filter; the extension must not
    const other = join(home, 'other')
    mkdirSync(other)
    g(other, 'init', '-q')
    const saved = process.env.GIT_DIR
    process.env.GIT_DIR = join(other, '.git') // the IDE started from a shell with GIT_DIR set
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!('900')
      assert.deepEqual(b.seen.warnings, [])
      const items = b.seen.pickers[0].items.map((i: any) => [i.label, i.description])
      assert.deepEqual(items, [['.gitattributes', '未追跡(まだコミットされていない新しいファイル)'], ['a.txt', '削除'],
        ['conf', '未追跡(まだコミットされていない新しいファイル)']]) // conf/hosts: added, then gone again
      const fork = g(wt, 'merge-base', 'origin/main', 'HEAD').trim()
      const provider = b.seen.providers.get('taskhub-diff')
      const side = (s: string, p: string) => provider.provideTextDocumentContent(b.vscode.Uri.from({ scheme: 'taskhub-diff',
        path: `/900/${s}/${p}`, query: fork }))
      assert.equal(await side('base', 'a.txt'), 'one\ntwo\n')
      assert.equal(await side('worktree', 'conf/hosts'), '') // through the symlink: outside, so not shown
      assert.equal(await side('worktree', 'conf'), join(origin, '..', 'outside')) // the link itself, as git has it
      assert.match(await side('worktree', '../x'), /worktree の外/)
      assert.match(await side('other', 'a.txt'), /base か worktree/)
      assert.equal(existsSync(marker), false)
      assert.deepEqual(gitState(wt), before)
      b.vscode.workspace.isTrusted = false // a diff tab restored in a window that is not trusted
      assert.match(await side('base', 'a.txt'), /信頼していないワークスペース/)
    } finally {
      if (saved === undefined) delete process.env.GIT_DIR
      else process.env.GIT_DIR = saved
      b.stop()
    }
  })
})

test('変更: base ではディレクトリだったパスがファイルになっても、左は空で開く', async () => {
  await withHome(null, async home => {
    const { wt, origin, clone } = taskHome(home)
    // base: dir/inner.txt; the task: dir is a file
    rmSync(join(wt, 'b.txt'))
    g(wt, 'rm', '-q', '--cached', 'b.txt')
    mkdirSync(join(origin, 'dir'))
    writeFileSync(join(origin, 'dir', 'inner.txt'), 'inner\n')
    g(origin, 'add', '-A')
    g(origin, 'commit', '-q', '-m', 'dir')
    g(clone, 'fetch', '-q')
    g(wt, 'merge', '-q', '--ff-only', 'origin/main')
    g(wt, 'rm', '-q', '-r', 'dir')
    writeFileSync(join(wt, 'dir'), 'now a file\n')
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!('900')
      const labels = b.seen.pickers[0].items.map((i: any) => i.label)
      assert.ok(labels.includes('dir') && labels.includes('dir/inner.txt'), labels.join(','))
      b.seen.pickers[0].accept('dir')
      await until(() => b.seen.executed.some(e => e[0] === 'vscode.diff'))
      const [, left, right] = b.seen.executed.find(e => e[0] === 'vscode.diff')!
      await until(() => b.seen.docs.has(right.toString()))
      assert.deepEqual([b.seen.docs.get(left.toString()).text, b.seen.docs.get(right.toString()).text], ['', 'now a file\n'])
    } finally {
      b.stop()
    }
  })
})

test('変更: 作業中の変更がない(コミットだけ)worktree でも、コミットした変更を並べる。Base branch の欄も使う', async () => {
  await withHome(null, async home => {
    const { wt, origin, clone } = taskHome(home, { base: 'release' })
    g(origin, 'branch', 'release', 'HEAD~1')
    g(clone, 'fetch', '-q')
    writeFileSync(join(wt, 'a.txt'), 'committed only\n')
    g(wt, 'commit', '-q', '-am', 'work')
    assert.equal(g(wt, 'status', '--porcelain'), '')
    const before = gitState(wt)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!('900')
      assert.match(b.seen.pickers[0].title, /← origin\/release\(/)
      assert.deepEqual(b.seen.pickers[0].items.map((i: any) => [i.label, i.description]), [['a.txt', '変更']])
      assert.deepEqual(gitState(wt), before)
    } finally {
      b.stop()
    }
  })
})

test('変更: 動いていない・片付いた worktree・信頼していないワークスペースは、理由を出して何も開かない(別の checkout を使わない)', async () => {
  await withHome(null, async home => {
    const { wt, state } = taskHome(home)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!(cardNode(b, '901'))
      assert.match(b.seen.warnings[0], /#901 はこのマシンで動いていません\(runs\/901\.json がない\)/)
      b.vscode.workspace.isTrusted = false
      await b.seen.commands.get('taskHub.task.changes')!('900')
      assert.match(b.seen.warnings[1], /信頼していないワークスペースでは git を動かさない/)
      b.vscode.workspace.isTrusted = true
      // the worktree removed by cleanup, while the clone (another checkout of the same repo) is still there
      rmSync(wt, { recursive: true, force: true })
      await b.seen.commands.get('taskHub.task.changes')!('900')
      assert.match(b.seen.warnings[2], /#900 の worktree がありません: ~\/\.local\/share\/task-hub\/worktrees\/900\(片付け済み\)/)
      writeFileSync(join(state, 'runs', '900.json'), '{"broken')
      await b.seen.commands.get('taskHub.task.changes')!('900')
      assert.match(b.seen.warnings[3], /#900 はこのマシンで動いていません/)
      await b.seen.commands.get('taskHub.task.changes')!('../900')
      assert.match(b.seen.warnings[4], /タスクの番号ではありません/)
      assert.deepEqual(b.seen.pickers, [])
      assert.equal(b.seen.executed.filter(e => e[0] === 'vscode.diff').length, 0)
    } finally {
      b.stop()
    }
  })
})

test('変更: 別のカードの変更を開いても、開いている差分のタブはもとのタスクのまま', async () => {
  await withHome(null, async home => {
    const { wt, state } = taskHome(home)
    work(wt)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.changes')!('900')
      b.seen.pickers[0].accept('a.txt')
      await until(() => b.seen.executed.some(e => e[0] === 'vscode.diff'))
      const [, left, right] = b.seen.executed.find(e => e[0] === 'vscode.diff')!
      await until(() => b.seen.docs.has(right.toString()))
      // task 901 now has a run of its own with another worktree; its list replaces the open picker, not the tabs
      const other = join(home, 'wt901')
      g(join(home, '.local', 'share', 'task-hub', 'repos', 'jyoka', 'demo'), 'worktree', 'add', '-q', '-b', 'task/901', other, 'origin/main')
      writeFileSync(join(other, 'a.txt'), 'task 901\n')
      writeFileSync(join(state, 'runs', '901.json'), JSON.stringify({ repo: 'jyoka/demo', branch: 'task/901', worktree: other }))
      await b.seen.commands.get('taskHub.task.changes')!('901')
      assert.equal(b.seen.pickers[0].visible, false)
      assert.equal(b.seen.pickers[0].disposed, true)
      assert.match(b.seen.pickers[1].title, /^#901 Changes/)
      assert.equal(b.seen.docs.get(right.toString()).text, 'one\nTWO\n')
      assert.equal(b.seen.docs.get(left.toString()).text, 'one\ntwo\n')
      assert.match(right.toString(), /^taskhub-diff:\/900\//)
    } finally {
      b.stop()
    }
  })
})

test('ログ: 読み取り専用のタブで開き、追う間は新しい行へ送り、止めると表示も位置も変えない。フォーカスは奪わない', async () => {
  await withHome(null, async home => {
    const { log } = taskHome(home)
    writeFileSync(log, '== start\nline 1\n')
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.log')!(cardNode(b, '900'))
      const key = 'taskhub-log:/900/#900 Log · demo.log'
      assert.equal(b.seen.shown[0].uri, key)
      const doc = b.seen.docs.get(key)
      const editor = b.seen.editors[0]
      assert.equal(doc.text, '== start\nline 1\n')
      assert.deepEqual(editor.revealed, [2])
      assert.equal(b.seen.context.get('taskHub.logFollowing'), true)

      appendFileSync(log, 'line 2\n')
      await until(() => doc.text.endsWith('line 2\n'))
      await until(() => editor.revealed.at(-1) === 3)
      assert.equal(b.seen.shown.length, 1) // never shown again: the focus stays where the user is

      await b.seen.commands.get('taskHub.log.pause')!(doc.uri)
      assert.equal(b.seen.context.get('taskHub.logFollowing'), false)
      const revealed = editor.revealed.length
      appendFileSync(log, 'line 3\n')
      await new Promise(r => setTimeout(r, 2500)) // two looks of fs.watchFile
      assert.equal(doc.text, '== start\nline 1\nline 2\n')
      assert.equal(editor.revealed.length, revealed)

      await b.seen.commands.get('taskHub.log.follow')!(doc.uri)
      await until(() => doc.text.endsWith('line 3\n'))
      await until(() => editor.revealed.at(-1) === 4)
      assert.equal(b.seen.context.get('taskHub.logFollowing'), true)
      assert.equal(b.seen.shown.length, 1)

      // back in view after another tab was in front: a following log shows its end
      editor.revealed.length = 0
      for (const l of b.seen.onVisible) l([editor])
      assert.deepEqual(editor.revealed, [4])

      // the tab closed (the document may stay): the file is no longer looked at
      b.close(key)
      const provided = b.seen.provided.length
      appendFileSync(log, 'line 4\n')
      await new Promise(r => setTimeout(r, 2500))
      assert.equal(b.seen.provided.length, provided)
    } finally {
      b.stop()
    }
  })
})

test('ログ: 閉じたあとに戻ってきたタブ(閉じたエディターを開き直す、ウィンドウの復元)も追い、止められる', async () => {
  await withHome(null, async home => {
    const { log } = taskHome(home)
    writeFileSync(log, 'line 1\n')
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.log')!('900')
      const key = 'taskhub-log:/900/#900 Log · demo.log'
      const doc = b.seen.docs.get(key)
      b.close(key)

      // Reopen Closed Editor: the same URI comes back as a tab, without the Log command
      const editor = await b.vscode.window.showTextDocument(doc, { preview: false })
      appendFileSync(log, 'line 2\n')
      await until(() => doc.text.endsWith('line 2\n'))
      await until(() => editor.revealed.at(-1) === 2)
      assert.equal(b.seen.context.get('taskHub.logFollowing'), true)
      await b.seen.commands.get('taskHub.log.pause')!(doc.uri)
      appendFileSync(log, 'line 3\n')
      await new Promise(r => setTimeout(r, 2500))
      assert.equal(doc.text, 'line 1\nline 2\n')
      await b.seen.commands.get('taskHub.log.follow')!(doc.uri)
      await until(() => doc.text.endsWith('line 3\n'))

      // a window that restores the tab before the extension hears of it: its 'follow' button still works
      b.close(key)
      const restored = { document: doc, revealed: [] as number[], revealRange(r: any) { this.revealed.push(r.start.line) } }
      b.vscode.window.visibleTextEditors.push(restored)
      b.vscode.window.activeTextEditor = restored
      appendFileSync(log, 'line 4\n')
      await b.seen.commands.get('taskHub.log.follow')!()
      await until(() => doc.text.endsWith('line 4\n'))
      await until(() => restored.revealed.at(-1) === 4)
      assert.equal(b.seen.context.get('taskHub.logFollowing'), true)
      appendFileSync(log, 'line 5\n')
      await until(() => doc.text.endsWith('line 5\n'))
    } finally {
      b.stop()
    }
  })
})

test('ログ: まだないログはそう書いて待ち、できたら出す。拡張を止めたら見るのをやめる', async () => {
  await withHome(null, async home => {
    const { log } = taskHome(home)
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.log')!('900')
      const doc = b.seen.docs.get(b.seen.shown[0].uri)
      assert.match(doc.text, /^\(task-hub: #900 のログはまだありません: ~\/\.local\/state\/task-hub\/logs\/900\.log。/)
      writeFileSync(log, 'started\n')
      await until(() => doc.text === 'started\n')
      // a card that never ran here: its own log path (state/logs/901.log), never another task's
      await b.seen.commands.get('taskHub.task.log')!('901')
      assert.match(b.seen.docs.get(b.seen.shown[1].uri).text, /#901 のログはまだありません: ~\/\.local\/state\/task-hub\/logs\/901\.log/)
    } finally {
      b.stop()
    }
    const provided = b.seen.provided.length
    appendFileSync(log, 'more\n')
    await new Promise(r => setTimeout(r, 2500))
    assert.equal(b.seen.provided.length, provided)
  })
})

test('ログ: 大きいログは最後の 1 MB だけを、そう書いて出す', async () => {
  await withHome(null, async home => {
    const { log } = taskHome(home)
    writeFileSync(log, 'old line\n'.repeat(200_000) + 'the end\n')
    const b = start(inspectRun)
    try {
      await b.refresh()
      await b.seen.commands.get('taskHub.task.log')!('900')
      const text = b.seen.docs.get(b.seen.shown[0].uri).text
      assert.match(text, /^\(task-hub: 1800008 バイトのうち、最後の 1048576 バイトです。全部は ~\/\.local\/state\/task-hub\/logs\/900\.log\)\nold line\n/)
      assert.ok(text.endsWith('old line\nthe end\n'))
      assert.ok(text.length <= 1024 * 1024 + 200)
    } finally {
      b.stop()
    }
  })
})
