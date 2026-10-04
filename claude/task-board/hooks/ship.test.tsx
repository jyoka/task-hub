import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import type { Card } from '../types'
import { BADGES, earned, fresh } from './badges'
import { parseList } from './parse'
import { ROWS, cells, deck, drop, pose, scene, tiltFor } from './ship'

const PANE = {
  title: 'task-hub', isFocused: false, bodyColumns: 80, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 40 }, view: {},
}
const MOUNT = { plugin: 'task-board', component: 'Pane', requestId: 'task-board', props: PANE } as const

const LIST = `counts: Backlog=1, Ready=2, In progress=3, In review=2, wait for merge=1, Blocked=1
tasks[10]{id,title,status,repo,agent,waits_for}:
  "64",Backlog のカード,Backlog,jyoka/aica,"",""
  "70",待ち 1,Ready,jyoka/aica,"",""
  "71",待ち 2,Ready,jyoka/task-hub,"",""
  "109",作業中,In progress › agent,jyoka/aica,"",""
  "128",レビュー中,In progress › review,jyoka/task-hub,kiro,""
  "130",やり直し中,In progress › retry,jyoka/task-hub,"",""
  "75",レビュー待ち 1,In review,jyoka/task-hub,kiro,""
  "76",レビュー待ち 2,In review,jyoka/task-hub,"",""
  "90",マージ待ち,wait for merge,jyoka/task-hub,"",""
  "110",止まっている,Blocked,jyoka/aica,"","#109"
`
const HOME = '/home/me'
const METRICS_PATH = `${HOME}/.local/state/task-hub/metrics.jsonl`

