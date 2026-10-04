import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board, Card, Details } from '../types'
import { BADGES, earned, fresh } from './badges'
import { base, failure, parseList, summary } from './parse'
import {
  STATUS_COLORS, cells, clip, details, elapsedText, groups, isFolded, prLabel, repoTag, stage, verdictColor,
} from './panel'
import type { Figure, Scene } from './ship'
import { ROWS, TILT_WORDS, cells as shipCells, deck, drop, scene } from './ship'

const PANE = 'task-board'
const board = atom({ plugin: 'task-board', key: 'board' } as const, null as Board | null)
const extra = atom({ plugin: 'task-board', key: 'details' } as const, {} as Details)
const shipHidden = atom({ plugin: 'task-board', key: 'shipHidden' } as const, false)
const badges = atom({ plugin: 'task-board', key: 'badges' } as const, [] as string[])
const folded = atom({ plugin: 'task-board', key: 'folded' } as const, null as string[] | null)

// $.store: what the person chose and what they unlocked, kept across sessions. A choice that cannot be read is unset.
const stored = ($: EngineInterface, key: string): Promise<unknown> => $.store.get(key).catch(() => undefined)
const ids = (v: unknown): string[] => Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

// Achievements: the badges metrics.jsonl earns that the store does not hold yet are stored first, then toasted once.
// One judgement at a time, so two refreshes running together never toast the same badge twice. A badge store that
// cannot be read skips the judgement: taken as empty, it would toast the old badges again and overwrite them.
let judging: Promise<void> = Promise.resolve()
const judge = ($: EngineInterface, metrics: string): Promise<void> => judging = judging.then(async () => {
  const known = ids(await $.store.get('badges'))
  const { ids: unlocked, toast } = fresh(earned(metrics), known)
  const all = [...known, ...unlocked]
  if (toast) {
    try { await $.store.set('badges', all) } catch { return }
    $.ui.toast(toast)
  }
  const shown = await read($, badges)
  if (shown.join() !== all.join()) await update($, badges, () => all)
}).catch(() => {})

