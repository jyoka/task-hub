// The packaged extension in a real VS Code or Kiro: node test/host/check.mjs <the IDE's CLI>
// e.g. "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" or /Applications/Kiro.app/Contents/Resources/app/bin/code
// Builds the VSIX, installs it into a throwaway extensions folder and profile (never the usual ones), and starts the IDE
// with HOME set to a throwaway task-hub (a stand-in `task` that prints a board, a run with a git worktree, its log and
// board-cache.json). suite.cjs then drives Goal, Changes and Log in the extension host. Nothing reads the real board.
import { execFileSync, spawn } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..', '..')
const DEADLINE_MS = 180_000
const cli = process.argv[2]
if (!cli || !existsSync(cli)) {
  console.error('usage: node test/host/check.mjs <path to the IDE CLI, e.g. .../Contents/Resources/app/bin/code>')
  process.exit(2)
}

const root = mkdtempSync(join(tmpdir(), 'task-hub-host-'))
const home = join(root, 'home')
const env = { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_AUTHOR_NAME: 't',
  GIT_AUTHOR_EMAIL: 't@example.com', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@example.com' }
const g = (cwd, ...args) => execFileSync('git', args, { cwd, env, encoding: 'utf8' })

try {
  // the task: a repo, task-hub's clone of it, the worktree of task 900 with committed and uncommitted work
  const origin = join(root, 'origin')
  mkdirSync(origin)
  g(origin, 'init', '-q', '-b', 'main')
  writeFileSync(join(origin, 'a.txt'), 'one\ntwo\n')
  g(origin, 'add', '-A')
  g(origin, 'commit', '-q', '-m', 'base')
  const clone = join(home, '.local', 'share', 'task-hub', 'repos', 'jyoka', 'demo')
  mkdirSync(dirname(clone), { recursive: true })
  g(root, 'clone', '-q', origin, clone)
  const wt = join(home, '.local', 'share', 'task-hub', 'worktrees', '900')
  g(clone, 'worktree', 'add', '-q', '-b', 'task/900', wt, 'origin/main')
  writeFileSync(join(wt, 'a.txt'), 'one\nTWO\n')
  g(wt, 'commit', '-q', '-am', 'work')
  writeFileSync(join(wt, 'b.txt'), 'untracked\n')
  const state = join(home, '.local', 'state', 'task-hub')
  mkdirSync(join(state, 'runs'), { recursive: true })
  mkdirSync(join(state, 'logs'), { recursive: true })
  const log = join(state, 'logs', '900.log')
  writeFileSync(log, Array.from({ length: 200 }, (_, i) => `· Bash: step ${i}`).join('\n') + '\n')
  writeFileSync(join(state, 'runs', '900.json'), JSON.stringify({ repo: 'jyoka/demo', title: 'Demo task', base: '',
    branch: 'task/900', worktree: wt, log }))
  writeFileSync(join(state, 'board-cache.json'), JSON.stringify({ key: ['jyoka', '2', 'jyoka/tasks'],
    fetched_at: Date.now() / 1000, items: [{ id: 'I1', content: { number: 900, title: 'Demo task',
      url: 'https://github.com/jyoka/tasks/issues/900', body: '### Goal\nMake **demo** work.\n', state: 'OPEN',
      repository: { nameWithOwner: 'jyoka/tasks' } }, status: { name: 'In progress' }, repo: { text: 'jyoka/demo' } }] }))
  // the stand-in `task`: prints a board, starts nothing
  mkdirSync(join(home, '.local', 'bin'), { recursive: true })
  writeFileSync(join(home, '.local', 'bin', 'task'), '#!/bin/sh\nprintf \'%s\\n\' ' +
    '"counts: In progress=1" "tasks[1]{id,title,status,repo,agent,waits_for}:" \'  "900",Demo task,In progress,jyoka/demo,claude,""\'\n')
  chmodSync(join(home, '.local', 'bin', 'task'), 0o755)

  // the runner extension (just a folder VS Code accepts as extensionDevelopmentPath) and the profile
  const runner = join(root, 'runner')
  mkdirSync(runner)
  writeFileSync(join(runner, 'package.json'), JSON.stringify({ name: 'task-hub-host-check', publisher: 'test',
    version: '0.0.0', engines: { vscode: '^1.90.0' } }))
  const profile = ['--user-data-dir', join(root, 'user'), '--extensions-dir', join(root, 'extensions')]
  // the throwaway profile only: no welcome page or onboarding over the editors
  mkdirSync(join(root, 'user', 'User'), { recursive: true })
  writeFileSync(join(root, 'user', 'User', 'settings.json'), JSON.stringify({ 'workbench.startupEditor': 'none',
    'workbench.welcomePage.experimentalOnboarding': false, 'workbench.welcomePage.walkthroughs.openOnInstall': false,
    'kiro.welcome.showWhatsNew': false }))
  const vsix = execFileSync(process.execPath, ['--disable-warning=ExperimentalWarning', join(ROOT, 'scripts', 'package.mjs')],
    { cwd: ROOT, encoding: 'utf8' }).trim().replace(/^wrote /, '')
  execFileSync(cli, [...profile, '--install-extension', vsix, '--force'], { env: { ...env, HOME: home }, stdio: 'inherit',
    timeout: 60_000 })

  const result = join(root, 'result.json')
  // The CLI may return before the IDE does: wait for suite.cjs's result (it exits the IDE when done), at most DEADLINE_MS.
  const child = spawn(cli, [...profile, '--extensionDevelopmentPath', runner,
    '--extensionTestsPath', join(HERE, 'suite.cjs'), '--skip-welcome', '--skip-release-notes', '--disable-telemetry',
    '--disable-workspace-trust', '--new-window'],
  { env: { ...env, HOME: home, TASKHUB_HOST_HOME: home, TASKHUB_HOST_WT: wt, TASKHUB_HOST_LOG: log,
    TASKHUB_HOST_RESULT: result }, stdio: 'inherit' })
  let code = null
  child.on('exit', c => { code = c })
  const end = Date.now() + DEADLINE_MS
  const done = () => { try { return JSON.parse(readFileSync(result, 'utf8')).done } catch { return false } }
  while (!done() && Date.now() < end) await new Promise(r => setTimeout(r, 500))
  // The IDE started by the CLI stays open after the suite: stop every process of this throwaway profile.
  if (code === null) child.kill('SIGKILL')
  const stop = signal => { try { execFileSync('pkill', [`-${signal}`, '-f', join(root, 'user')]) } catch { /* none left */ } }
  stop('TERM')
  await new Promise(r => setTimeout(r, 3000))
  stop('KILL')
  if (!existsSync(result)) {
    console.error(`no result from the extension host (exit ${code})`)
    process.exitCode = 1
  } else {
    const r = JSON.parse(readFileSync(result, 'utf8'))
    console.log(`host: ${r.app} (VS Code API ${r.version})`)
    for (const c of r.results) console.log(`${c.ok ? 'ok  ' : 'FAIL'} ${c.name}${c.detail && !c.ok ? `: ${c.detail}` : ''}`)
    const failed = r.results.filter(c => !c.ok).length
    if (!r.done) console.log(`FAIL the suite did not finish within ${DEADLINE_MS / 1000} s (it stopped after the last line above)`)
    console.log(failed || !r.done ? `${failed} failed` : `all ${r.results.length} passed`)
    process.exitCode = failed || !r.done ? 1 : 0
  }
} finally {
  if (process.env.TASKHUB_HOST_KEEP) console.log(`kept ${root}`)
  else rmSync(root, { recursive: true, force: true })
}
