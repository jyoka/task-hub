# タスクファイル、レポートファイル、PR の形式

## タスクファイル

各タスクはボードフォルダ `~/.local/share/task-hub/board/tasks/`(または `$TASK_HUB_DIR/tasks/`)内の
1 つの markdown ファイルです。例: `tasks/0012-fix-login.md`。ボードは非公開です。task-hub リポジトリとは別の
独自のローカル git 履歴を持ち、push されることはありません。
これらのファイルを書き込むのは `task` CLI だけです。Goal のテキストは手で編集できます。たとえばタスクを
開始する前や、ブロックされたタスクを再実行する前です。status の変更は必ず CLI で行ってください。

```markdown
---
id: 12
title: Fix login redirect
repo: jyoka/app
theme: auth
agent: codex
status: review
created: 2026-09-23
updated: 2026-09-23
branch: task/12
started: 2026-09-23T02:14:05Z
pid:
workspace: w6
worktree: /Users/jyoka/.local/share/task-hub/worktrees/12
log: /Users/jyoka/.local/state/task-hub/logs/12.log
pr: https://github.com/jyoka/app/pull/41
reason:
---
## Goal

After login, users land on / instead of the page they came from.
Keep the `next` query parameter through the OAuth round trip.

- [ ] Redirects to `next` after login
- [ ] Rejects external `next` URLs
- [ ] Tests cover both

## Report

Stored `next` in the session before the OAuth redirect and read it back in the callback.
Added 3 tests; `pytest` passes.

## Please review

- `src/auth/callback.py:40`: the allowlist check for `next` (only same-origin paths)
- I kept the old `/home` fallback when `next` is missing. Confirm that is wanted.
```

| フィールド | 設定者 | 意味 |
|---|---|---|
| `id` | CLI | 番号。このボード内で一意で、再利用されません |
| `title` | あなた | 命令形の短い要約。PR のタイトルにもなります |
| `repo` | あなた | 作業を行う GitHub の `owner/name` |
| `theme` | あなた | 任意のグループ分け |
| `agent` | あなた | このタスクのエージェント。空欄 = そのマシンのデフォルト([agents.md](agents.md)) |
| `status` | CLI | README を参照 |
| `created` / `updated` | CLI | 日付 |
| `branch` | CLI | `task/<id>`。再実行でも使い回されます |
| `started` | CLI | 最新の実行を起動した UTC 時刻 |
| `pid` | CLI | 実行中の `task _run` のプロセス。停止した実行の検出に使います |
| `workspace` | CLI | task-hub がその実行用に作成した herdr のワークスペース(herdr がない場合は空) |
| `worktree` | CLI | エージェントが作業する場所。タスクが完了すると削除されます |
| `log` | CLI | 実行の全出力(`task log <id>`) |
| `pr` | CLI | task-hub が作成した PR |
| `reason` | CLI | タスクがブロックされた理由 |

セクション: **Goal** はあなたまたは `/task` が書くもので、エージェントへの指示のすべてです。
**Report** と **Please review** は、実行終了時にエージェントのレポートファイルからコピーされます。

## エージェントのレポートファイル

毎回の実行の最後に、エージェントは worktree のルートに `.task-report.md` を書き込みます
(書き方は [worker/PROMPT.md](../worker/PROMPT.md) で指示しています)。task-hub はこれを読み取ってから削除し、
コミットすることはありません。

```markdown
## Blocked                 <- only when stuck; everything else still gets written

Need the Stripe test key.

## Report

What changed, how it was verified, what was not done.

## Please review

Exact files, decisions, and risks to check.
```

## 実行終了時の処理

| エージェントの結果 | task-hub の処理 | タスクの状態 |
|---|---|---|
| レポートあり、ファイル変更あり | コミットし、`task/<id>` を push し、レビュー可能な PR を作成 | `review` |
| `## Blocked` を含むレポート | 現状をコミットして push し、理由を付けた**ドラフト** PR を作成 | `blocked` |
| レポートなし、ファイル変更あり | push し、ドラフト PR を作成("agent exited without a report") | `blocked` |
| レポートなし、変更なし(クラッシュ) | push せず、PR も作成しない | `blocked` |
| レポートあり、変更なし | push せず、PR も作成しない | `blocked` |

再実行(ブロックされたタスクに対する `task start`)は同じブランチで作業を続け、同じ PR を更新します。
エージェントには前回のレポートとブロックされた理由が伝えられます。最新の実行で使われたプロンプトそのものは
`~/.local/share/task-hub/prompts/<id>.md` に保存されます。

## PR

- ブランチは `task/<id>`、ベースはリポジトリのデフォルトブランチ、タイトルはタスクのタイトル
- 説明: `## Blocked`(ある場合)、`## Report`、`## Please review`、およびタスク ID とエージェントを記したフッター
- GitHub でマージされた場合: 次の `task` 実行時にタスクを `done` にし、その worktree と herdr のワークスペースを削除します
- レビュー中にマージされずにクローズされた場合: タスクは `blocked` になります
