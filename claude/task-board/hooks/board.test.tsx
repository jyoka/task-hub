import { expect, mock, test } from 'claude-code/testing'

import { CASES as cases } from './slow-threshold.cases'
import { parseList, summary } from './parse'
import { FOLDED, clip, defaultAgent, isFolded, minutes, repoTag, slowThreshold, toggleFold } from './panel'

const PANE = {
  title: 'task-hub', isFocused: false, bodyColumns: 80, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 20 }, view: {},
}

const LIST = `counts: Backlog=1, Ready=0, In progress=2, In review=1, wait for merge=1, Blocked=1
tasks[6]{id,title,status,repo,agent,waits_for}:
  "64","aica v1: Render 公開とデプロイ smoke(HITL)",Backlog,jyoka/aica,"",""
  "75",Test kiro automation workflow,In review,jyoka/task-hub,kiro,""
  "109","aica v2 (H): 完了時の計測",In progress,jyoka/aica,"",""
  "128",Claude Code 用のボード表示 mod,In progress › review,jyoka/task-hub,kiro,""
  "90",merge を待つカード,wait for merge,jyoka/task-hub,"",""
  "110","画面, 検索",Blocked,jyoka/aica,"","#109"
needs_you: 3 (Backlog to approve, In review, Blocked)
`

