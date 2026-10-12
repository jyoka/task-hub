// What the Goal, Changes and Log tabs show for one task, read from what task-hub already keeps on this machine:
// runs/<id>.json (the run's worktree, base, log), board-cache.json (the Issue body `task list` last read) and the log.
// Read only: git runs with an argument list (no shell), only the subcommands in READ_ONLY, never takes the index lock.
// No `vscode` here, so tests run it as is.
import { execFile } from 'node:child_process'
import { copyFile, lstat, mkdtemp, open, readFile, readlink, realpath, rm, stat } from 'node:fs/promises'
import { homedir, tmpdir } from 'node:os'
import { delimiter, dirname, isAbsolute, join, normalize, sep } from 'node:path'

// task-hub's own files in a worktree (bin/task NEVER_COMMIT): never part of the PR, so never shown as a change.
export const INTERNAL = ['.task-report.md', '.task-review.md', '.task-replan.md']
// A side of a diff larger than this is described, not shown. The log tab shows its last LOG_MAX bytes.
export const TEXT_MAX = 1024 * 1024
export const LOG_MAX = 1024 * 1024
// More changed files than this are cut from the list, with a line saying how many.
export const LIST_MAX = 2000
const GIT_TIMEOUT_MS = 30_000
// The only git subcommands run. Every call also turns off the fsmonitor hook and the index extensions git would write
// beside the index, and reads attributes from the empty tree (GIT_ATTR_SOURCE), so no clean filter (Git LFS and the
// like) runs; diffs turn off external diff and textconv programs. `git diff` refreshes the index it reads even with
// GIT_OPTIONAL_LOCKS=0, so it reads a throwaway copy (GIT_INDEX_FILE) and the worktree's index is never written.
export const READ_ONLY = ['rev-parse', 'merge-base', 'symbolic-ref', 'diff', 'ls-files', 'cat-file']
const EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
const SAFE = ['-c', 'core.fsmonitor=false', '-c', 'core.splitIndex=false', '-c', 'core.untrackedCache=false',
  '-c', 'core.quotepath=false']

const state = (): string => join(homedir(), '.local', 'state', 'task-hub')
const where = (path: string): string => path.startsWith(homedir() + sep) ? `~${path.slice(homedir().length)}` : path

export type RunRecord = { repo: string; title: string; base: string; branch: string; worktree: string; log: string }

// A task id is the Issue number: anything else never becomes a path.
export const validId = (id: string): boolean => /^[1-9]\d{0,9}$/.test(id)

// runs/<id>.json as task-hub's launch wrote it; null when this machine has no run of the task (never run here, or
// cleaned up after Done).
export const readRun = async (id: string): Promise<RunRecord | null> => {
  if (!validId(id)) return null
  let data: unknown
  try { data = JSON.parse(await readFile(join(state(), 'runs', `${id}.json`), 'utf8')) } catch { return null }
  if (typeof data !== 'object' || data === null) return null
  const d = data as Record<string, unknown>
  const s = (k: string): string => typeof d[k] === 'string' ? d[k] as string : ''
  return { repo: s('repo'), title: s('title'), base: s('base'), branch: s('branch'), worktree: s('worktree'), log: s('log') }
}

// ---------- Goal ----------

export type Goal = { found: true; title: string; repo: string; url: string; body: string; fetchedAt: number; stale: boolean }
  | { found: false; reason: string }

const readJson = async (path: string): Promise<unknown> => JSON.parse(await readFile(path, 'utf8'))

