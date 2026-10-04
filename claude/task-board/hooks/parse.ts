import type { Board, Card } from '../types'

// One row of `task list`: comma-separated, a field quoted when it holds a comma or quote.
const fields = (line: string): string[] => {
  const out: string[] = []
  let cur = ''
  let isQuoted = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (isQuoted && c === '"' && line[i + 1] === '"') { cur += '"'; i++ }
    else if (c === '"') isQuoted = !isQuoted
    else if (c === ',' && !isQuoted) { out.push(cur); cur = '' }
    else cur += c
  }
  out.push(cur)
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
