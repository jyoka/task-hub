import { SLOW_MIN_RUNS, jsonLines } from './panel'

// Achievements, judged from metrics.jsonl alone (one line per finished run, in the order the runs finished).
// events.jsonl is not used: a card closed by merging its PR has no `Done` there, so no badge counts merges.
export type Badge = { id: string; name: string; desc: string }
export const STREAKS = [5, 10]
export const DAYS = [5, 15]
export const RESEARCH = 3
export const AGENTS = ['claude', 'kiro', 'codex', 'pi']
export const BADGES: Badge[] = [
  ...STREAKS.map((n, k) => ({ id: `streak-${n}`, name: ['順風', '快進撃'][k]!, desc: `retry なしの pass が ${n} 回続いた` })),
  ...DAYS.map((n, k) => ({ id: `day-${n}`, name: ['大漁', '大船団'][k]!, desc: `1 日に ${n} 件 In review にした` })),
  { id: `research-${RESEARCH}`, name: '探検家', desc: `調べもの(research)を ${RESEARCH} 件 In review にした` },
  { id: 'fast', name: '追い風', desc: '普段の半分以下の時間で In review にした' },
  ...AGENTS.map(a => ({ id: `first-${a}`, name: `初航海 ${a}`, desc: `${a} の初めてのタスクが In review になった` })),
]

const str = (v: unknown): string => typeof v === 'string' ? v : ''
const num = (v: unknown): number | undefined => typeof v === 'number' && Number.isFinite(v) ? v : undefined

// The local calendar day a run finished on: "1 日に" is the user's day, not UTC's.
const day = (iso: string): string => {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const d = new Date(t)
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

// The ids of BADGES the runs in metrics.jsonl earn, in BADGES order. Lines that are not runs are skipped.
export const earned = (metrics: string): string[] => {
  const runs = jsonLines(metrics)
  const got = new Set<string>()
  let streak = 0
  const perDay = new Map<string, Set<string>>()
  const research = new Set<string>() // the ids of research cards, so a card reviewed twice counts once
  const before = new Map<string, number[]>() // each agent's earlier run times, sorted, as slowThreshold reads them
  for (const r of runs) {
    const reviews = Array.isArray(r.reviews) ? r.reviews : []
    const done = r.status === 'In review'
    // A run where the agent never ran (it could not start, or its setup failed) neither extends nor breaks a streak.
    if (r.blocked_by !== 'start' && r.blocked_by !== 'setup') {
      streak = done && reviews[0] === 'pass' && r.retried !== true ? streak + 1 : 0
      for (const n of STREAKS) if (streak >= n) got.add(`streak-${n}`)
    }
    const agent = str(r.agent)
    const seconds = num(r.seconds)
    const times = before.get(agent) ?? []
    // "Usual" as the pane and bin/task count it (slowThreshold), from the runs before this one only.
    const usual = times.length >= SLOW_MIN_RUNS ? times[Math.floor(times.length / 2)]! : null
    if (r.blocked_by !== 'start' && r.blocked_by !== 'setup') {
      const t = seconds ?? 0
      let at = 0
      while (at < times.length && times[at]! <= t) at++
      times.splice(at, 0, t)
      before.set(agent, times)
    }
    if (!done) continue
    const id = str(r.id)
    const d = day(str(r.finished))
    if (id !== '' && d !== '') {
      const ids = perDay.get(d) ?? new Set<string>()
      ids.add(id)
      perDay.set(d, ids)
      for (const n of DAYS) if (ids.size >= n) got.add(`day-${n}`)
    }
    // A research task is the one kind that reaches In review with no file changed (bin/task blocks the others).
    if (num(r.files) === 0 && id !== '') {
      research.add(id)
      if (research.size >= RESEARCH) got.add(`research-${RESEARCH}`)
    }
    if (AGENTS.includes(agent)) got.add(`first-${agent}`)
    if (usual !== null && usual > 0 && seconds !== undefined && seconds <= usual / 2) got.add('fast')
  }
  return BADGES.filter(b => got.has(b.id)).map(b => b.id)
}

// The badges in `unlocked` not yet in `known`, and the one toast line for all of them (several at once share a toast).
export const fresh = (unlocked: string[], known: readonly string[]): { ids: string[]; toast?: string } => {
  const ids = unlocked.filter(id => !known.includes(id))
  if (ids.length === 0) return { ids }
  const names = ids.map(id => BADGES.find(b => b.id === id)?.name ?? id)
  return { ids, toast: `実績解除: ${names.join('、')}` }
}