const taskList = (on: On, stdout = LIST) =>
  on('process.run', async () => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
const files = (on: On, found: Record<string, string>) =>
  on('fs.read', async ($, e) => {
    const text = found[e.path]
    if (text === undefined) throw new Error(`ENOENT: no such file or directory, open '${e.path}'`)
    return { value: text }
  })
const toasts = (on: On, seen: string[]) => on('ui.toast', async ($, e) => (seen.push(String(e.text)), { value: undefined }))
// $.store in memory, as mock.store keeps it, recording each write
const stores = (on: On, writes: [string, unknown][]) => {
  const kept = new Map<string, unknown>()
  on('store.get', async ($, e) => ({ value: kept.get(e.key) }))
  on('store.set', async ($, e) => (writes.push([e.key, e.value]), kept.set(e.key, e.value), { value: undefined }))
}
// What a session start needs beneath the plugin: the slash command it registers
const session = (on: On) => {
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('command.register', async ($, e) => ({ value: { command: e.name } }))
}

const card = (id: string, status: string): Card => ({ id, title: `t${id}`, status, repo: 'jyoka/x', agent: '', waitsFor: '' })

test('カードの状態から場面を決める: 乗組員と姿、荷と傾き、SOS、桟橋', () => {
  const s = scene(parseList(LIST, '11:00').cards)
  expect(s.crew.map(f => [f.id, f.pose])).toEqual([['109', 'work'], ['128', 'review'], ['130', 'retry']])
  expect(s.cargo.map(f => f.id)).toEqual(['75', '76', '90'])
  expect(s.tilt).toBe(1)
  expect([s.sos, s.stuck.map(f => f.id)]).toEqual([true, ['110']])
  expect(s.pier.map(f => `#${f.id} ${f.title}`)).toEqual(['#70 待ち 1', '#71 待ち 2'])

  // 0-1 crates: level; 2-3: a little; 4 or more: hard
  expect([0, 1, 2, 3, 4, 9].map(tiltFor)).toEqual([0, 0, 1, 1, 2, 2])
  expect(scene([card('1', 'In review'), card('2', 'wait for merge'), card('3', 'In review'), card('4', 'In review')]).tilt).toBe(2)
  expect(scene([card('1', 'wait for merge')]).tilt).toBe(0)

  // Backlog is not on the picture; no Blocked card, no SOS; a stage the mod does not know stands idle
  const calm = scene([card('1', 'Backlog'), card('2', 'In progress › setup'), card('3', 'In progress')])
  expect([calm.sos, calm.stuck, calm.cargo, calm.pier]).toEqual([false, [], [], []])
  expect(calm.crew.map(f => f.pose)).toEqual(['idle', 'idle'])
  expect([pose('In progress › agent'), pose('In progress › finishing')]).toEqual(['work', 'idle'])
})

test('絵は傾きと荷で変わり、文字の絵は船尾ほど下がる', () => {
  const level = scene([card('1', 'In review')])
  const heavy = scene(['1', '2', '3', '4', '5'].map(id => card(id, 'In review')))
  expect(cells(level, 40, 0)).not.toBe(cells(heavy, 40, 0))
  // RasterProps.cells: 12 bytes a cell, base64
  expect(cells(level, 40, 0).length).toBe(Math.ceil((40 * ROWS * 12) / 3) * 4)
  // the waves move from frame to frame
  expect(cells(level, 40, 0)).not.toBe(cells(level, 40, 1))
  // a narrow pane still draws, whatever is aboard
  expect(cells(scene(parseList(LIST, '11:00').cards), 24, 3).length).toBe(Math.ceil((24 * ROWS * 12) / 3) * 4)

  const cols = deck(heavy)
  expect(cols.map(c => c.kind)).toEqual(['end', 'mast', 'cargo', 'cargo', 'cargo', 'cargo', 'cargo', 'end'])
  expect(cols.map((c, i) => drop(heavy.tilt, i, cols.length))).toEqual([0, 0, 1, 1, 1, 1, 2, 2])
  expect(deck(level).map((c, i, all) => drop(level.tilt, i, all.length))).toEqual([0, 0, 0, 0])
  expect(deck(scene([card('9', 'Blocked')]))[2]?.lines[0]).toBe('🆘')
})

// The code points of a Raster's cells, one string per row (RasterProps.cells: 12 bytes a cell, base64)
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const rows = (b64: string, columns: number): string[] => {
  const bytes: number[] = []
  for (let i = 0; i < b64.length; i += 4) {
    const q = [...b64.slice(i, i + 4)].map(ch => ch === '=' ? 0 : B64.indexOf(ch))
    const n = (q[0]! << 18) | (q[1]! << 12) | (q[2]! << 6) | q[3]!
    bytes.push((n >> 16) & 255, (n >> 8) & 255, n & 255)
  }
  const view = new DataView(new Uint8Array(bytes).buffer)
  return Array.from({ length: ROWS }, (_, r) => Array.from({ length: columns }, (_, x) =>
    String.fromCodePoint(view.getUint32((r * columns + x) * 12, true))).join(''))
}

test('SOS の旗は、船が大きく傾いても、どのコマでも上の端で切れずに読める', () => {
  const many = (n: number, status: string, from: number) =>
    Array.from({ length: n }, (_, i) => card(String(from + i), status))
  const cases = [
    [1, 0, 4], [1, 0, 8], [2, 0, 8], [1, 1, 4], [1, 5, 8], [1, 0, 2], [1, 0, 0], [2, 5, 3],
  ].map(([stuck, crew, cargo]) =>
    [...many(stuck!, 'Blocked', 100), ...many(crew!, 'In progress › agent', 200), ...many(cargo!, 'In review', 300)])
  for (const cards of cases) for (const columns of [24, 40, 64, 80]) for (let frame = 0; frame < 12; frame++) {
    const drawn = rows(cells(scene(cards), columns, frame), columns)
    const where = `${cards.map(c => c.status[0]).join('')} ${columns} 列 ${frame} コマ`
    expect([where, drawn.some(row => row.includes('SOS'))]).toEqual([where, true])
  }
})

test('船はパネルの上に、terminal では Raster、desktop では文字の絵で出て、ホバーで #番号 タイトル', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  mock.store(on)
  taskList(on)
  files(on, {})
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...MOUNT, surface })
    await ui.press({ key: 'refresh' })
    const raster = await ui.find({ type: 'Raster' })
    if (surface === 'terminal') {
      expect([raster?.key, raster?.props.columns, raster?.props.rows]).toEqual(['ship', 64, ROWS])
    } else {
      expect(raster).toBeUndefined()
      expect(await ui.findAll({ type: 'Text', text: '👷' })).toHaveLength(3)
      expect((await ui.findAll({ type: 'Text', text: /^(🔨|🔍|💦)$/ })).map(t => t.text)).toEqual(['🔨', '🔍', '💦'])
      expect(await ui.findAll({ type: 'Text', text: '📦' })).toHaveLength(3)
      expect(await ui.find({ type: 'Text', text: '🆘' })).toBeDefined()
      expect(await ui.findAll({ type: 'Text', text: '🧍' })).toHaveLength(2)
      expect((await ui.find({ key: 'ship-crew-128' }))).toBeDefined()
    }
    // who is aboard, by #id, both surfaces; the list from #137 follows below, unchanged
    expect(await ui.find({ type: 'Text', text: ' (少し傾いている)' })).toBeDefined()
    expect((await ui.findAll({ type: 'Text', text: /^ #\d+$/ })).map(t => t.text.trim()))
      .toEqual(['#109', '#128', '#130', '#75', '#76', '#90', '#110', '#70', '#71'])
    expect(await ui.find({ type: 'Text', text: /^要対応 4$/ })).toBeDefined()
    const boxes = await ui.findAll({ type: 'Box' })
    expect(boxes.findIndex(x => x.key === 'ship-area')).toBeLessThan(boxes.findIndex(x => x.key === 'needs-you'))

    // the hover card: hidden until the pointer is over its #id
    const chip = await ui.find({ key: 'aboard-128' })
    const card = (chip?.children ?? []).find(c => (c as { props?: { position?: string } }).props?.position === 'absolute') as
      { props: Record<string, unknown>; hover?: unknown } | undefined
    expect([card?.props.display, card?.hover]).toEqual(['none', { display: 'flex' }])
    expect(await ui.find({ type: 'Text', text: '#128 レビュー中' })).toBeDefined()
    await ui.unmount()
  }
})

test('船を隠すボタンで船が消え、$.store に覚えられる', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  const writes: [string, unknown][] = []
  stores(on, writes)
  taskList(on)
  files(on, {})
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...MOUNT, surface })
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ key: 'ship-area' })).toBeDefined()
    expect((await ui.find({ key: 'ship-toggle' }))?.props.label).toBe('船を隠す')
    await ui.press({ key: 'ship-toggle' })
    expect(await ui.find({ key: 'ship-area' })).toBeUndefined()
    expect(await ui.find({ type: 'Raster' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /^要対応 4$/ })).toBeDefined() // the list stays
    expect(writes.at(-1)).toEqual(['shipHidden', true])
    // the next refresh reads it back from the store: still hidden
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ key: 'ship-area' })).toBeUndefined()
    await ui.press({ key: 'ship-toggle' })
    expect(await ui.find({ key: 'ship-area' })).toBeDefined()
    expect(writes.at(-1)).toEqual(['shipHidden', false])
    await ui.unmount()
  }
})