// The ship's animation: a few frames a second, painted into the mounted Raster with $.ui.blit (no redraw), and
// only while the pane is shown with the ship in it. `drawn` is what the last terminal drawing showed.
const FRAME_MS = 300
let drawn: { scene: Scene; columns: number } | undefined
let frame = 0
let painting = false
async function tick($: EngineInterface): Promise<void> {
  if (!drawn || painting) return
  painting = true
  try {
    if (!(await $.ui.panes()).some(p => p.id === PANE && p.isShown)) return
    frame = (frame + 1) % 12
    await $.ui.blit({ requestId: PANE, key: 'ship', cells: shipCells(drawn.scene, drawn.columns, frame) })
  } catch { // the pane went away between the check and the blit: the next drawing sets `drawn` again
  } finally {
    painting = false
  }
}

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
  const metrics = await optional($, `${home}/.local/state/task-hub/metrics.jsonl`)
  if (next.cards.length > 0) {
    const [events, ini] = await Promise.all([
      optional($, `${home}/.local/state/task-hub/events.jsonl`),
      optional($, `${home}/.config/task-hub/config.ini`),
    ])
    more = details(next.cards, events, metrics, ini, now)
  }
  await update($, extra, () => more)
  await update($, board, () => next)
  $.ui.status(summary(next))
  const hidden = (await stored($, 'shipHidden')) === true
  if (hidden !== await read($, shipHidden)) await update($, shipHidden, () => hidden)
  const chosen = await stored($, 'folded')
  const keys = Array.isArray(chosen) ? ids(chosen) : null
  if (JSON.stringify(keys) !== JSON.stringify(await read($, folded))) await update($, folded, () => keys)
  await judge($, metrics)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'task-board', description: 'task-hub のボードをペインに出す' })
    void refresh($).catch(() => {})
    $.clock.every(60_000, () => void refresh($).catch(() => {}))
    $.clock.every(FRAME_MS, () => void tick($))
    return next(e)
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) drawn = undefined
    return next(e)
  })

  on('command.run', { command: 'task-board' }, async $ => {
    await $.ui.open({ id: PANE, title: 'task-hub' })
    void refresh($)
    return { text: 'task-hub のボードを開きました。' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const ui = $.ui.resolve(e)
    const { Box, Text, Button, Link } = ui
    const b = await read($, board)
    const more = await read($, extra)
    const hidden = await read($, shipHidden)
    const unlocked = await read($, badges)
    const chosen = await read($, folded)
    const refreshButton = <Button key="refresh" label="今すぐ更新" onPress={() => refresh($)} />
    if (!b) return <Box><Text dimColor>読み込み中... </Text>{refreshButton}</Box>
    const columns = Math.max(24, e.props.bodyColumns ?? e.viewport?.columns ?? 60)
    const inner = columns - 4 // a framed group: its border and one cell of padding on each side

    // A label that shows `text` in a small card next to it while the pointer is over it.
    const tip = (key: string, label: JSX.Element, text: string, above = false) => (
      <Box key={key}>
        {label}
        <Box position="absolute" top={above ? -3 : 1} left={0} display="none" hover={{ display: 'flex' }}
          borderStyle="round" paddingX={1} width={Math.min(cells(text) + 4, columns)}>
          <Text wrap="truncate-end">{text}</Text>
        </Box>
      </Box>
    )
    const name = (f: Figure) => `#${f.id} ${f.title}`

    // The ship: a Raster of pixels on the terminal, characters elsewhere; under it, who is aboard, by #id.
    const shipView = () => {
      const s = scene(b.cards)
      const width = Math.min(columns, 64)
      let picture
      if (e.surface === 'terminal' && 'Raster' in ui) { // elsewhere a Raster is drawn as nothing
        drawn = { scene: s, columns: width }
        picture = <ui.Raster key="ship" columns={width} rows={ROWS} cells={shipCells(s, width, frame)} />
      } else {
        const cols = deck(s)
        picture = (
          <Box flexDirection="column">
            <Box key="ship" flexDirection="row">
              {cols.map((col, i) => {
                const body = (
                  <Box flexDirection="column" alignItems="center" marginTop={drop(s.tilt, i, cols.length)}>
                    {col.lines.map(l => <Text>{l}</Text>)}
                    <Text color="#8b5a2b">{col.hull}</Text>
                  </Box>
                )
                return col.figure ? tip(`ship-${col.kind}-${col.figure.id}`, body, name(col.figure))
                  : <Box key={`ship-${col.kind}-${i}`}>{body}</Box>
              })}
            </Box>
            <Text color="blue" wrap="truncate-end">{'～'.repeat(Math.max(8, Math.floor(width / 2)))}</Text>
            {s.pier.length > 0 && (
              <Box flexDirection="row">
                <Text dimColor>桟橋 </Text>
                {s.pier.map(f => tip(`ship-pier-${f.id}`, <Text>🧍</Text>, name(f)))}
              </Box>
            )}
          </Box>
        )
      }
      const chips = (label: string, figures: Figure[], color: string, after = '') => figures.length > 0 && (
        <Box key={`aboard-${label}`} flexDirection="row" marginRight={2}>
          <Text dimColor>{label}</Text>
          {figures.map(f => tip(`aboard-${f.id}`, <Text color={color}>{` #${f.id}`}</Text>, name(f)))}
          {after !== '' && <Text dimColor>{after}</Text>}
        </Box>
      )
      const aboard = s.crew.length + s.cargo.length + s.stuck.length + s.pier.length
      return (
        <Box key="ship-area" flexDirection="column">
          {picture}
          <Box flexDirection="row" flexWrap="wrap">
            {aboard === 0 && <Text dimColor>船は空です</Text>}
            {chips('乗組員', s.crew, 'cyan')}
            {chips('荷', s.cargo, 'yellow', s.cargo.length > 0 ? ` (${TILT_WORDS[s.tilt]})` : '')}
            {chips('SOS', s.stuck, 'red')}
            {chips('桟橋', s.pier, 'gray')}
          </Box>
        </Box>
      )
    }
    if (hidden || b.error !== '') drawn = undefined
    const toggle = <Button key="ship-toggle" label={hidden ? '船を出す' : '船を隠す'} onPress={async () => {
      const next = await update($, shipHidden, h => !h)
      await $.store.set('shipHidden', next).catch(() => {})
    }} />
    const earnedBadges = BADGES.filter(x => unlocked.includes(x.id))

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
        {!hidden && b.error === '' && shipView()}
        {b.error !== '' && <Text color="red">読めませんでした: {b.error}</Text>}
        {b.cards.length === 0 && b.error === '' && <Text dimColor>開いているカードはありません。</Text>}
        {groups(b.cards).map((g, _, all) => {
          // The heading folds and unfolds its group; the choice is kept for the next session.
          const shut = isFolded(g, chosen)
          const fold = async () => {
            const next = await update($, folded, keys => {
              const now = all.filter(x => isFolded(x, keys)).map(x => x.key)
              return now.includes(g.key) ? now.filter(k => k !== g.key) : [...now, g.key]
            })
            await $.store.set('folded', next).catch(() => {})
          }
          const head = (
            <Box key={`head-${g.key}`} flexDirection="row">
              <Button key={`fold-${g.key}`} plain dimColor label={shut ? '▸' : '▾'} onPress={fold} />
              <Text> </Text>
              <Text bold>{g.label} <Text dimColor>{g.cards.length}</Text></Text>
            </Box>
          )
          if (shut) {
            const ids = g.cards.map(c => `#${c.id}`).join(' ')
            return (
              <Box key={g.key} flexDirection="row" paddingX={2}>
                {head}
                <Text dimColor wrap="truncate-end">{'  '}{clip(ids, Math.max(8, columns - 4 - cells(g.label) - 8))}</Text>
              </Box>
            )
          }
          const running = g.key === 'running'
          // Backlog and Ready need no column label: the heading says it. A running card shows its stage instead.
          const pad = running
            ? Math.max(0, ...g.cards.map(c => stage(c.status) === '' ? 0 : cells(stage(c.status)) + 2))
            : g.key === 'backlog' || g.key === 'ready' ? 0
            : Math.max(...g.cards.map(c => cells(base(c.status))))
          const border = running ? 'cyan' : g.cards.some(c => c.status === 'Blocked') ? 'red'
            : g.key === 'needs-you' ? 'yellow' : 'gray'
          return (
            <Box key={g.key} flexDirection="column" borderStyle="round" borderColor={border} paddingX={1}>
              {head}
              {g.cards.map(c => card(c, pad))}
            </Box>
          )
        })}
        {earnedBadges.length > 0 && (
          <Box key="badges" flexDirection="row" flexWrap="wrap">
            <Text dimColor>{`実績 ${earnedBadges.length}/${BADGES.length} `}</Text>
            {earnedBadges.map(x => tip(`badge-${x.id}`, <Text color="yellow">{`★${x.name} `}</Text>, x.desc, true))}
          </Box>
        )}
        <Box flexWrap="wrap">
          <Text dimColor>{b.checkedAt} 時点 · 1 分ごとに更新 </Text>
          {refreshButton}
          {toggle}
        </Box>
      </Box>
    )
  })
}
