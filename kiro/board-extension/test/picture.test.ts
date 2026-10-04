import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import { BADGES, earned } from '../../../claude/task-board/hooks/badges.ts'
import { NONE, ROWS, pixels, scene } from '../../../claude/task-board/hooks/ship.ts'
import { ROOT, SOURCES, build } from '../scripts/build.mjs'
import { toBoard } from '../src/board.ts'
import { FRAMES, MAX_COLUMNS, MIN_COLUMNS, clampColumns, picture, shipHtml, shipState, unlock } from '../src/picture.ts'
import { LIST, METRICS } from './fixtures.ts'

const ok = (stdout: string) => ({ exitCode: 0, stdout, stderr: '' })
const board = toBoard(ok(LIST), '11:00')
const list = (rows: [string, string][]) => `counts: Blocked=0\ntasks[${rows.length}]{id,title,status,repo,agent,waits_for}:\n` +
  rows.map(([id, status]) => `  "${id}",t${id},${status},jyoka/x,"",""\n`).join('')

test('場面と絵は mod の ship.ts を通る: scene() と pixels() と同じピクセル、同じ文字', () => {
  for (const frame of [0, 1, 5, 11]) {
    const p = picture(board, 40, frame)
    const c = pixels(scene(board.cards), 40, frame)
    assert.equal(p.columns, 40)
    assert.equal(p.rows, ROWS * 2)
    assert.deepEqual(p.px, Array.from(c.px, v => v === NONE ? -1 : v))
    assert.deepEqual(p.glyphs.map(g => [g.x, g.y, g.ch]), c.glyphs.map(g => [g.x, g.y, g.ch]))
  }
  // Blocked: the SOS flag and a "?"; the waves move between frames
  assert.deepEqual(picture(board, 40, 0).glyphs.map(g => g.ch).sort(), ['?', 'O', 'S', 'S'])
  assert.notDeepEqual(picture(board, 40, 0).px, picture(board, 40, 1).px)
  // the mod's width limits
  assert.deepEqual([clampColumns(3), clampColumns(40.7), clampColumns(500), clampColumns(NaN)],
    [MIN_COLUMNS, 40, MAX_COLUMNS, MIN_COLUMNS])
  assert.equal(FRAMES, 12)
})

test('荷が多いと船が傾く: 木箱の数で絵が変わる(mod の tiltFor)', () => {
  const level = toBoard(ok(list([['1', 'In review']])), '11:00')
  const heavy = toBoard(ok(list([['1', 'In review'], ['2', 'In review'], ['3', 'wait for merge'], ['4', 'In review']])), '11:00')
  assert.equal(scene(heavy.cards).tilt, 2)
  const crate = (b: typeof level, tip: string) => picture(b, 60, 0).spots.find(s => s.tip === tip)!
  // both on the deck's bottom row; as she lists astern down, the sternmost crate sits lower than a level ship's
  assert.ok(crate(heavy, '#4 t4').y > crate(level, '#1 t1').y)
  assert.notDeepEqual(picture(heavy, 60, 0).px, picture(level, 60, 0).px)
})

test('マウスを乗せる場所: 乗組員・荷・SOS・桟橋の #番号 タイトル、描いたピクセルの上にある', () => {
  const p = picture(board, 64, 0)
  assert.deepEqual(p.spots.map(s => s.tip).sort(), [
    '#109 aica v2 (H): 完了時の計測', '#110 画面, 検索', '#111 すぐ始められるカード',
    '#128 Claude Code 用のボード表示 mod', '#75 Test kiro automation workflow', '#90 merge を待つカード'].sort())
  for (const s of p.spots) {
    let drawn = 0
    for (let y = s.y; y < s.y + s.h; y++) for (let x = s.x; x < s.x + s.w; x++) {
      if (y >= 0 && y < p.rows && x >= 0 && x < p.columns && p.px[y * p.columns + x]! >= 0) drawn++
    }
    assert.ok(drawn > 0, s.tip)
  }
  // a narrow view leaves the pier out of the picture; the list under it still names everyone
  assert.ok(!picture(board, MIN_COLUMNS, 0).spots.some(s => s.tip.startsWith('#111 ')))
  assert.deepEqual(shipState(board, MIN_COLUMNS, 0, false, []).aboard.map(a => [a.label, a.figures.map(f => f.id), a.after]), [
    ['乗組員', ['109', '128'], ''], ['荷', ['75', '90'], '(少し傾いている)'], ['SOS', ['110'], ''], ['桟橋', ['111'], '']])
})