// The card's Issue body as the last `task list` (or `task watch`) read it into board-cache.json. Nothing is asked of
// GitHub here: the board's refresh button reads it again.
export const readGoal = async (id: string): Promise<Goal> => {
  let cache: any
  try { cache = await readJson(join(state(), 'board-cache.json')) } catch {
    return { found: false, reason: 'ボードのキャッシュ(board-cache.json)がありません。ボードの更新ボタンで読み直してください' }
  }
  const issues = Array.isArray(cache?.key) && typeof cache.key[2] === 'string' ? cache.key[2].toLowerCase() : ''
  const items: any[] = Array.isArray(cache?.items) ? cache.items : []
  const item = items.find(i => String(i?.content?.number ?? '') === id
    && (!issues || String(i?.content?.repository?.nameWithOwner ?? '').toLowerCase() === issues))
  if (!item) {
    return { found: false, reason: `#${id} はボードのキャッシュにありません(Done になった、またはボードをまだ読んでいない)。` +
      `ボードの更新ボタンで読み直すか、ターミナルの task show ${id} --full で読めます` }
  }
  const fetchedAt = typeof cache.fetched_at === 'number' ? cache.fetched_at * 1000 : 0
  let changed = 0
  try { changed = Number(await readFile(join(state(), 'board-cache.stale'), 'utf8')) * 1000 } catch { /* no change yet */ }
  const c = item.content
  return { found: true, title: String(c.title ?? ''), repo: String(item.repo?.text ?? ''), url: String(c.url ?? ''),
    body: String(c.body ?? ''), fetchedAt, stale: changed > fetchedAt }
}

const ago = (ms: number): string => ms < 60_000 ? '1 分以内' : ms < 3_600_000 ? `${Math.floor(ms / 60_000)} 分前`
  : ms < 86_400_000 ? `${Math.floor(ms / 3_600_000)} 時間前` : `${Math.floor(ms / 86_400_000)} 日前`

// The Goal tab: a line saying which task and when the board was read, then the Issue body as it is.
export const goalText = (id: string, g: Extract<Goal, { found: true }>, now: number): string => {
  const at = g.fetchedAt ? `${new Date(g.fetchedAt).toLocaleString()}(${ago(now - g.fetchedAt)})` : '不明'
  const head = [
    `<!-- task-hub #${id}: 読み取り専用。ボードのキャッシュ(board-cache.json)の Issue 本文です -->`,
    `> **#${id} ${g.title}** · ${g.repo || 'repo 不明'}${g.url ? ` · ${g.url}` : ''}`,
    `> ボードを読んだ時刻: ${at}。GitHub の今の本文と違うことがあります。ボードを更新してから開き直すと読み直します。`,
    ...(g.stale ? ['> そのあと task-hub がボードを変えています(Status など)。'] : []),
  ]
  return `${head.join('\n')}\n\n---\n\n${g.body.trim()}\n`
}

// ---------- Changes ----------

const childPath = (): string => {
  const have = (process.env.PATH ?? '').split(delimiter).filter(p => p !== '')
  const more = [join(homedir(), '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin'].filter(p => !have.includes(p))
  return [...have, ...more].join(delimiter)
}

export class GitError extends Error {}

// The IDE's environment without GIT_* (a GIT_DIR or GIT_WORK_TREE there would point git at another repository).
const gitEnv = (index: string): NodeJS.ProcessEnv => ({
  ...Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('GIT_'))),
  PATH: childPath(), GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0', GIT_ATTR_SOURCE: EMPTY_TREE, LC_ALL: 'C',
  ...(index ? { GIT_INDEX_FILE: index } : {}),
})

// One git command in the worktree, read only. Output as bytes (a file's content may not be text).
export const git = (wt: string, args: string[], index = ''): Promise<Buffer> => {
  if (!READ_ONLY.includes(args[0] ?? '')) return Promise.reject(new GitError(`git ${args[0]} は使いません(読むだけ)`))
  return new Promise((resolve, reject) => {
    execFile('git', [...SAFE, '-C', wt, ...args], {
      encoding: 'buffer', maxBuffer: 64 * 1024 * 1024, timeout: GIT_TIMEOUT_MS, env: gitEnv(index),
    }, (err, stdout, stderr) => {
      if (!err) resolve(stdout)
      else if ((err as any).code === 'ENOENT') reject(new GitError('git が見つかりません'))
      else if (err.killed) reject(new GitError(`git ${args[0]} が ${GIT_TIMEOUT_MS / 1000} 秒で終わりませんでした`))
      else reject(new GitError((stderr.toString().trim() || err.message).split('\n')[0] ?? ''))
    })
  })
}
const gitText = async (wt: string, args: string[], index = ''): Promise<string> =>
  (await git(wt, args, index)).toString('utf8')

