import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board, Card, Details } from '../types'
import { base, failure, parseList, summary } from './parse'
import {
  STATUS_COLORS, cells, clip, details, elapsedText, groups, prLabel, repoTag, stage, verdictColor,
} from './panel'

const PANE = 'task-board'
const board = atom({ plugin: 'task-board', key: 'board' } as const, null as Board | null)
const extra = atom({ plugin: 'task-board', key: 'details' } as const, {} as Details)

// A file the pane may do without: missing, over 4 MiB ($.fs.read rejects those) or unreadable reads as empty.
const optional = ($: EngineInterface, path: string): Promise<string> => $.fs.read(path).catch(() => '')

// `task list` is read only (it never starts a card); bare `task` would start Ready cards.
// events.jsonl and metrics.jsonl are local files task-hub writes: no LLM, no GitHub.
async function refresh($: EngineInterface): Promise<void> {
  const home = (await $.env.get('HOME')) ?? ''
  const now = await $.clock.now()
  const checkedAt = new Date(now).toTimeString().slice(0, 5)
  let next: Board
  try {
    const { exitCode, stdout, stderr } = await $.process.run([`${home}/.local/bin/task`, 'list'], { timeoutMs: 60_000 })
    next = exitCode === 0 ? parseList(stdout, checkedAt)
      : { counts: {}, cards: [], checkedAt, error: failure(exitCode, stdout, stderr) }
  } catch (err) {
    next = { counts: {}, cards: [], checkedAt, error: String(err) }
  }
  let more: Details = {}
  if (next.cards.length > 0) {
    const [events, metrics, ini] = await Promise.all([
      optional($, `${home}/.local/state/task-hub/events.jsonl`),
      optional($, `${home}/.local/state/task-hub/metrics.jsonl`),
      optional($, `${home}/.config/task-hub/config.ini`),
    ])
    more = details(next.cards, events, metrics, ini, now)
  }
  await update($, extra, () => more)
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
    const { Box, Text, Button, Link } = $.ui.resolve(e)
    const b = await read($, board)
    const more = await read($, extra)
    const refreshButton = <Button key="refresh" label="今すぐ更新" onPress={() => refresh($)} />
    if (!b) return <Box><Text dimColor>読み込み中... </Text>{refreshButton}</Box>
    const columns = Math.max(24, e.props.bodyColumns ?? e.viewport?.columns ?? 60)
    const inner = columns - 4 // a framed group: its border and one cell of padding on each side

    // One card: what it is waiting on (its column, or a running card's stage), the repo tag, #id and the title cut to
    // what is left of the line. Under it, indented, the one thing to judge it by.
    const card = (c: Card, pad: number) => {
      const col = base(c.status)
      const running = col === 'In progress'
      const label = running ? stage(c.status) : col
      const tag = repoTag(c.repo)
      const waits = c.waitsFor !== '' ? ` (待ち: ${c.waitsFor})` : ''
      const used = (pad > 0 ? pad + 1 : 0) + cells(tag.name) + 3 + cells(`#${c.id} `) + cells(waits)
      const d = more[c.id] ?? {}
      const time = elapsedText(d)
      return (
        <Box key={`card-${c.id}`} flexDirection="column">
          <Text wrap="truncate-end">
            {pad > 0 && (!running ? <Text color={STATUS_COLORS[col]} bold>{label.padEnd(pad)}</Text>
              : label !== '' ? <Text color="cyan" inverse>{` ${label} `.padEnd(pad)}</Text>
              : ' '.repeat(pad))}
            {pad > 0 && ' '}
            <Text color={tag.color} inverse>{` ${tag.name} `}</Text>
            {` #${c.id} ${clip(c.title, Math.max(8, inner - used))}`}
            {waits !== '' && <Text dimColor>{waits}</Text>}
          </Text>
          {time && <Text color={time.color} dimColor={!time.color}>{`    ${time.text}`}</Text>}
          {col === 'In review' && (d.verdict || d.pr) && (
            <Box>
              <Text>{'    '}</Text>
              {d.verdict && <Text color={verdictColor(d.verdict)} bold>{d.verdict}</Text>}
              {d.verdict && d.pr && <Text dimColor>{' · '}</Text>}
              {d.pr && <Link href={d.pr} label={prLabel(d.pr)} />}
            </Box>
          )}
          {col === 'Blocked' && d.reason && (
            <Text dimColor wrap="truncate-end">{`    ${clip(d.reason, Math.max(8, inner - 4))}`}</Text>
          )}
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        {b.error !== '' && <Text color="red">読めませんでした: {b.error}</Text>}
        {b.cards.length === 0 && b.error === '' && <Text dimColor>開いているカードはありません。</Text>}
        {groups(b.cards).map(g => {
          const head = <Text bold>{g.label} <Text dimColor>{g.cards.length}</Text></Text>
          if (g.folded) {
            const ids = g.cards.map(c => `#${c.id}`).join(' ')
            return (
              <Box key={g.key} paddingX={2}>
                <Text wrap="truncate-end">{head}{'  '}<Text dimColor>{clip(ids, Math.max(8, columns - 4 - cells(g.label) - 6))}</Text></Text>
              </Box>
            )
          }
          const running = g.key === 'running'
          const pad = running
            ? Math.max(0, ...g.cards.map(c => stage(c.status) === '' ? 0 : cells(stage(c.status)) + 2))
            : Math.max(...g.cards.map(c => cells(base(c.status))))
          return (
            <Box key={g.key} flexDirection="column" borderStyle="round" borderColor={running ? 'cyan' : g.cards.some(c => c.status === 'Blocked') ? 'red' : 'yellow'} paddingX={1}>
              {head}
              {g.cards.map(c => card(c, pad))}
            </Box>
          )
        })}
        <Box>
          <Text dimColor>{b.checkedAt} 時点 · 1 分ごとに更新 </Text>
          {refreshButton}
        </Box>
      </Box>
    )
  })
}