test('Webview に渡す場面: 隠したとき、読み込み中、task list の失敗では絵を出さない', () => {
  const s = shipState(board, 40, 3, false, ['first-kiro', 'day-5', 'unknown'])
  assert.deepEqual(s.picture, picture(board, 40, 3))
  assert.equal(s.hidden, false)
  assert.equal(s.empty, false)
  // the badges in BADGES order, by name, with what earns them
  assert.deepEqual(s.badges.map(b => b.name), ['大漁', '初航海 kiro'])
  assert.equal(s.badges[0]!.desc, '1 日に 5 件 In review にした')
  assert.equal(s.total, BADGES.length)

  const hidden = shipState(board, 40, 3, true, ['day-5'])
  assert.deepEqual([hidden.hidden, hidden.picture, hidden.aboard, hidden.empty], [true, null, [], false])
  assert.deepEqual(hidden.badges.map(b => b.name), ['大漁']) // the badges stay under a hidden ship
  assert.equal(shipState(null, 40, 0, false, []).picture, null)
  assert.equal(shipState(toBoard({ reason: 'boom' }, '11:00'), 40, 0, false, []).picture, null)
  // Backlog alone: an empty ship
  const backlog = shipState(toBoard(ok(list([['1', 'Backlog']])), '11:00'), 40, 0, false, [])
  assert.deepEqual([backlog.empty, backlog.aboard], [true, []])
  assert.notEqual(backlog.picture, null)
})

test('実績の判定は mod の badges.ts を通り、知らせるのは新しいものだけ', () => {
  assert.deepEqual(earned(METRICS), ['first-claude', 'first-kiro'])
  const first = unlock(METRICS, [])
  assert.deepEqual(first, { all: ['first-claude', 'first-kiro'], message: '実績解除: 初航海 claude、初航海 kiro' })
  assert.deepEqual(unlock(METRICS, first.all), { all: first.all, message: undefined })
  // a badge kept before stays, even when metrics.jsonl no longer earns it (or could not be read)
  assert.deepEqual(unlock('', ['day-5']), { all: ['day-5'], message: undefined })
  assert.deepEqual(unlock(METRICS, ['first-kiro']), { all: ['first-kiro', 'first-claude'], message: '実績解除: 初航海 claude' })
})

test('Webview のページ: CSP で拡張に同梱したファイルと nonce つきのスクリプトだけ、外部の URL なし', () => {
  const html = shipHtml('vscode-webview://x', 'abc123', 'vscode-webview://x/media/ship.js', 'vscode-webview://x/media/ship.css')
  const csp = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)?.[1]
  assert.equal(csp, "default-src 'none'; img-src vscode-webview://x; style-src vscode-webview://x; script-src 'nonce-abc123';")
  assert.deepEqual(html.match(/<script[^>]*>/g), ['<script nonce="abc123" src="vscode-webview://x/media/ship.js">'])
  assert.doesNotMatch(html, /https?:/)
  assert.doesNotMatch(html, /\sstyle=/)
  // the script it loads is in the VSIX (media/) and loads nothing itself
  const script = readFileSync(join(ROOT, 'media', 'ship.js'), 'utf8')
  assert.doesNotMatch(script, /https?:|fetch\(|import\(|innerHTML|eval\(/)
})

test('共有のしかた: out/ に mod の ship.ts と badges.ts から作った ship.js と badges.js が入り、拡張に別実装はない', () => {
  for (const f of ['ship.ts', 'badges.ts', 'parse.ts', 'panel.ts']) {
    assert.ok(SOURCES.includes(join(ROOT, '..', '..', 'claude', 'task-board', 'hooks', f)), f)
  }
  const dir = mkdtempSync(join(tmpdir(), 'task-hub-board-test-'))
  try {
    build(dir)
    assert.deepEqual(readdirSync(dir).sort(),
      ['badges.js', 'board.js', 'extension.js', 'panel.js', 'parse.js', 'picture.js', 'ship.js'])
    const built = readFileSync(join(dir, 'picture.js'), 'utf8')
    assert.match(built, /require\("\.\/badges\.js"\)/)
    assert.match(built, /require\("\.\/ship\.js"\)/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
  const src = readdirSync(join(ROOT, 'src')).map(f => readFileSync(join(ROOT, 'src', f), 'utf8')).join('\n')
  assert.doesNotMatch(src, /\b(const|function) (scene|tiltFor|pixels|earned|fresh)\b/)
})