// Runs `body` with a copy of the worktree's index (git replaces the index by a rename, so the copy is a whole one).
const withIndexCopy = async <T>(wt: string, body: (index: string) => Promise<T>): Promise<T> => {
  const path = (await gitText(wt, ['rev-parse', '--git-path', 'index'])).trim()
  const dir = await mkdtemp(join(tmpdir(), 'task-hub-index-'))
  try {
    const copy = join(dir, 'index')
    await copyFile(isAbsolute(path) ? path : join(wt, path), copy)
    return await body(copy)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

export type Change = { path: string; status: 'added' | 'deleted' | 'modified' | 'untracked' | 'type'; binary: boolean }
export type Changes = { worktree: string; baseRef: string; fork: string; branch: string; repo: string; title: string
  files: Change[]; more: number }

// The worktree of task <id>, or why there is none. Never another checkout: only the path runs/<id>.json names.
export const worktreeOf = async (id: string): Promise<{ run: RunRecord } | { reason: string }> => {
  const run = await readRun(id)
  if (!run) return { reason: `#${id} はこのマシンで動いていません(runs/${id}.json がない)。Done で片付いたか、別のマシンで動いたタスクです` }
  if (!run.worktree) return { reason: `#${id} の実行の記録に worktree がありません` }
  try {
    if (!(await stat(join(run.worktree, '.git')).catch(() => null))) throw new Error()
  } catch {
    return { reason: `#${id} の worktree がありません: ${where(run.worktree)}(片付け済み)。もう一度動かすと作り直されます` }
  }
  return { run }
}

// What the task branches from: the card's Base branch, else origin's default branch (bin/task base_ref()).
const baseRef = async (wt: string, base: string): Promise<string> => {
  if (base) return `origin/${base}`
  const head = await gitText(wt, ['symbolic-ref', '--short', 'refs/remotes/origin/HEAD']).catch(() => '')
  return head.trim() || 'origin/main'
}

const STATUS: Record<string, Change['status']> = { A: 'added', D: 'deleted', M: 'modified', T: 'type' }
const fields = (out: string): string[] => out.split('\0').filter(s => s !== '')
const internal = (path: string): boolean => INTERNAL.includes(path)

// The whole task change: from where the branch left its base (merge-base) to the worktree as it is now, committed
// and not, plus files git does not track yet (task-hub commits them too). Nothing is staged or written.
export const readChanges = async (id: string): Promise<Changes | { reason: string }> => {
  const found = await worktreeOf(id)
  if ('reason' in found) return found
  const { run } = found
  const wt = run.worktree
  const ref = await baseRef(wt, run.base)
  let fork: string
  try {
    fork = (await gitText(wt, ['merge-base', ref, 'HEAD'])).trim()
  } catch (e) {
    return { reason: `#${id} の base(${ref})と HEAD の分かれ目が見つかりません: ${(e as Error).message}` }
  }
  if (!/^[0-9a-f]{7,64}$/.test(fork)) return { reason: `#${id} の base(${ref})と HEAD の分かれ目が見つかりません` }
  const opts = ['--no-ext-diff', '--no-textconv', '--no-renames', '-z']
  try {
    const [names, numstat, others] = await withIndexCopy(wt, index => Promise.all([
      gitText(wt, ['diff', '--name-status', ...opts, fork, '--'], index),
      gitText(wt, ['diff', '--numstat', ...opts, fork, '--'], index),
      gitText(wt, ['ls-files', '--others', '--exclude-standard', '-z'], index),
    ]))
    const binary = new Set<string>()
    const n = fields(numstat)
    for (const line of n) {
      const [plus, minus, ...rest] = line.split('\t')
      if (plus === '-' && minus === '-') binary.add(rest.join('\t'))
    }
    const files: Change[] = []
    const f = fields(names)
    for (let i = 0; i + 1 < f.length; i += 2) {
      const path = f[i + 1] ?? ''
      if (path && !internal(path)) files.push({ path, status: STATUS[f[i]?.[0] ?? ''] ?? 'modified', binary: binary.has(path) })
    }
    for (const path of fields(others)) {
      if (path && !internal(path)) files.push({ path, status: 'untracked', binary: false })
    }
    files.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)
    return { worktree: wt, baseRef: ref, fork, branch: run.branch, repo: run.repo, title: run.title,
      files: files.slice(0, LIST_MAX), more: Math.max(0, files.length - LIST_MAX) }
  } catch (e) {
    return { reason: `#${id} の変更を読めませんでした: ${(e as Error).message}` }
  }
}

// A path from a URI, inside the worktree: no absolute path, no `..`.
export const safePath = (path: string): boolean => {
  if (!path || isAbsolute(path) || path.includes('\0')) return false
  const n = normalize(path)
  return n !== '..' && !n.startsWith(`..${sep}`) && !n.split(sep).includes('..')
}

const describe = (bytes: Buffer | null, size: number, what: string): string =>
  size > TEXT_MAX ? `(task-hub: ${what}は ${size} バイトあり、大きすぎるのでテキストとして出しません)\n`
  : bytes && bytes.subarray(0, 8000).includes(0) ? `(task-hub: ${what}はバイナリ(${size} バイト)なので、テキストとして出しません)\n`
  : bytes ? bytes.toString('utf8') : ''

// One side of a file's diff: at the fork commit ('base'), or in the worktree now ('worktree'). '' when the file is not
// there (added or deleted); a line in parentheses for a binary or oversized file instead of its bytes.
export const readSide = async (id: string, side: string, path: string, fork: string): Promise<string> => {
  if (side !== 'base' && side !== 'worktree') return '(task-hub: base か worktree のどちらかです)\n'
  const found = await worktreeOf(id)
  if ('reason' in found) return `(task-hub: ${found.reason})\n`
  if (!safePath(path)) return '(task-hub: このパスは worktree の外です)\n'
  const wt = found.run.worktree
  if (side === 'base') {
    if (!/^[0-9a-f]{7,64}$/.test(fork)) return '(task-hub: base のコミットがわかりません)\n'
    const spec = `${fork}:${path}`
    const type = (await gitText(wt, ['cat-file', '-t', spec]).catch(() => '')).trim()
    if (type === 'commit') return '(task-hub: base ではサブモジュールなので、中身は出しません)\n'
    if (type !== 'blob') return '' // not there, or a directory then: nothing on this side
    const size = Number((await gitText(wt, ['cat-file', '-s', spec]).catch(() => '')).trim())
    if (!Number.isFinite(size) || size <= 0) return ''
    if (size > TEXT_MAX) return describe(null, size, 'base の版')
    return describe(await git(wt, ['cat-file', 'blob', spec]), size, 'base の版')
  }
  const file = join(wt, path)
  // a directory on the way that is a symlink could lead out of the worktree: then the file is not in it
  const [root, parent] = await Promise.all([realpath(wt).catch(() => ''), realpath(dirname(file)).catch(() => '')])
  if (!root || !parent || (parent !== root && !parent.startsWith(root + sep))) return ''
  const info = await lstat(file).catch(() => null)
  if (!info) return ''
  if (info.isSymbolicLink()) return await readlink(file).catch(() => '')
  if (!info.isFile()) return '(task-hub: ふつうのファイルではないので出しません)\n'
  if (info.size > TEXT_MAX) return describe(null, info.size, '作業中の版')
  return describe(await readFile(file), info.size, '作業中の版')
}

// ---------- Log ----------

// The log task-hub writes for the task: runs/<id>.json names it; after cleanup (the record is gone) it is still
// state/logs/<id>.log, the one place bin/task launch() ever puts it.
export const logPathOf = async (id: string): Promise<string> => {
  const run = await readRun(id)
  return run?.log || join(state(), 'logs', `${id}.log`)
}

// The last LOG_MAX bytes of the log as it is now, or a line saying there is none yet.
export const readLog = async (id: string, path: string): Promise<string> => {
  let f
  try { f = await open(path, 'r') } catch {
    return `(task-hub: #${id} のログはまだありません: ${where(path)}。このマシンでまだ動いていないか、始まる前です。` +
      'できたら、ここに出ます)\n'
  }
  try {
    const { size } = await f.stat()
    const start = Math.max(0, size - LOG_MAX)
    const buf = Buffer.alloc(size - start)
    await f.read(buf, 0, buf.length, start)
    const text = buf.toString('utf8')
    return start > 0 ? `(task-hub: ${size} バイトのうち、最後の ${LOG_MAX} バイトです。全部は ${where(path)})\n` +
      text.slice(text.indexOf('\n') + 1) : text
  } finally {
    await f.close()
  }
}
