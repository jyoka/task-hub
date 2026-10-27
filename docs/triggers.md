# トリガー(task-hub が自分でカードを作る)

ふだんカードは人が作ります(`/task`、`task new`、Slackトリアージ)。`[triggers]` を書くと、`task watch` が
決まったことに気づいて、自分でカードを作ります。

| トリガー | 気づくこと | できるカード |
|---|---|---|
| `ci` | 書いたリポジトリの既定のブランチで、CI(GitHub Actions)が失敗した | 「Fix failing CI on <リポジトリ>」。本文に失敗した実行のリンク |
| `issues` | 書いたリポジトリの開いている Issue が、あなたに割り当てられた、または `issue_label` のラベルが付いた | 「<リポジトリ>#<番号>: <Issue のタイトル>」。本文にその Issue のリンク |
| 繰り返しの目標 | 決めた周期(毎日、毎週、毎月)が来た | 「<目標> (<周期>)」。例: `Bump the dependencies (2026-W42)` |

できたカードは **Backlog** に入ります。やってほしいときに、いつもどおり Ready に移します(承認するのはあなたです)。
信頼できる繰り返しの雑務だけは、`ready` に名前を書くと Ready に入り、次の確認で始まります。

## 設定

`~/.config/task-hub/config.ini` に書きます。`[triggers]` がなければ、今までと何も変わりません(GitHub への問い合わせも、
手元のファイルも増えません)。

```ini
[triggers]
ci = jyoka/app, jyoka/web        ; 既定のブランチの CI が失敗したらカードを作る
issues = jyoka/app               ; あなたに割り当てられた、開いている Issue のカードを作る
issue_label = agent              ; このラベルの付いた Issue も(書かなければ割り当てだけ)
deps = weekly mon 09:00 jyoka/app Bump the dependencies and make the tests pass
notes = monthly 1 jyoka/web Update the release notes from the merged PRs
ready = deps                     ; この繰り返しの目標のカードは Ready に入れる
```

- `ci`、`issues`、`issue_label`、`ready`、`drift_report` 以外の名前は、すべて繰り返しの目標です。名前(上の `deps`)は
  自由で、`ready` や `drift_report` で指すときと、カードがどの目標から来たかの記録に使います
- 繰り返しの目標は `<周期> <owner/repo> <目標>` です。目標の文がそのままカードの Goal とタイトルになります
- `ci` と `issues` に同じリポジトリを 2 回書いても(大文字と小文字が違っても)、1 回として扱います
- 目標の文に ` ;` と ` #` は書けません(そこから先はコメントとして読まれます)
- Agent 欄と Base branch 欄は空のまま作ります(このマシンの既定のエージェント、リポジトリの既定のブランチ)

### 周期

| 書き方 | いつ | 1 枚の単位 |
|---|---|---|
| `daily` | 毎日 | 日(`2026-10-17`) |
| `weekly`、`weekly fri` | 毎週その曜日(省略すると月曜)。`mon`〜`sun`、`monday`〜`sunday` | ISO の週(`2026-W42`) |
| `monthly`、`monthly 15` | 毎月その日(省略すると 1 日)。月にない日(`monthly 31` の 2 月)は月の最後の日 | 月(`2026-10`) |

どれにも最後に `HH:MM`(24 時間、このマシンの時刻)を付けられます。付けなければ 0:00 です。その日時を過ぎて
最初の確認でカードを 1 枚作り、同じ周期の間はもう作りません。マシンが止まっていた周期の分を、あとからまとめて
作ることはしません(今の周期の 1 枚だけです)。cron の書き方(`0 9 * * 1`)は使えません。

## 文書とコードの食い違い(drift report)

`drift_report` に繰り返しの目標の名前を書くと、その目標のカードは drift report になります。文書(仕様)とコードの
食い違いを週に 1 回調べさせる、という使い方です。Elephant-Goldfish Model の `/egm-drift-report` に当たります。
毎回のレビューは変えたところしか見ないので、変えていない文書に残った古い記述は拾えません。

task-hub 自身に対して週に 1 回(月曜 9:00)調べるなら、`[triggers]` に次の 2 行を足します。

```ini
drift = weekly mon 09:00 jyoka/task-hub Drift report: README.md docs/design.md docs/architecture/hld.md docs/architecture/lld.md docs/task-format.md against bin/task worker/
drift_report = drift
```

- 目標の文が対象です。`<文書> against <コード>` の形で、リポジトリの中のパスを書きます。フォルダはその中の全部の
  ファイルです。別のリポジトリなら、そのリポジトリと、その文書とコードを書きます。組ごとに別の名前の目標にできます
- 設定を書き換えるのはあなたです(`~/.config/task-hub/config.ini`)。書けば、動いている `task watch` の次の確認から効きます

できるカードの流れです。

1. 周期が来ると、`task watch` が research カード(`research` ラベル)を Backlog に作ります。タイトルは
   ほかの繰り返しの目標と同じく「<目標> (<周期>)」、例えば `Drift report: README.md docs/design.md ... (2026-W44)` です
2. カードの Goal は、[worker/DRIFT.md](../worker/DRIFT.md) の指示、`## Targets` の見出しと目標の文、の順です。
   指示はカードを作ったときの task-hub のものが Issue に写ります
