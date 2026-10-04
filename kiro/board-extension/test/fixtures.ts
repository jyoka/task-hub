// What `task list` prints (bin/task cmd_list), with every column and a status it does not know.
export const LIST = `counts: Backlog=1, Ready=1, In progress=2, In review=1, wait for merge=1, Blocked=1
tasks[8]{id,title,status,repo,agent,waits_for}:
  "64","aica v1: Render 公開とデプロイ smoke(HITL)",Backlog,jyoka/aica,"",""
  "75",Test kiro automation workflow,In review,jyoka/task-hub,kiro,""
  "109","aica v2 (H): 完了時の計測",In progress,jyoka/aica,"",""
  "128",Claude Code 用のボード表示 mod,In progress › review,jyoka/task-hub,kiro,""
  "90",merge を待つカード,wait for merge,jyoka/task-hub,"",""
  "200",知らない列のカード,Someday,jyoka/task-hub,"",""
  "111",すぐ始められるカード,Ready,jyoka/task-hub,"",""
  "110","画面, 検索",Blocked,jyoka/aica,"","#109"
needs_you: 3 (Backlog to approve, In review, Blocked)
`

// What task-hub wrote to events.jsonl and metrics.jsonl (bin/task log_event, record_metrics), with broken lines.
// 109 started 12 minutes before NOW and claude (the [runner] agent) usually takes 9; 128 runs kiro, which has too
// few runs for a usual time.
export const NOW = Date.parse('2026-10-04T10:12:00Z')
export const EVENTS = [
  { time: '2026-10-04T08:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'In progress' },
  { time: '2026-10-04T09:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'Blocked', reason: 'old' },
  { time: '2026-10-04T10:00:00Z', id: '109', title: 'aica v2 (H)', repo: 'jyoka/aica', event: 'In progress' },
  { time: '2026-10-04T10:07:00Z', id: '128', title: 'mod', repo: 'jyoka/task-hub', event: 'In progress' },
  { time: '2026-10-04T09:50:00Z', id: '75', title: 'kiro', repo: 'jyoka/task-hub', event: 'In review',
    pr: 'https://github.com/jyoka/task-hub/pull/36', digest: { verdict: 'needs changes', review: ['a'] } },
  { time: '2026-10-04T09:55:00Z', id: '110', title: '画面', repo: 'jyoka/aica', event: 'Blocked',
    reason: '前提の PR #26 が\nまだマージされていない' },
].map(e => JSON.stringify(e)).join('\n') + '\n{"time": "2026-10-04T10:1\n1\n[]\n'
export const METRICS = [480, 540, 600].map(s => JSON.stringify({ agent: 'claude', seconds: s, status: 'In review' }))
  .concat([JSON.stringify({ agent: 'kiro', seconds: 60, status: 'In review' }), 'not json']).join('\n')
export const CONFIG = '[board]\nproject = jyoka/2\n[runner]\nagent = claude ; the default\n'
