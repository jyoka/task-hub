import type { Board, Card } from '../types'

// One row of `task list`: comma-separated; a quoted field is a JSON string (`bin/task` q() uses json.dumps).
const fields = (line: string): string[] => {
  const out: string[] = []
  let i = 0
  while (i <= line.length) {
    if (line[i] === '"') {
      let end = i + 1
      while (end < line.length && line[end] !== '"') end += line[end] === '\\' ? 2 : 1
      const raw = line.slice(i, end + 1)
      try { out.push(JSON.parse(raw)) } catch { out.push(raw) }
      i = end + 1
    } else {
      const end = line.indexOf(',', i)
      out.push(line.slice(i, end === -1 ? line.length : end))
      i = end === -1 ? line.length : end
    }
    if (line[i] !== ',') break
    i++
  }
  return out
}

// Reads the output of `task list` (counts line, then tasks[n]{id,title,status,repo,agent,waits_for} rows).
export const parseList = (text: string, checkedAt: string): Board => {
  const counts: Record<string, number> = {}
  const cards: Card[] = []
  for (const line of text.split('\n')) {
    if (line.startsWith('counts:')) {
      for (const pair of line.slice('counts:'.length).split(',')) {
        const [name, n] = pair.split('=')
        if (name && n) counts[name.trim()] = Number(n)
      }
    } else if (line.startsWith('  ')) {
      const [id = '', title = '', status = '', repo = '', , waitsFor = ''] = fields(line.trim())
      cards.push({ id, title, status, repo, waitsFor })
    }
  }
  return { counts, cards, checkedAt, error: '' }
}

// Board order. A running card shows as "In progress › review": rank it by the column, and put unknown columns last.
const ORDER = ['Blocked', 'In review', 'wait for merge', 'In progress', 'Ready', 'Backlog']
export const base = (status: string): string => status.split(' › ')[0] ?? status
const rank = (status: string): number => {
  const i = ORDER.indexOf(base(status))
  return i === -1 ? ORDER.length : i
}
export const byColumn = (cards: Card[]): Card[] => [...cards].sort((x, y) => rank(x.status) - rank(y.status))

// Why `task list` failed: `bin/task` fail() prints "error: ..." to stdout and leaves stderr empty.
export const failure = (exitCode: number, stdout: string, stderr: string): string =>
  stderr.split('\n').map(l => l.trim()).filter(l => l !== '').pop()
  || stdout.split('\n').find(l => l.startsWith('error:'))?.slice('error:'.length).trim()
  || `exit ${exitCode}`

// The status line entry: only what needs the user, plus what is running.
export const summary = (board: Board): string | undefined => {
  if (board.error) return 'task: 読めない'
  const c = board.counts
  const parts = [
    ['実行中', c['In progress']],
    ['レビュー待ち', c['In review']],
    ['止まり', c['Blocked']],
  ].filter(([, n]) => Number(n) > 0).map(([label, n]) => `${label}${n}`)
  return parts.length ? `task: ${parts.join(' ')}` : undefined
}
