// Runs the built out/extension.js (what goes in the VSIX) against a stand-in for the `vscode` module.
import assert from 'node:assert/strict'
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import Module, { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, test } from 'node:test'

import { ROOT, build } from '../scripts/build.mjs'
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

// Just what the extension uses of the VS Code API, recording what it was given.
const fakeVscode = () => {
  const seen = { trees: [] as any[], bars: [] as any[], commands: new Map<string, (...args: any[]) => unknown>(),
    opened: [] as string[] }
  class EventEmitter {
    listeners: Array<() => void> = []
    event = (l: () => void) => (this.listeners.push(l), { dispose() {} })
    fire() { for (const l of this.listeners) l() }
    dispose() {}
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
  const vscode = {
    EventEmitter, TreeItem, ThemeIcon, ThemeColor, MarkdownString, StatusBarAlignment: { Left: 1, Right: 2 },
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
    Uri: { parse: (url: string) => ({ url }) },
    env: { openExternal: async (uri: { url: string }) => (seen.opened.push(uri.url), true) },
    window: {
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
    },
    commands: {
      registerCommand: (id: string, fn: (...args: any[]) => unknown) => (seen.commands.set(id, fn), { dispose() {} }),
    },
  }
  return { vscode, seen }
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

const start = (run: () => Promise<unknown>, read: () => Promise<unknown> = NO_FILES) => {
  const { vscode, seen } = fakeVscode()
  const ext = load(vscode)
  const context = { subscriptions: [] as Array<{ dispose(): void }> }
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
  return { seen, view, stop, refresh: () => seen.commands.get('taskHub.board.refresh')!() as Promise<void> }
}

test('ビューに並べ、ステータスバーに数を出し、更新ボタンで task list を読み直す', async () => {
  let runs = 0
  const { seen, view, stop, refresh } = start(async () => (runs++, { exitCode: 0, stdout: LIST, stderr: '' }))
  try {
    assert.equal(seen.trees[0].id, 'taskHub.board')
    await refresh() // the run started by activate: the button waits for it instead of starting another
    assert.equal(runs, 1)
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
  const context = { subscriptions: [] as Array<{ dispose(): void }> }
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

test('素の task を呼ぶコードがない: プロセスを起動するのは execFile(taskPath(), [\'list\']) の 1 か所だけ', () => {
  const dir = build(temp())
  const sources = [...readdirSync(join(ROOT, 'src')).map(f => join(ROOT, 'src', f)),
    ...readdirSync(dir).map(f => join(dir, f))]
  const calls = sources.flatMap(f => readFileSync(f, 'utf8').match(/\b(execFile|execFileSync|exec|execSync|spawn|spawnSync|fork)\(.*/g) ?? [])
  assert.equal(calls.length, 2) // src/extension.ts and out/extension.js
  for (const call of calls) assert.match(call, /^execFile\(task, \['list'\], /)
  for (const f of sources) {
    const text = readFileSync(f, 'utf8')
    if (/const task = /.test(text)) assert.match(text, /const task = taskPath\(\)/)
  }
})

test('package.json: 信頼していないワークスペースでも動く、engines は Kiro 1.2.4 の 1.131.0 以下', () => {
  const p = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  assert.equal(p.capabilities.untrustedWorkspaces.supported, true)
  const [major, minor] = p.engines.vscode.replace(/^\^/, '').split('.').map(Number)
  assert.ok(major === 1 && minor <= 131)
  assert.equal(p.main, './out/extension.js')
  assert.deepEqual(p.dependencies ?? {}, {})
  assert.ok(p.contributes.menus['view/title'].some((m: any) => m.command === 'taskHub.board.refresh' && m.when === 'view == taskHub.board'))
})
