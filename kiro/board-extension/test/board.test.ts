import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { Node } from '../src/board.ts'
import { badge, detailsOf, statusBar, toBoard, tree } from '../src/board.ts'
import { CONFIG, EVENTS, LIST, METRICS, NOW } from './fixtures.ts'

const ok = (stdout: string) => ({ exitCode: 0, stdout, stderr: '' })
const board = toBoard(ok(LIST), '11:00')
const full = () => tree(board, detailsOf(board, { events: EVENTS, metrics: METRICS, ini: CONFIG }, NOW))
const bare = () => tree(board, detailsOf(board, { events: '', metrics: '', ini: '' }, NOW))
const card = (nodes: Node[], id: string): Node | undefined =>
  nodes.flatMap(g => g.children ?? []).find(c => c.id === `card/${id}`)
const ids = (g: Node | undefined) => (g?.children ?? []).map(c => c.label.match(/^#(\d+) /)?.[1])

test('列ごとのグループ: 要対応 → 実行中 → 待ち → Backlog → その他、件数つき、Backlog とその他だけ畳む', () => {
  const groups = full()
  assert.deepEqual(groups.map(g => g.label), ['要対応 3', '実行中 2', '待ち 1', 'Backlog 1', 'その他 1'])
  assert.deepEqual(groups.map(g => g.open), [true, true, true, false, false])
  assert.deepEqual(groups.map(ids), [['110', '75', '90'], ['109', '128'], ['111'], ['64'], ['200']])
  assert.ok(groups.every(g => g.icon === ''))
})

test('空のグループは出さない', () => {
  const only = 'counts: Blocked=1\ntasks[1]{id,title,status,repo,agent,waits_for}:\n  "5",ひとつ,Blocked,jyoka/aica,"",""\n'
  assert.deepEqual(tree(toBoard(ok(only), '11:00')).map(g => g.label), ['要対応 1'])
})

test('状態ごとの色: Blocked は赤、In review は黄、wait for merge は緑、実行中は水色(テーマの色名)', () => {
  const nodes = bare()
  const look = (id: string) => [card(nodes, id)?.icon, card(nodes, id)?.color]
  assert.deepEqual(look('110'), ['error', 'charts.red'])
  assert.deepEqual(look('75'), ['eye', 'charts.yellow'])
  assert.deepEqual(look('90'), ['git-merge', 'charts.green'])
  assert.deepEqual(look('109'), ['sync', 'terminal.ansiCyan'])
  assert.deepEqual(look('128'), ['sync', 'terminal.ansiCyan'])
  assert.deepEqual(look('111'), ['play', undefined])
  assert.deepEqual(look('64'), ['circle-outline', undefined])
  assert.deepEqual(look('200'), ['question', undefined])
})

test('description: repo タグ(owner なし)、実行中は段階と経過時間、要対応は列、待ち先', () => {
  const nodes = full()
  assert.equal(card(nodes, '110')?.description, 'aica · Blocked · 待ち: #109')
  assert.equal(card(nodes, '75')?.description, 'task-hub · In review')
  assert.equal(card(nodes, '90')?.description, 'task-hub · wait for merge')
  assert.equal(card(nodes, '109')?.description, 'aica · 12分 / 普段9分')
  assert.equal(card(nodes, '128')?.description, 'task-hub · review · 5分 / 普段 不明')
  assert.equal(card(nodes, '111')?.description, 'task-hub')
  assert.equal(card(nodes, '64')?.description, 'aica')
  assert.equal(card(nodes, '200')?.description, 'task-hub · Someday')
  assert.equal(card(nodes, '110')?.label, '#110 画面, 検索')
})

test('経過時間: 普段を超えたら警告色、bin/task が遅いとする時間を超えたらエラー色', () => {
  assert.equal(card(full(), '109')?.color, 'list.warningForeground') // 12 minutes, usually 9
  assert.equal(card(full(), '128')?.color, 'terminal.ansiCyan') // no usual time yet, 5 minutes of the 30
  const late = detailsOf(board, { events: EVENTS, metrics: METRICS, ini: CONFIG }, NOW + 30 * 60_000)
  assert.equal(card(tree(board, late), '109')?.description, 'aica · 42分 / 普段9分')
  assert.equal(card(tree(board, late), '109')?.color, 'list.errorForeground') // past max(3 x 9, 15) minutes
  assert.equal(card(tree(board, late), '128')?.color, 'list.errorForeground') // past 30 minutes
})

test('子ノード: In review は判定と PR(クリックで開く)、Blocked は理由', () => {
  const nodes = full()
  const review = card(nodes, '75')
  assert.equal(review?.open, true)
  assert.deepEqual(review?.children?.map(c => [c.id, c.label, c.icon, c.color, c.link]), [
    ['card/75/verdict', '判定: needs changes', 'request-changes', 'charts.yellow', undefined],
    ['card/75/pr', 'PR #36', 'git-pull-request', undefined, 'https://github.com/jyoka/task-hub/pull/36'],
  ])
  const blocked = card(nodes, '110')
  assert.deepEqual(blocked?.children?.map(c => [c.label, c.tooltip, c.link]),
    [['理由: 前提の PR #26 が まだマージされていない', '前提の PR #26 が まだマージされていない', undefined]])
  for (const id of ['90', '109', '128', '111', '64', '200']) assert.equal(card(nodes, id)?.children, undefined, id)
  const pass = EVENTS.replace('"needs changes"', '"pass"')
  const passed = card(tree(board, detailsOf(board, { events: pass, metrics: '', ini: '' }, NOW)), '75')
  assert.deepEqual([passed?.children?.[0]?.label, passed?.children?.[0]?.icon, passed?.children?.[0]?.color],
    ['判定: pass', 'pass', 'charts.green'])
})

test('PR が http(s) の URL でなければ、開く子ノードは足さない', () => {
  const odd = EVENTS.replace('https://github.com/jyoka/task-hub/pull/36', 'file:///etc/passwd')
  const review = card(tree(board, detailsOf(board, { events: odd, metrics: '', ini: '' }, NOW)), '75')
  assert.deepEqual(review?.children?.map(c => c.label), ['判定: needs changes'])
})

test('tooltip は Markdown で、タイトルの全文と詳細', () => {
  const nodes = full()
  assert.equal(card(nodes, '75')?.markdown, [
    '**#75 Test kiro automation workflow**',
    'In review · jyoka/task\\-hub',
    '判定: needs changes',
    '[PR #36](https://github.com/jyoka/task-hub/pull/36)',
  ].join('\n\n'))
  assert.equal(card(nodes, '110')?.markdown,
    '**#110 画面, 検索**\n\nBlocked · jyoka/aica · 待ち: \\#109\n\n理由: 前提の PR \\#26 が まだマージされていない')
  assert.equal(card(nodes, '128')?.markdown,
    '**#128 Claude Code 用のボード表示 mod**\n\nIn progress › review · jyoka/task\\-hub · 5分 / 普段 不明')
  const star = 'counts: Ready=1\ntasks[1]{id,title,status,repo,agent,waits_for}:\n  "7","a *b* [c](d)",Ready,jyoka/aica,"",""\n'
  assert.match(card(tree(toBoard(ok(star), '11:00')), '7')?.markdown ?? '', /^\*\*#7 a \\\*b\\\* \\\[c\\\]\\\(d\\\)\*\*/)
  const paren = EVENTS.replace('https://github.com/jyoka/task-hub/pull/36', 'https://example.com/a)b/pull/36')
  assert.match(card(tree(board, detailsOf(board, { events: paren, metrics: '', ini: '' }, NOW)), '75')?.markdown ?? '',
    /\[PR #36\]\(https:\/\/example\.com\/a%29b\/pull\/36\)$/)
})

test('badge は要対応の件数、0 や読めないときは出さない', () => {
  assert.deepEqual(badge(board), { value: 3, tooltip: '要対応 3 件' })
  const none = 'counts: Ready=1\ntasks[1]{id,title,status,repo,agent,waits_for}:\n  "7",a,Ready,jyoka/aica,"",""\n'
  assert.equal(badge(toBoard(ok(none), '11:00')), undefined)
  assert.equal(badge(toBoard({ exitCode: 1, stdout: '', stderr: 'x' }, '11:00')), undefined)
  assert.equal(badge(null), undefined)
})

test('events と metrics がない、または壊れた行だけでも、一覧はこれまでどおり出る', () => {
  const plain = bare()
  assert.deepEqual(plain.map(ids), [['110', '75', '90'], ['109', '128'], ['111'], ['64'], ['200']])
  assert.equal(card(plain, '109')?.description, 'aica')
  assert.equal(card(plain, '128')?.description, 'task-hub · review')
  assert.equal(card(plain, '75')?.children, undefined)
  const broken = tree(board, detailsOf(board, { events: '{"id": "75", "ev\nnull\n[1]\n"x"', metrics: '{', ini: '[' }, NOW))
  assert.deepEqual(broken, plain)
})

test('ステータスバーは 0 でない数だけ。Blocked が 1 件以上なら必ず「止まりN」が出る', () => {
  assert.equal(statusBar(board).text, '$(checklist) task: 実行中2 レビュー待ち1 止まり1')
  const some = 'counts: Backlog=2, Ready=0, In progress=0, In review=3, wait for merge=0, Blocked=0\n'
  assert.equal(statusBar(toBoard(ok(some), '11:00')).text, '$(checklist) task: レビュー待ち3')
  const blocked = 'counts: Backlog=0, Ready=0, In progress=0, In review=0, wait for merge=0, Blocked=2\n'
  assert.equal(statusBar(toBoard(ok(blocked), '11:00')).text, '$(checklist) task: 止まり2')
  const none = statusBar(toBoard(ok('counts: Backlog=2, In progress=0\ntasks: 0 open tasks\n'), '11:00'))
  assert.equal(none.text, '$(checklist) task')
  assert.equal(none.warning, false)
})

test('カードがないときと、読み込む前', () => {
  assert.deepEqual(tree(toBoard(ok('counts: Backlog=0\ntasks: 0 open tasks\n'), '11:00')).map(r => r.label),
    ['開いているカードはありません。'])
  assert.deepEqual(tree(null).map(r => [r.label, r.icon]), [['読み込み中...', 'loading~spin']])
})

test('task list が失敗したら空のボードにせず、stdout の error: 行を理由に出す', () => {
  const stdout = 'error: the board is not configured in ~/.config/task-hub/config.ini\nhelp: add:  [board]  project = <owner>/<project number>\n'
  const b = toBoard({ exitCode: 1, stdout, stderr: '' }, '11:00')
  assert.deepEqual(tree(b).map(r => r.label), ['読めませんでした: the board is not configured in ~/.config/task-hub/config.ini'])
  const bar = statusBar(b)
  assert.equal(bar.text, '$(warning) task: 読めない (the board is not configured in ~/.confi…)')
  assert.match(bar.tooltip, /the board is not configured in ~\/\.config\/task-hub\/config\.ini$/)
  assert.equal(bar.warning, true)
})

test('失敗の理由: stderr があればその最後の行、どちらもなければ終了コード、起動できなければその理由', () => {
  assert.equal(toBoard({ exitCode: 2, stdout: '', stderr: 'Traceback\nKeyError: x\n' }, '11:00').error, 'KeyError: x')
  assert.equal(toBoard({ exitCode: 3, stdout: '', stderr: '' }, '11:00').error, 'exit 3')
  const b = toBoard({ reason: '/home/me/.local/bin/task がありません' }, '11:00')
  assert.deepEqual(tree(b).map(r => r.label), ['読めませんでした: /home/me/.local/bin/task がありません'])
  assert.equal(statusBar(b).text, '$(warning) task: 読めない (/home/me/.local/bin/task がありません)')
})

test('終了コードが 0 でも counts: の行がなければ、空のボードにしない', () => {
  const b = toBoard(ok(''), '11:00')
  assert.deepEqual(tree(b).map(r => r.label), ['読めませんでした: task list の出力に counts: の行がありません'])
  assert.equal(statusBar(b).warning, true)
})
