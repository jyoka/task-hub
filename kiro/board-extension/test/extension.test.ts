// Runs the built out/extension.js (what goes in the VSIX) against a stand-in for the `vscode` module.
import assert from 'node:assert/strict'
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import Module, { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, test } from 'node:test'

import { ROOT, build } from '../scripts/build.mjs'
import { LIST } from './fixtures.ts'

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
  const seen = { trees: [] as any[], bars: [] as any[], commands: new Map<string, () => Promise<void>>() }
  class EventEmitter {
    listeners: Array<() => void> = []
    event = (l: () => void) => (this.listeners.push(l), { dispose() {} })
    fire() { for (const l of this.listeners) l() }
    dispose() {}
  }
  class TreeItem {
    label: string
    constructor(label: string) { this.label = label }
  }
  class ThemeIcon {
    id: string
    constructor(id: string) { this.id = id }
  }
  class ThemeColor extends ThemeIcon {}
  const vscode = {
    EventEmitter, TreeItem, ThemeIcon, ThemeColor, StatusBarAlignment: { Left: 1, Right: 2 },
    window: {
      createTreeView: (id: string, { treeDataProvider }: any) => {
        const tree = { id, provider: treeDataProvider, description: '', dispose() {} }
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
      registerCommand: (id: string, fn: () => Promise<void>) => (seen.commands.set(id, fn), { dispose() {} }),
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

const start = (run: () => Promise<unknown>) => {
  const { vscode, seen } = fakeVscode()
  const ext = load(vscode)
  const context = { subscriptions: [] as Array<{ dispose(): void }> }
  ext.activate(context, run)
  const view = () => {
    const tree = seen.trees[0]
    return tree.provider.getChildren().map((r: unknown) => tree.provider.getTreeItem(r))
  }
  const stop = () => { for (const d of context.subscriptions) d.dispose() }
  return { seen, view, stop, refresh: () => seen.commands.get('taskHub.board.refresh')!() }
}

test('ビューに並べ、ステータスバーに数を出し、更新ボタンで task list を読み直す', async () => {
  let runs = 0
  const { seen, view, stop, refresh } = start(async () => (runs++, { exitCode: 0, stdout: LIST, stderr: '' }))
  try {
    assert.equal(seen.trees[0].id, 'taskHub.board')
    await refresh() // the run started by activate: the button waits for it instead of starting another
    assert.equal(runs, 1)
    const items = view()
    assert.deepEqual(items.map((i: any) => i.label.match(/^#(\d+) /)?.[1]), ['110', '75', '90', '109', '128', '111', '64', '200'])
    assert.equal(items[0].description, 'Blocked · 待ち: #109')
    assert.equal(items[0].iconPath.id, 'error')
    assert.equal(items[3].description, 'In progress')
    assert.equal(items[4].description, 'In progress › review')
    assert.match(seen.trees[0].description, /^\d\d:\d\d 時点$/)
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