test('$.store が隠すと覚えていれば、開いたときから船は出ない', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  mock.store(on, { shipHidden: true })
  taskList(on)
  files(on, {})
  const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
  await ui.press({ key: 'refresh' })
  expect(await ui.find({ key: 'ship-area' })).toBeUndefined()
  expect((await ui.find({ key: 'ship-toggle' }))?.props.label).toBe('船を出す')
  await ui.unmount()
})

test('波と乗組員は $.clock.every で動き、パネルが出ていないときや船を隠したときは描き直さない', async ($, on) => {
  mock.env(on, { HOME })
  const clock = mock.clock(on, { now: 0 })
  mock.store(on)
  taskList(on)
  files(on, {})
  let shown = true
  on('ui.panes', async () => ({ value: shown ? [{ id: 'task-board', title: 'task-hub', isShown: true, isFocused: false, isPlaced: true }] : [] }))
  const blits: string[] = []
  on('ui.blit', async ($, e, next) => {
    blits.push('cells' in e ? e.cells : '')
    return next(e)
  })
  session(on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
  await ui.press({ key: 'refresh' })
  await clock.advance(1000)
  // about three frames a second, each a different picture
  expect(blits.length).toBeGreaterThanOrEqual(3)
  expect(blits.length).toBeLessThanOrEqual(4)
  expect(new Set(blits).size).toBeGreaterThan(1)

  shown = false // closed, or another pane's tab in front
  blits.length = 0
  await clock.advance(1000)
  expect(blits).toEqual([])

  shown = true
  await ui.press({ key: 'ship-toggle' })
  await clock.advance(1000)
  expect(blits).toEqual([])
  await ui.press({ key: 'ship-toggle' })
  await clock.advance(1000)
  expect(blits.length).toBeGreaterThan(0)
  await ui.unmount()
})

test('desktop では船を描き直さない(Raster がない)', async ($, on) => {
  mock.env(on, { HOME })
  const clock = mock.clock(on, { now: 0 })
  mock.store(on)
  taskList(on)
  files(on, {})
  on('ui.panes', async () => ({ value: [{ id: 'task-board', title: 'task-hub', isShown: true, isFocused: false, isPlaced: true }] }))
  const blits: unknown[] = []
  on('ui.blit', async ($, e, next) => (blits.push(e), next(e)))
  session(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...MOUNT, surface: 'desktop' })
  await ui.press({ key: 'refresh' })
  await clock.advance(1000)
  expect(blits).toEqual([])
  await ui.unmount()
})