3. あなたが Ready に移すと(`ready = drift` も書けば自動で)、ふだんのカードと同じにエージェントが動きます。
   周期ごとに新しい Issue なので、エージェントは会話も前の週のレポートも持ちません(Goldfish)。
   読むのは Targets の文書とコードだけで、git の履歴、PR、Issue、ボードは読みません。ファイルは変えません
4. エージェントのレポートが drift report です。食い違いを 1 件ずつ、文書の場所(ファイルと行)、コードの場所、
   どちらが正しそうか、直し方の案と、blocking / minor の別で並べます。research カードなので PR はなく、
   レポートが Issue のコメントになって In review に進みます([task-format.md](task-format.md))
5. 読んだら `task done` で閉じます。直すかどうか、どちらを直すかはあなたが決め、直すならカードを別に作ります

1 回の時間と token は、ほかのカードと同じく `metrics.jsonl` に記録され、`task stats` で見られます
([operations.md](operations.md#エージェントの使用量))。予算の上限もほかのカードと同じに効きます
([operations.md](operations.md#予算と残高))。
`drift_report` に書けるのは繰り返しの目標の名前だけです(違えば `task watch` が始めるときに `error:` で止まります)。

## 1 回に 1 枚

同じことに 2 枚目のカードは作りません。作ったものは `~/.local/state/task-hub/triggers.json` に記録します。

| トリガー | 「同じこと」 | 補足 |
|---|---|---|
| `ci` | 同じ実行(run の id) | ワークフローごとに、既定のブランチで最後に終わった実行だけを見ます。走っている途中の実行は数えません。失敗が続いても、そのリポジトリの「Fix failing CI」のカードが開いている間は新しいカードを作りません。カードが Done になってもまだ失敗していれば、まだカードのない実行について 1 枚作ります |
| `issues` | 同じ Issue | カードが Done になっても、同じ Issue のカードは二度と作りません |
| 繰り返しの目標 | 同じ名前の同じ周期 | |

記録は Issue ができた直後に書きます。そのあとで Project に足すのが失敗しても、2 枚目の Issue は作りません
(`trigger_errors` にその Issue の URL が出るので、手で Project に足します)。記録を書けないときは、何も作らずに
`error:` を出します。

初めて `issues` を書いたときは、その時点で条件に合う開いている Issue が全部カードになります。

## いつ確かめるか

`task watch` だけが確かめます(5 分に 1 回まで)。`task` や `task start` は確かめません。`task watch` の 1 回の確認で、
Ready のカードを始めたあとにトリガーを確かめるので、Ready に入ったカードは次の確認(1 分後)で始まります。

`task watch` の出力:

```
triggered[2]{id,trigger,status,title}:
  31,ci,Backlog,Fix failing CI on jyoka/app
  32,deps,Ready,"Bump the dependencies and make the tests pass (2026-W42)"
```

1 つのリポジトリで GitHub が失敗しても(リポジトリがない、権限がない)、watch もほかのトリガーも止まりません。
`trigger_errors` に出し、次の確認でまた試します。`[triggers]` の書き間違いは、`task watch` を始めたときに
`error:` で止まります。動いている間に書き間違えたときは、その回の `error:` に出してトリガーだけを飛ばします。

**1 つの Project は 1 台のマシンで使います**([design.md](design.md#既知の制限))。トリガーもそのマシンの
`task watch` だけで動かしてください。2 台で動かすと、記録が別々なので同じことにカードが 2 枚できます。

## GitHub の費用

すべて `gh` で問い合わせます。5 分に 1 回なので、1 時間に 12 回です。

| 問い合わせ | API | 1 回の確認で |
|---|---|---|
| `gh run list`(既定のブランチの最近 20 の実行) | REST | `ci` のリポジトリごとに 1 |
| `gh repo view`(既定のブランチの名前) | GraphQL | `ci` のリポジトリごとに 1 日 1 回 |
| `gh issue list`(割り当て、ラベル) | GraphQL | `issues` のリポジトリごとに 1(`issue_label` があれば 2) |
| カードを作る | `task new` と同じ | 作ったときだけ |

## 安全のために

- `ci` と `issues` のカードは、いつも Backlog に入ります(`ready` に書けるのは繰り返しの目標だけ)。Issue の文章は
  ボードの外で、誰かが書いたものです。エージェントに渡す前に、あなたが読んで Ready に移します
- Issue のカードの Goal は、Issue へのリンクと「リポジトリへの変更でなければ何もせずレポートに書く」という指示です。
  Issue の本文はカードにコピーしません
- ボードの Issue リポジトリ(`[board] issues`)は `issues` に書けません。その Issue はもともとタスクだからです
- `[autopilot]`([autopilot.md](autopilot.md))に書いたリポジトリのカードは、トリガーで作ったものも、人が読む前に
  Ready に移ります。Issue を書ける人を信頼できるリポジトリだけを `[autopilot]` に書きます

## 置かれるもの

| 内容 | 場所 |
|---|---|
| 作ったものの記録、最後に確かめた時刻、既定のブランチの名前 | `~/.local/state/task-hub/triggers.json` |

`triggers.json` を消すと、記録を忘れます。次の確認で、条件に合うもの(失敗している CI、開いている Issue、今の周期)の
カードがもう一度できます。
