import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board } from '../types'
import { parseList, summary } from './parse'

const PANE = 'task-board'
const ORDER = ['Blocked', 'In review', 'wait for merge', 'In progress', 'Ready', 'Backlog']
// A running card shows as "In progress › review": rank it by the column, and put unknown columns last.
const base = (status: string): string => status.split(' › ')[0] ?? status
const rank = (status: string): number => {
  const i = ORDER.indexOf(base(status))
  return i === -1 ? ORDER.length : i
}
const board = atom({ plugin: 'task-board', key: 'board' } as const, null as Board | null)

// `task list` is read only (it never starts a card); bare `task` would start Ready cards.
async function refresh($: EngineInterface): Promise<void> {
  const home = (await $.env.get('HOME')) ?? ''
  const checkedAt = new Date(await $.clock.now()).toTimeString().slice(0, 5)
  let next: Board
  try {
    const { exitCode, stdout, stderr } = await $.process.run([`${home}/.local/bin/task`, 'list'], { timeoutMs: 60_000 })
    next = exitCode === 0 ? parseList(stdout, checkedAt)
      : { counts: {}, cards: [], checkedAt, error: stderr.trim().split('\n').pop() ?? `exit ${exitCode}` }
  } catch (err) {
    next = { counts: {}, cards: [], checkedAt, error: String(err) }
  }
  await update($, board, () => next)
  $.ui.status(summary(next))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'task-board', description: 'task-hub のボードをペインに出す' })
    void refresh($)
    $.clock.every(60_000, () => void refresh($))
    return next(e)
  })

  on('command.run', { command: 'task-board' }, async $ => {
    await $.ui.open({ id: PANE, title: 'task-hub' })
    void refresh($)
    return { text: 'task-hub のボードを開きました。' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const b = await read($, board)
    const refreshButton = <Button key="refresh" label="今すぐ更新" onPress={() => refresh($)} />
    if (!b) return <Box><Text dimColor>読み込み中... </Text>{refreshButton}</Box>
    const cards = [...b.cards].sort((x, y) => rank(x.status) - rank(y.status))
    const width = Math.max(20, (e.viewport?.columns ?? 60) - 12)

    return (
      <Box flexDirection="column">
        {b.error !== '' && <Text color="red">読めませんでした: {b.error}</Text>}
        {cards.length === 0 && b.error === '' && <Text dimColor>開いているカードはありません。</Text>}
        {cards.map(c => (
          <Text key={c.id}>
            <Text bold={base(c.status) === 'Blocked' || base(c.status) === 'In review'}>{c.status.padEnd(11)}</Text>
            {` #${c.id} ${c.title.length > width ? c.title.slice(0, width - 1) + '…' : c.title}`}
            {c.waitsFor !== '' && <Text dimColor>{` (待ち: ${c.waitsFor})`}</Text>}
          </Text>
        ))}
        <Box>
          <Text dimColor>{b.checkedAt} 時点 · 1 分ごとに更新 </Text>
          {refreshButton}
        </Box>
      </Box>
    )
  })
}