// ---- achievements

const run = (over: Record<string, unknown>) => JSON.stringify({
  id: '1', agent: 'claude', started: '2026-10-04T03:00:00Z', finished: '2026-10-04T03:10:00Z', seconds: 600,
  status: 'In review', reviews: ['pass'], retried: false, blocked_by: '', files: 2, ...over,
})
const lines = (runs: Record<string, unknown>[]) => runs.map(run).join('\n')

test('実績は metrics.jsonl だけで判定する', () => {
  expect(earned('')).toEqual([])
  expect(earned('not json\n{{{\n[]\nnull\n')).toEqual([])

  // a pass without retry, five in a row; a retry breaks the run, a run that never started does not
  const four = Array.from({ length: 4 }, (_, i) => ({ id: `${i}` }))
  expect(earned(lines([...four, { id: '9', retried: true, reviews: ['needs changes', 'pass'] }]))).not.toContain('streak-5')
  expect(earned(lines([...four, { id: '8', status: 'Blocked', blocked_by: 'setup', reviews: [] }, { id: '9' }])))
    .toContain('streak-5')
  expect(earned(lines([...four, { id: '8', status: 'Blocked', blocked_by: 'agent', reviews: [] }, { id: '9' }])))
    .not.toContain('streak-5')
  expect(earned(lines(Array.from({ length: 10 }, (_, i) => ({ id: `${i}` }))))).toContain('streak-10')

  // five cards In review on one day (the same card twice counts once); spread over two days, no badge
  const day = (d: string, id: string) => ({ id, finished: `2026-10-0${d}T03:00:00Z`, reviews: ['needs changes'] })
  expect(earned(lines(['1', '2', '3', '4', '5'].map(id => day('4', id))))).toEqual(['day-5', 'first-claude'])
  expect(earned(lines(['1', '2', '3', '4', '4'].map(id => day('4', id))))).not.toContain('day-5')
  expect(earned(lines(['1', '2', '3', '4', '5'].map((id, i) => day(i < 3 ? '3' : '4', id))))).not.toContain('day-5')

  // each agent's first task in review; a Blocked run is not a finished task
  expect(earned(lines([{ agent: 'kiro', status: 'Blocked' }, { agent: 'codex' }, { agent: 'other' }])))
    .toEqual(['first-codex'])
  expect(earned(lines([{ agent: 'pi' }]))).toContain('first-pi')

  // research: In review with no file changed, three of them
  const research = (id: string) => ({ id, files: 0, reviews: ['needs changes'] })
  expect(earned(lines(['1', '2'].map(research)))).not.toContain('research-3')
  expect(earned(lines(['1', '2', '3'].map(research)))).toContain('research-3')
  // one research card reviewed three times is 1 件
  expect(earned(lines(['1', '1', '1'].map(research)))).not.toContain('research-3')
  expect(earned(lines(['1', '1', '2', '2'].map(research)))).not.toContain('research-3')

  // fast: half the agent's usual time (the median of its earlier runs) or less; never before it has a usual time
  const slow = [500, 600, 700].map((s, i) => ({ id: `s${i}`, seconds: s, reviews: ['needs changes'] }))
  expect(earned(lines([...slow, { id: 'f', seconds: 300, reviews: ['needs changes'] }]))).toContain('fast')
  expect(earned(lines([...slow, { id: 'f', seconds: 301, reviews: ['needs changes'] }]))).not.toContain('fast')
  expect(earned(lines([{ seconds: 1 }, { seconds: 1000 }, { seconds: 1 }]))).not.toContain('fast')
  expect(earned(lines([...slow, { id: 'f', agent: 'kiro', seconds: 10, reviews: ['needs changes'] }]))).not.toContain('fast')

  expect(fresh(['day-5', 'fast'], ['day-5'])).toEqual({ ids: ['fast'], toast: '実績解除: 追い風' })
  expect(fresh(['day-5'], ['day-5'])).toEqual({ ids: [] })
  expect(new Set(BADGES.map(b => b.id)).size).toBe(BADGES.length)
})