const NOW = Date.parse('2026-10-04T10:12:00Z')
const EVENTS = [
  { time: '2026-10-04T08:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'In progress' },
  { time: '2026-10-04T09:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'Blocked', reason: 'old' },
  { time: '2026-10-04T10:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'In progress' },
  { time: '2026-10-04T09:37:00Z', id: '128', title: 'mod', repo: 'jyoka/task-hub', event: 'In progress' },
  { time: '2026-10-04T09:50:00Z', id: '75', title: 'kiro', repo: 'jyoka/task-hub', event: 'In review',
    pr: 'https://github.com/jyoka/task-hub/pull/36', digest: { verdict: 'needs changes', review: ['a'] } },
  { time: '2026-10-04T09:55:00Z', id: '110', title: '画面', repo: 'jyoka/aica', event: 'Blocked',
    reason: `前提の PR #26 がまだマージされていない\n${'とても長い説明。'.repeat(30)}` },
].map(e => JSON.stringify(e)).join('\n') + '\n{"time": "2026-10-04T10:1\n1\n[]\n'
// claude (the [runner] agent of card 109) usually takes 9 minutes; kiro has too few runs for a usual time
const METRICS = [480, 540, 600].map(s => JSON.stringify({ agent: 'claude', seconds: s, status: 'In review' }))
  .concat([JSON.stringify({ agent: 'kiro', seconds: 60, status: 'In review' }), 'not json']).join('\n')
const CONFIG = '[board]\nproject = jyoka/2\n[runner]\nagent = claude ; the default\n'

const files = (on: Parameters<Parameters<typeof test>[1]>[1], found: Record<string, string>, read: string[] = []) =>
  on('fs.read', async ($, e) => {
    read.push(e.path)
    const text = found[e.path]
    if (text === undefined) throw new Error(`ENOENT: no such file or directory, open '${e.path}'`)
    return { value: text }
  })

const taskList = (on: Parameters<Parameters<typeof test>[1]>[1], ran: string[][] = []) =>
  on('process.run', async ($, e) => {
    ran.push([...e.argv])
    return { value: { exitCode: 0, stdout: LIST, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

const ALL = {
  '/home/me/.local/state/task-hub/events.jsonl': EVENTS,
  '/home/me/.local/state/task-hub/metrics.jsonl': METRICS,
  '/home/me/.config/task-hub/config.ini': CONFIG,
}

test('task list の出力を読む', () => {
  const b = parseList(LIST, '11:00')
  expect(b.counts['In review']).toBe(1)
  expect(b.cards.length).toBe(6)
  expect(b.cards[0]?.title).toBe('aica v1: Render 公開とデプロイ smoke(HITL)')
  expect(b.cards[1]?.agent).toBe('kiro')
  expect(b.cards[5]).toEqual({ id: '110', title: '画面, 検索', status: 'Blocked', repo: 'jyoka/aica', agent: '', waitsFor: '#109' })
  expect(summary(b)).toBe('task: 実行中2 レビュー待ち1 止まり1')
  expect(summary(parseList('counts: Backlog=2, In progress=0\n', '11:00'))).toBeUndefined()
})

test('引用された値は JSON 文字列として読む(bin/task の q() は json.dumps)', () => {
  const title = 'say "hi", C:\\path'
  const b = parseList(`counts: Blocked=1\n  "1",${JSON.stringify(title)},Blocked,jyoka/x,"",""\n`, '11:00')
  expect(b.cards).toEqual([{ id: '1', title, status: 'Blocked', repo: 'jyoka/x', agent: '', waitsFor: '' }])
})

test('普段の時間は bin/task の slow_threshold と同じ(tests/test_task.py も同じ表で確かめる)', () => {
  const metrics = cases.metrics.join('\n')
  for (const [agent, [limit, usual]] of Object.entries(cases.cases)) {
    expect([agent, slowThreshold(metrics, agent)]).toEqual([agent, { limit, usual }])
  }
  expect(slowThreshold('', 'claude')).toEqual({ limit: 1800, usual: null })
})

test('分は Python の round と同じ丸め、repo タグは owner を外して repo ごとに同じ色', () => {
  expect([minutes(89), minutes(90), minutes(150), minutes(540), minutes(3600), minutes(4500)])
    .toEqual(['1分', '2分', '2分', '9分', '1時間', '1時間15分'])
  expect(repoTag('jyoka/aica').name).toBe('aica')
  expect(repoTag('jyoka/aica').color).toBe(repoTag('jyoka/aica').color)
  expect(new Set(['jyoka/aica', 'jyoka/task-hub', 'jyoka/aica_ra_a2a_poc', 'x/y'].map(r => repoTag(r).color)).size)
    .toBeGreaterThan(1)
  expect(defaultAgent('')).toBe('claude')
  expect(defaultAgent('[runner]\nreviewer = agent\nAgent: kiro # mine\n[agents]\nagent = x\n')).toBe('kiro')
  // a CJK character takes two cells
  expect(clip('画面と検索の改善', 9)).toBe('画面と検…')
  expect(clip('abc', 3)).toBe('abc')
})

test('ペインは列ごとにまとめ、色・経過時間・判定・PR・理由・repo タグを出す', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  const ran: string[][] = []
  taskList(on, ran)
  const read: string[] = []
  files(on, ALL, read)
  const statuses: unknown[] = []
  on('ui.status', async ($, e) => (statuses.push(e), { value: undefined }))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: PANE })
    await ui.press({ key: 'refresh' })

    // A: needs-you and running are framed groups with a heading and a count; Backlog starts folded into one line
    const boxes = await ui.findAll({ type: 'Box' })
    const needs = boxes.find(x => x.key === 'needs-you')
    const running = boxes.find(x => x.key === 'running')
    expect([needs?.props.borderStyle, needs?.props.borderColor]).toEqual(['round', 'red'])
    expect([running?.props.borderStyle, running?.props.borderColor]).toEqual(['round', 'cyan'])
    expect(await ui.find({ type: 'Text', text: /^要対応 3$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^実行中 2$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^Backlog 1$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^ {2}#64$/ })).toBeDefined()
    expect((await ui.findAll({ type: 'Button', text: /^[▾▸]$/ })).map(x => [x.key, x.text]))
      .toEqual([['fold-needs-you', '▾'], ['fold-running', '▾'], ['fold-backlog', '▸']])
    expect(boxes.flatMap(x => x.key?.match(/^card-(\d+)$/)?.[1] ?? [])).toEqual(['110', '75', '90', '109', '128'])
    expect(await ui.find({ type: 'Text', text: /^Blocked +aica  #110 画面, 検索 \(待ち: #109\)$/ })).toBeDefined()

    // B: each column its color; a running card's stage is a small label
    const blocked = await ui.find({ type: 'Text', text: /^Blocked *$/ })
    expect(blocked?.props.color).toBe('red')
    expect((await ui.find({ type: 'Text', text: /^In review *$/ }))?.props.color).toBe('yellow')
    const stageLabel = await ui.find({ type: 'Text', text: /^ review $/ })
    expect([stageLabel?.props.color, stageLabel?.props.inverse]).toEqual(['cyan', true])

    // C: 12 minutes since its last In progress, 9 the usual for claude: past it, so yellow;
    // kiro has no usual time yet, and 35 minutes is past bin/task's 30, so red
    const late = await ui.find({ type: 'Text', text: '12分 / 普段9分' })
    expect(late?.props.color).toBe('yellow')
    expect((await ui.find({ type: 'Text', text: '35分 / 普段 不明' }))?.props.color).toBe('red')

    // D: the verdict and a link to the PR; the Blocked reason on one line, cut to the pane
    expect((await ui.find({ type: 'Text', text: 'needs changes' }))?.props.color).toBe('yellow')
    const link = await ui.find({ type: 'Link' })
    expect([link?.props.href, link?.props.label]).toEqual(['https://github.com/jyoka/task-hub/pull/36', 'PR #36'])
    const reason = await ui.find({ type: 'Text', text: /前提の PR #26/ })
    expect(reason?.text).toMatch(/^ {4}前提の PR #26 がまだマージされていない とても長い説明。.*…$/)
    expect(reason?.text.includes('old')).toBe(false)

    // E: the repo without its owner, in the repo's color
    const tag = await ui.find({ type: 'Text', text: /^ aica $/ })
    expect([tag?.props.color, tag?.props.inverse]).toEqual([repoTag('jyoka/aica').color, true])
    expect(await ui.find({ type: 'Text', text: /^ task-hub $/ })).toBeDefined()
    await ui.unmount()
  }
  expect(ran.every(argv => argv.join(' ') === '/home/me/.local/bin/task list')).toBe(true)
  expect(read).toContain('/home/me/.local/state/task-hub/events.jsonl')
  expect(read).toContain('/home/me/.local/state/task-hub/metrics.jsonl')
  expect(JSON.stringify(statuses.at(-1))).toContain('task: 実行中2 レビュー待ち1 止まり1')
})

test('タイトルは狭いペインの幅に合わせて切る', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  taskList(on)
  files(on, ALL)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board',
      props: { ...PANE, bodyColumns: 36 } })
    await ui.press({ key: 'refresh' })
    const row = await ui.find({ type: 'Text', text: / #64 / })
    expect(row).toBeUndefined() // Backlog is folded
    const running = await ui.find({ type: 'Text', text: / #109 / })
    expect(running?.text).toMatch(/ #109 aica v2 \(H…$/)
    await ui.unmount()
  }
})

test('events.jsonl と metrics.jsonl がない、または読めないときも、ペインはこれまでどおり出る', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  taskList(on)
  files(on, {}) // missing, or over 4 MiB: $.fs.read rejects both
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: PANE })
    await ui.press({ key: 'refresh' })
    const rows = await ui.findAll({ type: 'Text', text: / #\d+ / })
    expect(rows.flatMap(r => r.text.match(/ #(\d+) /)?.[1] ?? [])).toEqual(['110', '75', '90', '109', '128'])
    expect(await ui.findAll({ text: /分 \/ 普段/ })).toEqual([])
    expect(await ui.findAll({ type: 'Link' })).toEqual([])
    await ui.unmount()
  }
})

test('壊れた行だけの events.jsonl でも、ペインは出る', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  taskList(on)
  files(on, {
    '/home/me/.local/state/task-hub/events.jsonl': '{"time": "2026-\n\u0000\nnull\n"id"\n{"id": 109, "event": "In progress"}\n',
    '/home/me/.local/state/task-hub/metrics.jsonl': '{{{',
  })
  const ui = await $.ui.mount({ plugin: 'task-board', surface: 'terminal', component: 'Pane', requestId: 'task-board', props: PANE })
  await ui.press({ key: 'refresh' })
  expect(await ui.find({ type: 'Text', text: /^要対応 3$/ })).toBeDefined()
  expect(await ui.findAll({ text: /分 \/ 普段/ })).toEqual([])
  await ui.unmount()
})

test('task list が失敗したら、stdout の error: 行を理由として出す', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: 0 })
  const stdout = 'error: the board is not configured in ~/.config/task-hub/config.ini\nhelp: add:  [board]  project = <owner>/<project number>\n'
  on('process.run', async () => ({ value: { exitCode: 1, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  const statuses: unknown[] = []
  on('ui.status', async ($, e) => (statuses.push(e), { value: undefined }))
  const ui = await $.ui.mount({ plugin: 'task-board', surface: 'terminal', component: 'Pane', requestId: 'task-board', props: PANE })
  await ui.press({ key: 'refresh' })
  expect(await ui.find({ text: '読めませんでした: the board is not configured in ~/.config/task-hub/config.ini' })).toBeDefined()
  expect(await ui.findAll({ text: /開いているカードはありません/ })).toEqual([])
  await ui.unmount()
  expect(JSON.stringify(statuses.at(-1))).toContain('task: 読めない')
})

test('見出しを押すとグループを開け閉めし、$.store に覚える: Backlog も 1 枚ずつ出せる', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  taskList(on)
  files(on, ALL)
  const kept = new Map<string, unknown>()
  const writes: [string, unknown][] = []
  on('store.get', async ($, e) => ({ value: kept.get(e.key) }))
  on('store.set', async ($, e) => (writes.push([e.key, e.value]), kept.set(e.key, e.value), { value: undefined }))
  for (const surface of ['terminal', 'desktop'] as const) {
    kept.clear()
    writes.length = 0
    const mount = () => $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: PANE })
    const cardIds = async (ui: Awaited<ReturnType<typeof mount>>) =>
      (await ui.findAll({ type: 'Box' })).flatMap(x => x.key?.match(/^card-(\d+)$/)?.[1] ?? [])
    let ui = await mount()
    await ui.press({ key: 'refresh' })

    // Backlog opens into cards: the repo tag, #id and title, with no "Backlog" label (the heading says it)
    await ui.press({ key: 'fold-backlog' })
    expect(await cardIds(ui)).toEqual(['110', '75', '90', '109', '128', '64'])
    const row = await ui.find({ type: 'Text', text: / #64 / })
    expect(row?.text).toBe(' aica  #64 aica v1: Render 公開とデプロイ smoke(HITL)')
    expect((await ui.findAll({ type: 'Box' })).find(x => x.key === 'backlog')?.props.borderColor).toBe('gray')
    expect(writes.filter(w => w[0] === 'folded')).toEqual([['folded', ['other']]])

    // needs-you folds to its ids
    await ui.press({ key: 'fold-needs-you' })
    expect(await cardIds(ui)).toEqual(['109', '128', '64'])
    expect(await ui.find({ type: 'Text', text: /^ {2}#110 #75 #90$/ })).toBeDefined()
    expect(writes.at(-1)).toEqual(['folded', ['other', 'needs-you']])
    await ui.unmount()

    // the next session reads the choice back from the store
    ui = await mount()
    await ui.press({ key: 'refresh' })
    expect(await cardIds(ui)).toEqual(['109', '128', '64'])
    await ui.unmount()
  }
})

test('最初は Backlog とその他だけ閉じ、待ちは列の名前なしで 1 枚ずつ出す', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: NOW })
  const list = `counts: Backlog=1, Ready=1, Triage=1
tasks[3]{id,title,status,repo,agent,waits_for}:
  "64",Backlog のカード,Backlog,jyoka/aica,"",""
  "70",待ちのカード,Ready,jyoka/aica,"","#64 (Backlog)"
  "80",知らない列のカード,Triage,jyoka/aica,"",""
`
  on('process.run', async () => ({ value: { exitCode: 0, stdout: list, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  files(on, {})
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: PANE })
    await ui.press({ key: 'refresh' })
    expect((await ui.findAll({ type: 'Button', text: /^[▾▸]$/ })).map(x => [x.key, x.text]))
      .toEqual([['fold-ready', '▾'], ['fold-backlog', '▸'], ['fold-other', '▸']])
    expect((await ui.findAll({ type: 'Box' })).flatMap(x => x.key?.match(/^card-(\d+)$/)?.[1] ?? [])).toEqual(['70'])
    expect((await ui.find({ type: 'Text', text: / #70 / }))?.text).toBe(' aica  #70 待ちのカード (待ち: #64 (Backlog))')
    expect(await ui.find({ type: 'Text', text: /^ {2}#80$/ })).toBeDefined()
    await ui.unmount()
  }
})

test('閉じたグループは、カードがなくなっても閉じたまま覚える', () => {
  expect(FOLDED).toEqual(['backlog', 'other'])
  // pressing a heading for the first time starts from the defaults, even when Backlog has no cards now
  const first = toggleFold('running', null)
  expect(first).toEqual(['backlog', 'other', 'running'])
  expect(isFolded('backlog', first)).toBe(true)
  // Ready folded, then empty: pressing another heading keeps it folded for when it has cards again
  const later = toggleFold('needs-you', toggleFold('ready', []))
  expect(later).toEqual(['ready', 'needs-you'])
  expect(toggleFold('ready', later)).toEqual(['needs-you'])
})
