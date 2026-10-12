// Runs inside a real VS Code or Kiro extension host (--extensionTestsPath), started by check.mjs with a throwaway
// HOME, profile and extensions folder. Drives the installed VSIX's Goal, Changes and Log commands and writes what it
// saw to TASKHUB_HOST_RESULT. Not part of `npm test` (that runs test/*.test.ts against a stand-in vscode).
const vscode = require('vscode')
const { execFileSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const { appendFileSync, readFileSync, statSync, writeFileSync } = require('node:fs')
const { homedir } = require('node:os')
const { join } = require('node:path')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const until = async (cond, ms = 8000) => {
  const end = Date.now() + ms
  while (!(await cond())) {
    if (Date.now() > end) return false
    await sleep(50)
  }
  return true
}
// A step that does not finish in `ms` fails with its name instead of hanging the suite.
const step = (name, p, ms = 20000) => Promise.race([p, sleep(ms).then(() => { throw new Error(`${name}: no answer in ${ms} ms`) })])
const gitState = wt => {
  const git = (...a) => execFileSync('git', a, { cwd: wt, encoding: 'utf8', env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' } })
  const index = git('rev-parse', '--git-path', 'index').trim()
  const path = index.startsWith('/') ? index : join(wt, index)
  return JSON.stringify({ index: createHash('sha256').update(readFileSync(path)).digest('hex'), mtime: statSync(path).mtimeMs,
    head: git('rev-parse', 'HEAD'), refs: git('for-each-ref'), status: git('status', '--porcelain', '-uall') })
}

exports.run = async () => {
  const results = []
  // Written after every check (done: false until the end), so a host that hangs still shows how far it got.
  const save = done => writeFileSync(process.env.TASKHUB_HOST_RESULT, JSON.stringify({
    app: vscode.env.appName, version: vscode.version, done, results }, null, 1))
  const check = (name, ok, detail = '') => {
    results.push({ name, ok: Boolean(ok), detail: String(detail) })
    save(false)
  }
  const wt = process.env.TASKHUB_HOST_WT
  const log = process.env.TASKHUB_HOST_LOG
  try {
    check('HOME is the throwaway one', homedir() === process.env.TASKHUB_HOST_HOME, homedir())
    if (homedir() !== process.env.TASKHUB_HOST_HOME) throw new Error('not the test HOME: stopping before reading anything')
    const ext = vscode.extensions.getExtension('jyoka.task-hub-board')
    check('the VSIX is installed (not loaded from the source folder)', ext && !ext.extensionPath.includes('board-extension'),
      ext && ext.extensionPath)
    await ext.activate()
    const commands = await vscode.commands.getCommands(true)
    for (const c of ['taskHub.task.goal', 'taskHub.task.changes', 'taskHub.task.log', 'taskHub.log.follow',
      'taskHub.log.pause', 'taskHub.board.show', 'taskHub.board.refresh']) check(`command ${c}`, commands.includes(c))
    const menus = ext.packageJSON.contributes.menus['view/item/context']
    check('card context actions', menus.filter(m => m.when.includes('viewItem == taskHub.card')).length === 6)

    // The providers alone (no editor shown): what each tab would read
    const doc = uri => step(`open ${uri}`, vscode.workspace.openTextDocument(vscode.Uri.parse(uri)))
    check('provider: Goal', (await doc('taskhub-goal:/900/%23900%20Goal.md')).getText().includes('Make **demo** work.'))
    check('provider: Log', (await doc('taskhub-log:/900/%23900%20Log.log')).getText().includes('step 199'))
    const fork = execFileSync('git', ['merge-base', 'origin/main', 'HEAD'], { cwd: wt, encoding: 'utf8' }).trim()
    check('provider: diff base side', (await doc(`taskhub-diff:/900/base/a.txt?${fork}`)).getText() === 'one\ntwo\n')
    check('provider: diff worktree side', (await doc(`taskhub-diff:/900/worktree/a.txt?${fork}`)).getText() === 'one\nTWO\n')

    // Control: can this host show an editor at all? (Kiro in a fresh profile, not signed in, never answers
    // showTextDocument, even for an untitled document.) If not, the editor steps below cannot be checked here.
    const shown = await step('show an untitled document', vscode.window.showTextDocument(
      await vscode.workspace.openTextDocument({ content: '' })), 10000).then(() => true, () => false)
    check('control: the host shows an ordinary editor', shown,
      'showTextDocument of an untitled document did not answer: the editor steps are not checked in this host')
    if (!shown) {
      save(true)
      return
    }
    await vscode.commands.executeCommand('workbench.action.revertAndCloseActiveEditor')

    // Goal
    await step('Goal command', vscode.commands.executeCommand('taskHub.task.goal', '900'))
    const goal = vscode.window.activeTextEditor
    check('Goal: tab', goal && goal.document.uri.scheme === 'taskhub-goal', goal && goal.document.uri.toString())
    check('Goal: tab title', vscode.window.tabGroups.activeTabGroup.activeTab?.label === '#900 Goal · demo.md',
      vscode.window.tabGroups.activeTabGroup.activeTab?.label)
    check('Goal: Markdown', goal.document.languageId === 'markdown', goal.document.languageId)
    check('Goal: body', goal.document.getText().includes('Make **demo** work.'), goal.document.getText().slice(0, 300))
    // Read only: VS Code makes TextDocumentContentProvider documents read-only in the editor. Not checked here: an
    // extension's TextEditor.edit() bypasses that, and `type` reaches no editor while the window has no OS focus.

    // Changes
    const before = gitState(wt)
    await step('Changes command', vscode.commands.executeCommand('taskHub.task.changes', '900'))
    await sleep(800)
    await vscode.commands.executeCommand('workbench.action.acceptSelectedQuickOpenItem')
    const diffTab = () => vscode.window.tabGroups.all.flatMap(g => g.tabs).find(t => t.input instanceof vscode.TabInputTextDiff)
    check('Changes: diff editor opened', await until(() => Boolean(diffTab())), diffTab()?.label)
    const tab = diffTab()
    if (tab) {
      check('Changes: diff title', tab.label === '#900 a.txt · demo (origin/main ↔ 作業中)', tab.label)
      const left = await vscode.workspace.openTextDocument(tab.input.original)
      const right = await vscode.workspace.openTextDocument(tab.input.modified)
      check('Changes: base side', left.getText() === 'one\ntwo\n', JSON.stringify(left.getText()))
      check('Changes: worktree side', right.getText() === 'one\nTWO\n', JSON.stringify(right.getText()))
      check('Changes: the file on disk unchanged', readFileSync(join(wt, 'a.txt'), 'utf8') === 'one\nTWO\n')
    }
    await vscode.commands.executeCommand('workbench.action.closeQuickOpen')
    check('Changes: index, HEAD, refs and status unchanged', gitState(wt) === before)

    // Log
    await step('Log command', vscode.commands.executeCommand('taskHub.task.log', '900'))
    const logEd = vscode.window.activeTextEditor
    check('Log: tab', logEd.document.uri.scheme === 'taskhub-log', logEd.document.uri.toString())
    check('Log: tab title', vscode.window.tabGroups.activeTabGroup.activeTab?.label === '#900 Log · demo.log',
      vscode.window.tabGroups.activeTabGroup.activeTab?.label)
    const lastVisible = () => logEd.visibleRanges.at(-1)?.end.line ?? -1
    appendFileSync(log, 'appended while following\n')
    check('Log: follows new output', await until(() => logEd.document.getText().includes('appended while following')))
    check('Log: scrolled to the end', await until(() => lastVisible() >= logEd.document.lineCount - 2),
      `${lastVisible()} / ${logEd.document.lineCount}`)
    await vscode.commands.executeCommand('taskHub.log.pause')
    logEd.revealRange(new vscode.Range(0, 0, 0, 0), vscode.TextEditorRevealType.AtTop)
    await sleep(300)
    const top = logEd.visibleRanges[0].start.line
    const text = logEd.document.getText()
    appendFileSync(log, 'appended while paused\n')
    await sleep(3000)
    check('Log: paused keeps the text', logEd.document.getText() === text)
    check('Log: paused keeps the place', logEd.visibleRanges[0].start.line === top, `${top} → ${logEd.visibleRanges[0].start.line}`)
    await vscode.commands.executeCommand('taskHub.log.follow')
    check('Log: follow again reads it', await until(() => logEd.document.getText().includes('appended while paused')))
    check('Log: follow again goes to the end', await until(() => lastVisible() >= logEd.document.lineCount - 2))
    // focus: another editor active, the log grows, the active editor stays
    await vscode.commands.executeCommand('taskHub.task.goal', '900')
    appendFileSync(log, 'appended in the background\n')
    await until(() => logEd.document.getText().includes('appended in the background'))
    check('Log: an update does not take the focus', vscode.window.activeTextEditor?.document.uri.scheme === 'taskhub-goal')
    // A log tab that comes back without the Log command (as a restored window brings it) follows again. Not by
    // Reopen Closed Editor: VS Code 1.141 does not reopen a tab of a content provider, it reopened the untitled
    // document above instead, and the window then stopped answering showTextDocument.
    const logTab = () => vscode.window.tabGroups.all.flatMap(g => g.tabs)
      .find(t => t.input instanceof vscode.TabInputText && t.input.uri.scheme === 'taskhub-log')
    const logUri = logTab().input.uri
    await step('close the log tab', vscode.window.tabGroups.close(logTab()))
    check('Log: tab closed', await until(() => !logTab()))
    await step('show the log URI again', vscode.window.showTextDocument(logUri, { preview: false }))
    check('Log: tab back', await until(() => Boolean(logTab())))
    appendFileSync(log, 'appended after reopening\n')
    const reopened = () => vscode.workspace.textDocuments.find(d => d.uri.toString() === logUri.toString())
    check('Log: a tab back without the Log command follows new output',
      await until(() => reopened()?.getText().includes('appended after reopening')))

    // Missing things say why
    await vscode.commands.executeCommand('taskHub.task.changes', '901')
    check('Changes of a task that never ran here: no diff for it',
      !vscode.window.tabGroups.all.flatMap(g => g.tabs).some(t => t.input instanceof vscode.TabInputTextDiff
        && t.input.modified.path.startsWith('/901/')))

    // What the API lets a test see: taskHub.board.focus (the command the host makes for the board view) answers
    // without an error. Whether the sidebar then shows the board is not visible to an extension.
    // What the API lets a test see: taskHub.board.focus (the command the host makes for the board view) answers
    // without an error. Whether the sidebar then shows the board is not visible to an extension.
    const back = await step('Back to the board', vscode.commands.executeCommand('taskHub.board.show'), 10000)
      .then(() => '', e => String(e && e.message || e))
    check('Back to the board: taskHub.board.show → taskHub.board.focus answers without an error', back === '', back)
  } catch (e) {
    check('no exception', false, e && e.stack)
    check('(state) tabs', false, vscode.window.tabGroups.all.flatMap(g => g.tabs.map(t =>
      `${t.label} [${t.input && t.input.constructor && t.input.constructor.name}${t.input && t.input.viewType ? ` ${t.input.viewType}` : ''}]`)).join(' | '))
    check('(state) editors', false, vscode.window.visibleTextEditors.map(e => e.document.uri.toString()).join(' | '))
  }
  save(true)
}
