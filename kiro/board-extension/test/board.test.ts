import assert from 'node:assert/strict'
import { test } from 'node:test'

import { rows, statusBar, toBoard } from '../src/board.ts'
import { LIST } from './fixtures.ts'

const ok = (stdout: string) => ({ exitCode: 0, stdout, stderr: '' })

test('Blocked → In review → wait for merge → In progress → Ready → Backlog、知らない status は末尾', () => {
  const ids = rows(toBoard(ok(LIST), '11:00')).map(r => r.label.match(/^#(\d+) /)?.[1])
  assert.deepEqual(ids, ['110', '75', '90', '109', '128', '111', '64', '200'])
})

test('段階付きの status はそのまま出し、並びは › の前で決める', () => {
  const row = rows(toBoard(ok(LIST), '11:00')).find(r => r.label.startsWith('#128 '))
  assert.equal(row?.description, 'In progress › review')
  assert.equal(row?.icon, 'sync')
})

test('各行は #番号 タイトル、status、待ち先があれば待ち先', () => {
  const [blocked] = rows(toBoard(ok(LIST), '11:00'))
  assert.equal(blocked?.label, '#110 画面, 検索')
  assert.equal(blocked?.description, 'Blocked · 待ち: #109')
  assert.equal(blocked?.tooltip, '#110 画面, 検索\nBlocked\njyoka/aica\n待ち: #109')
  const review = rows(toBoard(ok(LIST), '11:00'))[1]
  assert.equal(review?.description, 'In review')
})

test('ステータスバーは 0 でない数だけ', () => {
  assert.equal(statusBar(toBoard(ok(LIST), '11:00')).text, '$(checklist) task: 実行中2 レビュー待ち1 止まり1')
  const some = 'counts: Backlog=2, Ready=0, In progress=0, In review=3, wait for merge=0, Blocked=0\n'
  assert.equal(statusBar(toBoard(ok(some), '11:00')).text, '$(checklist) task: レビュー待ち3')
  const none = statusBar(toBoard(ok('counts: Backlog=2, In progress=0\ntasks: 0 open tasks\n'), '11:00'))
  assert.equal(none.text, '$(checklist) task')
  assert.equal(none.warning, false)
})

test('カードがないときと、読み込む前', () => {
  assert.deepEqual(rows(toBoard(ok('counts: Backlog=0\ntasks: 0 open tasks\n'), '11:00')).map(r => r.label),
    ['開いているカードはありません。'])
  assert.deepEqual(rows(null).map(r => r.label), ['読み込み中...'])
})

test('task list が失敗したら空のボードにせず、stdout の error: 行を理由に出す', () => {
  const stdout = 'error: the board is not configured in ~/.config/task-hub/config.ini\nhelp: add:  [board]  project = <owner>/<project number>\n'
  const b = toBoard({ exitCode: 1, stdout, stderr: '' }, '11:00')
  assert.deepEqual(rows(b).map(r => r.label), ['読めませんでした: the board is not configured in ~/.config/task-hub/config.ini'])
  const bar = statusBar(b)
  assert.equal(bar.text, '$(warning) task: 読めない (the board is not configured in ~/.confi…)')
  assert.match(bar.tooltip, /the board is not configured in ~\/\.config\/task-hub\/config\.ini$/)
  assert.equal(bar.warning, true)
})

test('失敗の理由: stderr があればその最後の行、どちらもなければ終了コード、起動できなければその理由', () => {
  assert.equal(toBoard({ exitCode: 2, stdout: '', stderr: 'Traceback\nKeyError: x\n' }, '11:00').error, 'KeyError: x')
  assert.equal(toBoard({ exitCode: 3, stdout: '', stderr: '' }, '11:00').error, 'exit 3')
  const b = toBoard({ reason: '/home/me/.local/bin/task がありません' }, '11:00')
  assert.deepEqual(rows(b).map(r => r.label), ['読めませんでした: /home/me/.local/bin/task がありません'])
  assert.equal(statusBar(b).text, '$(warning) task: 読めない (/home/me/.local/bin/task がありません)')
})

test('終了コードが 0 でも counts: の行がなければ、空のボードにしない', () => {
  const b = toBoard(ok(''), '11:00')
  assert.deepEqual(rows(b).map(r => r.label), ['読めませんでした: task list の出力に counts: の行がありません'])
  assert.equal(statusBar(b).warning, true)
})