test('実績の解除はその場でトーストを 1 回だけ出し、パネルの下にバッジで並べる', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  mock.store(on)
  taskList(on)
  const metrics: Record<string, string> = { [METRICS_PATH]: lines([{ id: '1', agent: 'kiro', reviews: ['needs changes'] }]) }
  files(on, metrics)
  const seen: string[] = []
  toasts(on, seen)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...MOUNT, surface })
    await ui.press({ key: 'refresh' })
    await ui.press({ key: 'refresh' })
    expect(seen).toEqual(['実績解除: 初航海 kiro'])
    expect(await ui.find({ type: 'Text', text: `実績 1/${BADGES.length} ` })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '★初航海 kiro ' })).toBeDefined()
    const boxes = await ui.findAll({ type: 'Box' })
    expect(boxes.findIndex(x => x.key === 'badges')).toBeGreaterThan(boxes.findIndex(x => x.key === 'needs-you'))
    expect(await ui.find({ type: 'Text', text: 'kiro の初めてのタスクが In review になった' })).toBeDefined()
    await ui.unmount()
  }

  // metrics.jsonl replaced: a new run earns two more at once, in one toast; the old one is not toasted again
  metrics[METRICS_PATH] += '\n' + lines(['2', '3', '4', '5', '6'].map(id => ({ id, agent: 'claude' })))
  const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
  await Promise.all([ui.press({ key: 'refresh' }), ui.press({ key: 'refresh' })])
  expect(seen).toEqual(['実績解除: 初航海 kiro', '実績解除: 順風、大漁、初航海 claude'])
  expect(await ui.find({ type: 'Text', text: `実績 4/${BADGES.length} ` })).toBeDefined()

  // the file gone or broken: the badges already earned stay, nothing is toasted, the list still shows
  delete metrics[METRICS_PATH]
  await ui.press({ key: 'refresh' })
  metrics[METRICS_PATH] = '{"agent": "pi", "status": "In rev\n\u0000'
  await ui.press({ key: 'refresh' })
  expect(seen).toHaveLength(2)
  expect(await ui.find({ type: 'Text', text: `実績 4/${BADGES.length} ` })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^要対応 4$/ })).toBeDefined()
  await ui.unmount()
})

test('解除済みの実績が $.store にあれば、トーストは出さない', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  mock.store(on, { badges: ['first-kiro'] })
  taskList(on)
  files(on, { [METRICS_PATH]: lines([{ agent: 'kiro', reviews: ['needs changes'] }]) })
  const seen: string[] = []
  toasts(on, seen)
  const ui = await $.ui.mount({ ...MOUNT, surface: 'desktop' })
  await ui.press({ key: 'refresh' })
  expect(seen).toEqual([])
  expect(await ui.find({ type: 'Text', text: '★初航海 kiro ' })).toBeDefined()
  await ui.unmount()
})

test('$.store の実績が読めないときは判定しない: トーストも上書きもしない', async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: 0 })
  const writes: [string, unknown][] = []
  on('store.get', async ($, e) => {
    if (e.key === 'badges') throw new Error('store unavailable')
    return { value: undefined }
  })
  on('store.set', async ($, e) => (writes.push([e.key, e.value]), { value: undefined }))
  taskList(on)
  files(on, { [METRICS_PATH]: lines([{ id: '1', agent: 'kiro', reviews: ['needs changes'] }]) })
  const seen: string[] = []
  toasts(on, seen)
  const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
  await ui.press({ key: 'refresh' })
  await ui.press({ key: 'refresh' })
  expect(seen).toEqual([])
  expect(writes.filter(([k]) => k === 'badges')).toEqual([])
  // the list still shows
  expect(await ui.find({ type: 'Text', text: /^要対応 4$/ })).toBeDefined()
  await ui.unmount()
})
