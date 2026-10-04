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
