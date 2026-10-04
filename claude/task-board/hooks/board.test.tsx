import { expect, mock, test } from 'claude-code/testing'

import { parseList, summary } from './parse'

const PANE = {
  title: 'task-hub', isFocused: false, bodyColumns: 80, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 20 }, view: {},
}

const LIST = `counts: Backlog=1, Ready=0, In progress=2, In review=1, wait for merge=1, Blocked=1
tasks[6]{id,title,status,repo,agent,waits_for}:
  "64","aica v1: Render 公開とデプロイ smoke(HITL)",Backlog,jyoka/aica,"",""
  "75",Test kiro automation workflow,In review,jyoka/task-hub,kiro,""
  "109","aica v2 (H): 完了時の計測",In progress,jyoka/aica,"",""
  "128",Claude Code 用のボード表示 mod,In progress › review,jyoka/task-hub,"",""
  "90",merge を待つカード,wait for merge,jyoka/task-hub,"",""
  "110","画面, 検索",Blocked,jyoka/aica,"","#109"
needs_you: 3 (Backlog to approve, In review, Blocked)
`

test('task list の出力を読む', () => {
  const b = parseList(LIST, '11:00')
  expect(b.counts['In review']).toBe(1)
  expect(b.cards.length).toBe(6)
  expect(b.cards[0]?.title).toBe('aica v1: Render 公開とデプロイ smoke(HITL)')
  expect(b.cards[5]).toEqual({ id: '110', title: '画面, 検索', status: 'Blocked', repo: 'jyoka/aica', waitsFor: '#109' })
  expect(summary(b)).toBe('task: 実行中2 レビュー待ち1 止まり1')
  expect(summary(parseList('counts: Backlog=2, In progress=0\n', '11:00'))).toBeUndefined()
})

test('引用された値は JSON 文字列として読む(bin/task の q() は json.dumps)', () => {
  const title = 'say "hi", C:\\path'
  const b = parseList(`counts: Blocked=1\n  "1",${JSON.stringify(title)},Blocked,jyoka/x,"",""\n`, '11:00')
  expect(b.cards).toEqual([{ id: '1', title, status: 'Blocked', repo: 'jyoka/x', waitsFor: '' }])
})

test('ペインは Blocked を先頭に出し、更新ボタンで task list を読み直す', async ($, on) => {
  mock.env(on, { HOME: '/home/me' })
  mock.clock(on, { now: 0 })
  const ran: string[][] = []
  on('process.run', async ($, e) => {
    ran.push([...e.argv])
    return { value: { exitCode: 0, stdout: LIST, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const statuses: unknown[] = []
  on('ui.status', async ($, e) => (statuses.push(e), { value: undefined }))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: PANE })
    await ui.press({ key: 'refresh' })
    const rows = await ui.findAll({ type: 'Text', text: /#\d+/ })
    // the id is followed by the title; the waits_for part "(待ち: #109)" is its own Text
    expect(rows.flatMap(r => r.text?.match(/ #(\d+) /)?.[1] ?? [])).toEqual(['110', '75', '90', '109', '128', '64'])
    expect(await ui.find({ text: /待ち: #109/ })).toBeDefined()
    await ui.unmount()
  }
  expect(ran[0]).toEqual(['/home/me/.local/bin/task', 'list'])
  expect(JSON.stringify(statuses.at(-1))).toContain('task: 実行中2 レビュー待ち1 止まり1')
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
